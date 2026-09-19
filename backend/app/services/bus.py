"""Sanntidsavganger fra Entur.

Entur samler kollektivdata for hele Norge, inkludert Ruters sanntid, og gir
det ut gratis via Journey Planner (GraphQL). Ingen nøkkel trengs, men de vil
ha en `ET-Client-Name`-header som sier hvem som spør (config: bus.client_name).

Holdeplasser identifiseres med NSR-id-er, f.eks. NSR:StopPlace:58366.
Finn dine med scripts/find_stop.py. En NSR:Quay:-id gir bare én plattform.
Det kan være flere holdeplasser i config (bus.stops); de hentes samtidig.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from pydantic import BaseModel, Field

from app.config import BusConfig, BusStopConfig
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
    platform: Optional[str] = None
    cancelled: bool = False


class BusData(BaseModel):
    """Avgangene fra én holdeplass."""
    stop_id: str
    stop_name: str
    departures: list[Departure] = Field(default_factory=list)
    fetched_at: str           # ISO 8601, så frontend kan vise "sist oppdatert"
    error: Optional[str] = None   # satt hvis akkurat denne holdeplassen ikke lot seg hente


class BusOverview(BaseModel):
    """Alle holdeplassene i config, i samme rekkefølge."""
    stops: list[BusData]
    fetched_at: str


_TZ_NO_COLON = re.compile(r"([+-]\d{2})(\d{2})$")


def parse_iso(value: str) -> datetime:
    """Tolker tidspunkt fra Entur. De skriver f.eks. 2026-09-19T14:00:00+0200
    (uten kolon i tidssonen), som eldre Python ikke godtar direkte."""
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    v = _TZ_NO_COLON.sub(r"\1:\2", v)
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_departures(place: dict, stop: BusStopConfig, now: datetime) -> BusData:
    """Gjør Enturs svar om til vår modell. Ren funksjon, så den er lett å teste."""
    departures: list[Departure] = []
    for call in place.get("estimatedCalls") or []:
        line = (call.get("serviceJourney") or {}).get("line") or {}
        line_code = line.get("publicCode") or "?"
        if stop.line_filter and line_code not in stop.line_filter:
            continue
        expected_raw = call.get("expectedDepartureTime") or call.get("aimedDepartureTime")
        aimed_raw = call.get("aimedDepartureTime") or expected_raw
        if not expected_raw:
            continue
        expected = parse_iso(expected_raw)
        seconds_left = (expected - now).total_seconds()
        if seconds_left < -30:
            continue  # har allerede gått
        departures.append(Departure(
            line=line_code,
            destination=(call.get("destinationDisplay") or {}).get("frontText") or "",
            mode=line.get("transportMode") or "bus",
            aimed=aimed_raw,
            expected=expected.isoformat(),
            minutes=max(0, int(seconds_left // 60)),
            realtime=bool(call.get("realtime")),
            platform=(call.get("quay") or {}).get("publicCode") or None,
            cancelled=bool(call.get("cancellation")),
        ))
    departures.sort(key=lambda d: d.expected)
    return BusData(
        stop_id=place.get("id") or stop.stop_place_id,
        stop_name=stop.name or place.get("name") or stop.stop_place_id,
        departures=departures,
        fetched_at=now.isoformat(),
    )


class BusService:
    """Henter avganger fra Entur for alle holdeplassene i config, med en kort
    mellomlagring så flere skjermer ikke gir flere kall enn nødvendig."""

    def __init__(self, cfg: BusConfig, http: httpx.AsyncClient, now=None):
        self.cfg = cfg
        self.http = http
        self._now = now or (lambda: datetime.now(timezone.utc))  # byttes ut i tester
        self._cache: Optional[BusOverview] = None
        self._cache_time = 0.0
        self._lock = asyncio.Lock()

    @property
    def _cache_seconds(self) -> float:
        return min(10.0, self.cfg.refresh_seconds / 2)

    def _cache_fresh(self) -> bool:
        return self._cache is not None and time.monotonic() - self._cache_time < self._cache_seconds

    async def get(self) -> BusOverview:
        if not self.cfg.enabled:
            raise ServiceError("Buss-kortet er skrudd av i config.yaml (bus.enabled)", code="bus_disabled", status=404)
        if self._cache_fresh():
            return self._cache
        async with self._lock:
            if self._cache_fresh():
                return self._cache
            now = self._now()
            results = await asyncio.gather(*(self._fetch_stop(stop, now) for stop in self.cfg.stops),
                                           return_exceptions=True)
            stops: list[BusData] = []
            for stop, res in zip(self.cfg.stops, results):
                if isinstance(res, ServiceError):
                    stops.append(BusData(stop_id=stop.stop_place_id, stop_name=stop.name or stop.stop_place_id,
                                         fetched_at=now.isoformat(), error=res.message))
                elif isinstance(res, Exception):
                    log.exception("Uventet feil ved henting av %s", stop.stop_place_id, exc_info=res)
                    stops.append(BusData(stop_id=stop.stop_place_id, stop_name=stop.name or stop.stop_place_id,
                                         fetched_at=now.isoformat(), error=f"Uventet feil: {res}"))
                else:
                    stops.append(res)
            if stops and all(s.error for s in stops):
                # Ingen holdeplasser lot seg hente – da er det en ordentlig feil
                raise ServiceError(stops[0].error, code="bus_unavailable")
            self._cache = BusOverview(stops=stops, fetched_at=now.isoformat())
            self._cache_time = time.monotonic()
            return self._cache

    async def _fetch_stop(self, stop: BusStopConfig, now: datetime) -> BusData:
        stop_id = stop.stop_place_id
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
            raise ServiceError(f"Fant ikke holdeplassen {stop_id}. Sjekk bus.stops i config.yaml "
                               f"(scripts/find_stop.py finner riktig id)", code="bus_unknown_stop")
        return parse_departures(place, stop, now)
