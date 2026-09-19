"""Vær fra MET (Meteorologisk institutt) – samme data som Yr.

Locationforecast 2.0 er gratis og uten nøkkel, men MET krever:
  * en User-Agent som identifiserer appen med kontaktinfo (config: weather.user_agent)
  * at vi respekterer Expires/If-Modified-Since, altså ikke spør oftere enn nødvendig
Begge deler håndteres her. Koordinater rundes til 4 desimaler (MET-krav).

Svaret er en liste av tidspunkter ("timeseries") med:
  instant.details        – temperatur, vind, fuktighet akkurat da
  next_1_hours           – symbol og nedbør for neste time (de første ~48 timene)
  next_6_hours           – symbol, nedbør, maks/min temperatur for neste 6 timer
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel

from app.config import WeatherConfig
from app.errors import ServiceError

log = logging.getLogger(__name__)

# Kan overstyres med miljøvariabel for å teste mot en lokal etterligning av MET.
MET_URL = os.environ.get("HJEMMEPANEL_MET_URL", "https://api.met.no/weatherapi/locationforecast/2.0/compact")
OSLO = ZoneInfo("Europe/Oslo")

WEEKDAYS = ["Mandag", "Tirsdag", "Onsdag", "Torsdag", "Fredag", "Lørdag", "Søndag"]
WEEKDAYS_SHORT = ["Man", "Tir", "Ons", "Tor", "Fre", "Lør", "Søn"]

# METs symbolkoder (uten _day/_night) → norsk tekst
SYMBOL_TEXT = {
    "clearsky": "Klarvær", "fair": "Lettskyet", "partlycloudy": "Delvis skyet", "cloudy": "Skyet",
    "fog": "Tåke",
    "lightrain": "Lett regn", "rain": "Regn", "heavyrain": "Kraftig regn",
    "lightrainshowers": "Lette regnbyger", "rainshowers": "Regnbyger", "heavyrainshowers": "Kraftige regnbyger",
    "lightsleet": "Lett sludd", "sleet": "Sludd", "heavysleet": "Kraftig sludd",
    "lightsleetshowers": "Lette sluddbyger", "sleetshowers": "Sluddbyger", "heavysleetshowers": "Kraftige sluddbyger",
    "lightsnow": "Lett snø", "snow": "Snø", "heavysnow": "Kraftig snø",
    "lightsnowshowers": "Lette snøbyger", "snowshowers": "Snøbyger", "heavysnowshowers": "Kraftige snøbyger",
    "lightrainandthunder": "Lett regn og torden", "rainandthunder": "Regn og torden",
    "heavyrainandthunder": "Kraftig regn og torden",
    "lightrainshowersandthunder": "Regnbyger og torden", "rainshowersandthunder": "Regnbyger og torden",
    "heavyrainshowersandthunder": "Kraftige regnbyger og torden",
    "lightsleetandthunder": "Sludd og torden", "sleetandthunder": "Sludd og torden",
    "heavysleetandthunder": "Kraftig sludd og torden",
    "lightssleetshowersandthunder": "Sluddbyger og torden", "sleetshowersandthunder": "Sluddbyger og torden",
    "heavysleetshowersandthunder": "Kraftige sluddbyger og torden",
    "lightsnowandthunder": "Snø og torden", "snowandthunder": "Snø og torden",
    "heavysnowandthunder": "Kraftig snø og torden",
    "lightssnowshowersandthunder": "Snøbyger og torden", "snowshowersandthunder": "Snøbyger og torden",
    "heavysnowshowersandthunder": "Kraftige snøbyger og torden",
}


def describe_symbol(code: str | None) -> tuple[str, str]:
    """MET-symbolkode → (ikon-navn i frontend, norsk tekst)."""
    if not code:
        return "cloud", ""
    base, _, variant = code.partition("_")
    text = SYMBOL_TEXT.get(base, base.capitalize())
    night = variant == "night"
    if "thunder" in base:
        icon = "thunder"
    elif "snow" in base:
        icon = "snow"
    elif "sleet" in base:
        icon = "sleet"
    elif "rain" in base:
        icon = "heavyrain" if base.startswith("heavy") else "rain"
    elif base == "fog":
        icon = "fog"
    elif base == "cloudy":
        icon = "cloud"
    elif base in ("partlycloudy", "fair"):
        icon = "partly_night" if night else "partly_day"
    elif base == "clearsky":
        icon = "moon" if night else "sun"
    else:
        icon = "cloud"
    return icon, text


def wind_direction_text(degrees: float | None) -> str:
    if degrees is None:
        return ""
    names = ["N", "NØ", "Ø", "SØ", "S", "SV", "V", "NV"]
    return names[int((degrees + 22.5) // 45) % 8]


def wind_text(speed: float | None) -> str:
    """Beaufort-skalaen med norske navn."""
    if speed is None:
        return ""
    steps = [(0.3, "Stille"), (1.6, "Flau vind"), (3.4, "Svak vind"), (5.5, "Lett bris"), (8.0, "Laber bris"),
             (10.8, "Frisk bris"), (13.9, "Liten kuling"), (17.2, "Stiv kuling"), (20.8, "Sterk kuling"),
             (24.5, "Liten storm"), (28.5, "Full storm"), (32.7, "Sterk storm")]
    for limit, name in steps:
        if speed < limit:
            return name
    return "Orkan"


# ---------------------------------------------------------------------------
# Datamodeller til frontend
# ---------------------------------------------------------------------------

class WeatherNow(BaseModel):
    time: str
    temp: float
    icon: str
    symbol_text: str
    wind: float                  # m/s
    wind_dir: float | None = None
    wind_dir_text: str = ""
    wind_text: str = ""
    precip_1h: float | None = None   # mm neste time
    humidity: float | None = None


class WeatherHour(BaseModel):
    time: str
    temp: float
    icon: str
    symbol_text: str
    precip: float | None = None
    wind: float | None = None


class WeatherDay(BaseModel):
    date: str
    label: str                   # "I morgen", "Ons", ...
    icon: str
    symbol_text: str
    tmax: float
    tmin: float
    precip: float


class WeatherData(BaseModel):
    place: str
    updated_at: str              # når MET sist oppdaterte varselet
    fetched_at: str
    now: WeatherNow
    hours: list[WeatherHour]
    days: list[WeatherDay]
    warning: str | None = None   # satt hvis vi viser gammelt varsel fordi ny henting feilet


# ---------------------------------------------------------------------------
# Tolkning av METs svar (ren funksjon, lett å teste)
# ---------------------------------------------------------------------------

def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_forecast(payload: dict, cfg: WeatherConfig, now: datetime) -> WeatherData:
    props = payload.get("properties") or {}
    series = props.get("timeseries") or []
    if not series:
        raise ServiceError("MET ga et tomt varsel", code="weather_empty")

    entries = [(_parse_time(e["time"]), e.get("data") or {}) for e in series]

    # "Nå" = den siste oppføringen som ikke ligger fram i tid (inntil 30 min slingringsmonn)
    current_index = 0
    for i, (t, _) in enumerate(entries):
        if t <= now + timedelta(minutes=30):
            current_index = i
        else:
            break
    t0, d0 = entries[current_index]
    inst = d0.get("instant", {}).get("details", {})
    next1 = d0.get("next_1_hours") or d0.get("next_6_hours") or {}
    icon, text = describe_symbol((next1.get("summary") or {}).get("symbol_code"))
    wind_dir = inst.get("wind_from_direction")
    weather_now = WeatherNow(
        time=t0.isoformat(),
        temp=float(inst.get("air_temperature", 0.0)),
        icon=icon, symbol_text=text,
        wind=float(inst.get("wind_speed", 0.0)),
        wind_dir=wind_dir, wind_dir_text=wind_direction_text(wind_dir),
        wind_text=wind_text(inst.get("wind_speed")),
        precip_1h=(next1.get("details") or {}).get("precipitation_amount"),
        humidity=inst.get("relative_humidity"),
    )

    # Timesvarsel: de neste timene etter "nå" som har next_1_hours
    hours: list[WeatherHour] = []
    for t, d in entries[current_index + 1:]:
        n1 = d.get("next_1_hours")
        if not n1:
            continue
        i, txt = describe_symbol((n1.get("summary") or {}).get("symbol_code"))
        di = d.get("instant", {}).get("details", {})
        hours.append(WeatherHour(
            time=t.isoformat(), temp=float(di.get("air_temperature", 0.0)), icon=i, symbol_text=txt,
            precip=(n1.get("details") or {}).get("precipitation_amount"), wind=di.get("wind_speed")))
        if len(hours) >= cfg.hours:
            break

    # Dagsvarsel: fra i morgen og cfg.days dager fram
    today = now.astimezone(OSLO).date()
    days: list[WeatherDay] = []
    for offset in range(1, cfg.days + 1):
        date = today + timedelta(days=offset)
        day = _summarize_day(entries, date)
        if day is None:
            continue
        label = "I morgen" if offset == 1 else WEEKDAYS_SHORT[date.weekday()]
        days.append(WeatherDay(date=date.isoformat(), label=label, **day))

    meta = props.get("meta") or {}
    return WeatherData(
        place=cfg.place_name,
        updated_at=meta.get("updated_at") or now.isoformat(),
        fetched_at=now.isoformat(),
        now=weather_now, hours=hours, days=days,
    )


def _summarize_day(entries, date) -> dict | None:
    """Maks/min-temperatur, nedbør og symbol for én lokal dato."""
    local = [(t.astimezone(OSLO), d) for t, d in entries]
    on_day = [(t, d) for t, d in local if t.date() == date]
    if not on_day:
        return None

    temps: list[float] = []
    for _, d in on_day:
        inst = d.get("instant", {}).get("details", {})
        if "air_temperature" in inst:
            temps.append(float(inst["air_temperature"]))
        n6 = (d.get("next_6_hours") or {}).get("details") or {}
        for key in ("air_temperature_max", "air_temperature_min"):
            if key in n6:
                temps.append(float(n6[key]))
    if not temps:
        return None

    # Nedbør: fire 6-timersblokker (00, 06, 12, 18). Bruk next_6_hours der den finnes,
    # ellers summer next_1_hours for timene i blokken.
    by_hour = {t.hour: d for t, d in on_day}
    precip = 0.0
    for block in (0, 6, 12, 18):
        n6 = (by_hour.get(block) or {}).get("next_6_hours")
        if n6 and "precipitation_amount" in (n6.get("details") or {}):
            precip += float(n6["details"]["precipitation_amount"])
        else:
            for h in range(block, block + 6):
                n1 = (by_hour.get(h) or {}).get("next_1_hours")
                if n1:
                    precip += float((n1.get("details") or {}).get("precipitation_amount", 0.0))

    # Symbol: helst 6-timersvarselet fra kl. 12 (dagen), ellers 06, ellers noe annet
    symbol = None
    for hour in (12, 6, 0, 18):
        n6 = (by_hour.get(hour) or {}).get("next_6_hours")
        if n6 and (n6.get("summary") or {}).get("symbol_code"):
            symbol = n6["summary"]["symbol_code"]
            break
    if symbol is None:
        for _, d in on_day:
            for key in ("next_6_hours", "next_1_hours"):
                code = ((d.get(key) or {}).get("summary") or {}).get("symbol_code")
                if code:
                    symbol = code
                    break
            if symbol:
                break
    icon, text = describe_symbol(symbol)
    return {"icon": icon, "symbol_text": text, "tmax": max(temps), "tmin": min(temps), "precip": round(precip, 1)}


# ---------------------------------------------------------------------------
# Tjenesten
# ---------------------------------------------------------------------------

class WeatherService:
    def __init__(self, cfg: WeatherConfig, http: httpx.AsyncClient, now=None):
        self.cfg = cfg
        self.http = http
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._cache: WeatherData | None = None
        self._raw: dict | None = None        # siste rå-svar, så vi kan regne ut "nå" på nytt uten å hente
        self._fetched_at = 0.0               # monotonic
        self._expires: datetime | None = None
        self._last_modified: str | None = None
        self._lock = asyncio.Lock()
        if "example.com" in cfg.user_agent or "bytt-meg" in cfg.user_agent:
            log.warning("weather.user_agent i config.yaml er ikke endret – MET kan avvise kallene. "
                        "Sett den til f.eks. 'hjemmepanel/1.0 (din@epost.no)'.")

    def _should_fetch(self) -> bool:
        if self._raw is None:
            return True
        if time.monotonic() - self._fetched_at < self.cfg.refresh_seconds:
            return False
        if self._expires and self._now() < self._expires:
            return False
        return True

    async def get(self) -> WeatherData:
        if not self.cfg.enabled:
            raise ServiceError("Vær-kortet er skrudd av i config.yaml (weather.enabled)", code="weather_disabled", status=404)
        warning = None
        if self._should_fetch():
            async with self._lock:
                if self._should_fetch():
                    try:
                        await self._fetch()
                    except ServiceError as exc:
                        if self._raw is None:
                            raise
                        # Vis forrige varsel, men si fra om at det er gammelt
                        log.warning("Oppdatering fra MET feilet: %s", exc.message)
                        warning = f"Fikk ikke nytt varsel: {exc.message}"
        # "Nå" og timesvarselet regnes alltid ut fra nåværende klokkeslett
        data = parse_forecast(self._raw, self.cfg, self._now())
        data.warning = warning
        self._cache = data
        return data

    async def _fetch(self) -> None:
        params = {"lat": round(self.cfg.lat, 4), "lon": round(self.cfg.lon, 4)}
        headers = {"User-Agent": self.cfg.user_agent}
        if self._last_modified:
            headers["If-Modified-Since"] = self._last_modified
        try:
            resp = await self.http.get(MET_URL, params=params, headers=headers, timeout=self.cfg.timeout_seconds)
        except httpx.TimeoutException:
            raise ServiceError("MET svarte ikke (tidsavbrudd)", code="weather_timeout")
        except httpx.HTTPError as exc:
            raise ServiceError(f"Fikk ikke kontakt med MET ({type(exc).__name__}). Er nettet nede?", code="weather_network")

        self._fetched_at = time.monotonic()
        self._expires = _parse_http_date(resp.headers.get("Expires"))

        if resp.status_code == 304:
            return  # ingenting nytt siden sist – behold det vi har
        if resp.status_code == 403:
            raise ServiceError("MET avviste kallet (HTTP 403). Sett weather.user_agent i config.yaml til noe "
                               "som identifiserer deg, f.eks. 'hjemmepanel/1.0 (din@epost.no)'", code="weather_forbidden")
        if resp.status_code == 429:
            raise ServiceError("MET ber oss vente (for mange kall)", code="weather_rate_limited")
        if resp.status_code != 200:
            raise ServiceError(f"MET svarte med feil (HTTP {resp.status_code})", code="weather_http")
        try:
            payload = resp.json()
        except ValueError:
            raise ServiceError("MET ga et uleselig svar", code="weather_bad_json")
        if not (payload.get("properties") or {}).get("timeseries"):
            raise ServiceError("MET ga et tomt varsel", code="weather_empty")

        self._raw = payload
        self._last_modified = resp.headers.get("Last-Modified")


def _parse_http_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
