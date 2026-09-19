"""Sanntidsavganger fra Entur.

Entur samler kollektivdata for hele Norge, inkludert Ruters sanntid, og gir
det ut gratis via Journey Planner (GraphQL). Ingen nøkkel trengs, men de vil
ha en `ET-Client-Name`-header som sier hvem som spør (config: bus.client_name).

Holdeplasser identifiseres med NSR-id-er, f.eks. NSR:StopPlace:58366.
Finn din med scripts/find_stop.py. En NSR:Quay:-id gir bare én plattform.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone

import httpx
from pydantic import BaseModel

from app.config import BusConfig
from app.errors import ServiceError

log = logging.getLogger(__name__)

# Kan overstyres med miljøvariabel for å teste mot en lokal etterligning av Entur.
ENTUR_URL = os.environ.get("HJEMMEPANEL_ENTUR_URL", "https://api.entur.io/journey-planner/v3/graphql")

# Feltene vi henter for hver avgang. Samme for stopPlace og quay.
CALL_FIELDS = """
  realtime
  cancellation
  aimedDepartureTime
  expectedDepartureTime
  destinationDisplay { frontText }
  quay { publicCode }
  serviceJourney { line { publicCode transportMode } }
"""

QUERY_STOP_PLACE = f"""
query ($id: String!, $n: Int!, $range: Int!) {{
  stopPlace(id: $id) {{
    id
    name
    estimatedCalls(timeRange: $range, numberOfDepartures: $n) {{ {CALL_FIELDS} }}
  }}
}}"""

QUERY_QUAY = f"""
query ($id: String!, $n: Int!, $range: Int!) {{
  quay(id: $id) {{
    id
    name
    estimatedCalls(timeRange: $range, numberOfDepartures: $n) {{ {CALL_FIELDS} }}
  }}
}}"""


class Departure(BaseModel):
    line: str                 # linjenummer, f.eks. "31"
    destination: str          # retning/destinasjon slik den står på bussen
    mode: str                 # bus, tram, metro, rail, water, ...
    aimed: str                # rutetid (ISO 8601)
    expected: str             # forventet tid (ISO 8601) – sanntid hvis realtime=True
    minutes: int              # minutter til avgang, regnet ut da vi hentet data
    realtime: bool
    platform: str | None = None
    cancelled: bool = False


class BusData(BaseModel):
    stop_id: str
    stop_name: str
    departures: list[Departure]
    fetched_at: str           # ISO 8601, så frontend kan vise "sist oppdatert"


def parse_departures(place: dict, cfg: BusConfig, now: datetime) -> BusData:
    """Gjør Enturs svar om til vår modell. Ren funksjon, så den er lett å teste."""
    departures: list[Departure] = []
    for call in place.get("estimatedCalls") or []:
        line = (call.get("serviceJourney") or {}).get("line") or {}
        line_code = line.get("publicCode") or "?"
        if cfg.line_filter and line_code not in cfg.line_filter:
            continue
        expected_raw = call.get("expectedDepartureTime") or call.get("aimedDepartureTime")
        aimed_raw = call.get("aimedDepartureTime") or expected_raw
        if not expected_raw:
            continue
        expected = datetime.fromisoformat(expected_raw)
        seconds_left = (expected - now).total_seconds()
        if seconds_left < -30:
            continue  # har allerede gått
        departures.append(Departure(
            line=line_code,
            destination=(call.get("destinationDisplay") or {}).get("frontText") or "",
            mode=line.get("transportMode") or "bus",
            aimed=aimed_raw,
            expected=expected_raw,
            minutes=max(0, int(seconds_left // 60)),
            realtime=bool(call.get("realtime")),
            platform=(call.get("quay") or {}).get("publicCode") or None,
            cancelled=bool(call.get("cancellation")),
        ))
    departures.sort(key=lambda d: d.expected)
    return BusData(
        stop_id=place.get("id") or cfg.stop_place_id,
        stop_name=cfg.stop_name or place.get("name") or cfg.stop_place_id,
        departures=departures,
        fetched_at=now.isoformat(),
    )


class BusService:
    """Henter avganger fra Entur, med en kort mellomlagring så flere skjermer
    (eller hyppige oppdateringer) ikke gir flere kall enn nødvendig."""

    def __init__(self, cfg: BusConfig, http: httpx.AsyncClient, now=None):
        self.cfg = cfg
        self.http = http
        self._now = now or (lambda: datetime.now(timezone.utc))  # byttes ut i tester
        self._cache: BusData | None = None
        self._cache_time = 0.0
        self._lock = asyncio.Lock()

    @property
    def _cache_seconds(self) -> float:
        return min(10.0, self.cfg.refresh_seconds / 2)

    async def get(self) -> BusData:
        if not self.cfg.enabled:
            raise ServiceError("Buss-kortet er skrudd av i config.yaml (bus.enabled)", code="bus_disabled", status=404)
        if self._cache and time.monotonic() - self._cache_time < self._cache_seconds:
            return self._cache
        async with self._lock:
            if self._cache and time.monotonic() - self._cache_time < self._cache_seconds:
                return self._cache
            data = await self._fetch()
            self._cache, self._cache_time = data, time.monotonic()
            return data

    async def _fetch(self) -> BusData:
        stop_id = self.cfg.stop_place_id
        is_quay = stop_id.startswith("NSR:Quay:")
        payload = {
            "query": QUERY_QUAY if is_quay else QUERY_STOP_PLACE,
            "variables": {"id": stop_id, "n": self.cfg.number_of_departures, "range": self.cfg.time_range_seconds},
        }
        headers = {"ET-Client-Name": self.cfg.client_name, "Content-Type": "application/json"}
        try:
            resp = await self.http.post(ENTUR_URL, json=payload, headers=headers, timeout=self.cfg.timeout_seconds)
        except httpx.TimeoutException:
            raise ServiceError("Entur svarte ikke (tidsavbrudd)", code="bus_timeout")
        except httpx.HTTPError as exc:
            raise ServiceError(f"Fikk ikke kontakt med Entur ({type(exc).__name__}). Er nettet nede?", code="bus_network")

        if resp.status_code != 200:
            raise ServiceError(f"Entur svarte med feil (HTTP {resp.status_code})", code="bus_http")
        try:
            body = resp.json()
        except ValueError:
            raise ServiceError("Entur ga et uleselig svar", code="bus_bad_json")
        if body.get("errors"):
            msg = body["errors"][0].get("message", "ukjent feil")
            raise ServiceError(f"Entur avviste spørringen: {msg}", code="bus_query")

        place = (body.get("data") or {}).get("quay" if is_quay else "stopPlace")
        if place is None:
            raise ServiceError(f"Fant ikke holdeplassen {stop_id}. Sjekk bus.stop_place_id i config.yaml "
                               f"(scripts/find_stop.py finner riktig id)", code="bus_unknown_stop")
        return parse_departures(place, self.cfg, self._now())
