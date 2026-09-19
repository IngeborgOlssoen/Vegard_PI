"""Musikk via Spotify Web API.

Sonos-høyttalere (og de fleste andre) dukker opp som "Spotify Connect"-enheter,
så gjennom Spotify kan vi se hva som spilles, starte spillelister, hoppe,
justere volum og velge hvilket rom det skal spilles i. Alt går via Spotifys
sky, så Pi-en trenger ikke å finne høyttalerne på hjemmenettet.

Krever:
  * Spotify Premium (Spotify tillater bare avspillingsstyring for Premium)
  * en app hos developer.spotify.com (gratis) – client_id i config.yaml
  * én innlogging med scripts/spotify_login.py, som lagrer en "refresh token"
    i config/spotify_token.json. Deretter fornyer backend tilgangen selv.

SpotifyService snakker med Spotify. SimSpotifyService er en falsk spiller
for utvikling på PC (spotify.simulate: true).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from pydantic import BaseModel, Field

from app.config import SpotifyConfig
from app.errors import ServiceError

log = logging.getLogger(__name__)

# Kan overstyres med miljøvariabler for å teste mot en lokal etterligning.
SPOTIFY_API = os.environ.get("HJEMMEPANEL_SPOTIFY_API", "https://api.spotify.com/v1")
SPOTIFY_TOKEN_URL = os.environ.get("HJEMMEPANEL_SPOTIFY_TOKEN_URL", "https://accounts.spotify.com/api/token")
SPOTIFY_AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
SCOPES = ("user-read-playback-state user-modify-playback-state user-read-currently-playing "
          "playlist-read-private playlist-read-collaborative")

STATE_CACHE_SECONDS = 2.0
DEVICES_CACHE_SECONDS = 20.0
PLAYLISTS_CACHE_SECONDS = 600.0


# ---------------------------------------------------------------------------
# Datamodeller til frontend
# ---------------------------------------------------------------------------

class Device(BaseModel):
    """En høyttaler / et rom."""
    id: str
    name: str
    type: str = "Speaker"
    is_active: bool = False        # spiller nå (Sonos: er med i gruppa som spiller)
    volume: Optional[int] = None
    supports_volume: bool = True
    is_coordinator: bool = False   # Sonos: rommet som "eier" avspillingen i gruppa


class Track(BaseModel):
    title: str
    artists: str
    album: str = ""
    image: Optional[str] = None   # URL til cover (eller None i simulering)
    duration_ms: int = 0
    uri: str = ""


class PlayerState(BaseModel):
    active: bool = False          # false = ingenting spilles på noen enhet
    is_playing: bool = False
    progress_ms: int = 0
    shuffle: bool = False
    device: Optional[Device] = None
    track: Optional[Track] = None
    context_uri: Optional[str] = None   # spillelista/albumet som spilles
    # Sonos: true når avspillingen styres av en annen app (Spotify Connect, AirPlay).
    # Da kan ikke høyttaleren selv hoppe i køen; neste/forrige må gå via Spotify.
    external: bool = False


class Playlist(BaseModel):
    id: str
    name: str
    uri: str
    image: Optional[str] = None
    owner: str = ""
    tracks: int = 0


class MusicOverview(BaseModel):
    ready: bool                    # false = ikke logget inn ennå
    message: Optional[str] = None  # forklaring når ready = false
    engine: str = "spotify"        # "sonos" = avspilling styres lokalt på Sonos, "spotify" = via Spotify Connect
    warning: Optional[str] = None  # advarsel som vises i kortet uten at det regnes som feil
    state: PlayerState = Field(default_factory=PlayerState)
    devices: list[Device] = Field(default_factory=list)
    playlists: list[Playlist] = Field(default_factory=list)
    fetched_at: str = ""


# ---------------------------------------------------------------------------
# Tolkning av Spotifys svar (rene funksjoner, lette å teste)
# ---------------------------------------------------------------------------

def parse_device(d: dict) -> Device:
    return Device(
        id=d.get("id") or "", name=d.get("name") or "Ukjent", type=d.get("type") or "Speaker",
        is_active=bool(d.get("is_active")), volume=d.get("volume_percent"),
        supports_volume=bool(d.get("supports_volume", True)),
    )


def parse_player(data: dict) -> PlayerState:
    if not data:
        return PlayerState()
    item = data.get("item") or {}
    track = None
    if item:
        images = (item.get("album") or {}).get("images") or (item.get("images") or [])
        # Podkast-episoder har "show" i stedet for "album"/"artists"
        artists = ", ".join(a.get("name", "") for a in item.get("artists") or [])
        if not artists and item.get("show"):
            artists = item["show"].get("name", "")
        track = Track(
            title=item.get("name") or "",
            artists=artists,
            album=(item.get("album") or {}).get("name") or "",
            image=_best_image(images, 300),
            duration_ms=int(item.get("duration_ms") or 0),
            uri=item.get("uri") or "",
        )
    device = parse_device(data["device"]) if data.get("device") else None
    return PlayerState(
        active=device is not None,
        is_playing=bool(data.get("is_playing")),
        progress_ms=int(data.get("progress_ms") or 0),
        shuffle=bool(data.get("shuffle_state")),
        device=device,
        track=track,
        context_uri=(data.get("context") or {}).get("uri"),
    )


def parse_playlists(data: dict) -> list[Playlist]:
    out = []
    for item in data.get("items") or []:
        if not item:
            continue
        out.append(Playlist(
            id=item.get("id") or "", name=item.get("name") or "Uten navn", uri=item.get("uri") or "",
            image=_best_image(item.get("images") or [], 300),
            owner=(item.get("owner") or {}).get("display_name") or "",
            tracks=int((item.get("tracks") or {}).get("total") or 0),
        ))
    return out


def _best_image(images: list, wanted: int) -> Optional[str]:
    """Velger bildet som er nærmest ønsket størrelse (Spotify gir 640/300/64)."""
    if not images:
        return None
    with_size = [i for i in images if i.get("width")]
    if not with_size:
        return images[0].get("url")
    return min(with_size, key=lambda i: abs(i["width"] - wanted)).get("url")


# ---------------------------------------------------------------------------
# Lagring av innlogging
# ---------------------------------------------------------------------------

class TokenStore:
    """Leser/skriver config/spotify_token.json."""

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> Optional[dict]:
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            log.error("Kunne ikke lese %s: %s", self.path, exc)
            return None

    def save(self, tokens: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(tokens, f, indent=2)
        os.replace(tmp, self.path)


# ---------------------------------------------------------------------------
# Den ekte tjenesten
# ---------------------------------------------------------------------------

NOT_LOGGED_IN = ("Spotify er ikke koblet til ennå. Kjør `python scripts/spotify_login.py` "
                 "på en PC med nettleser (se README).")


class SpotifyService:
    def __init__(self, cfg: SpotifyConfig, http: httpx.AsyncClient, token_path: Path, now=None):
        self.cfg = cfg
        self.http = http
        self.store = TokenStore(token_path)
        self._tokens = self.store.load()
        self._now = now or time.time
        self._lock = asyncio.Lock()
        self._state: Optional[PlayerState] = None
        self._state_time = 0.0
        self._devices: list[Device] = []
        self._devices_time = 0.0
        self._playlists: list[Playlist] = []
        self._playlists_time = 0.0
        if cfg.enabled and not cfg.client_id:
            log.warning("spotify.enabled er true, men client_id mangler i config.yaml")
        if cfg.enabled and not self.logged_in:
            log.warning("Spotify: ingen innlogging funnet (%s). Kjør scripts/spotify_login.py.", token_path)

    # --- innlogging / tokens ------------------------------------------------

    @property
    def logged_in(self) -> bool:
        return bool(self._tokens and self._tokens.get("refresh_token"))

    async def _access_token(self) -> str:
        if not self.logged_in:
            raise ServiceError(NOT_LOGGED_IN, code="spotify_not_logged_in")
        if self._tokens.get("access_token") and self._tokens.get("expires_at", 0) - 60 > self._now():
            return self._tokens["access_token"]
        async with self._lock:
            if self._tokens.get("expires_at", 0) - 60 > self._now():
                return self._tokens["access_token"]
            await self._refresh()
        return self._tokens["access_token"]

    async def _refresh(self) -> None:
        data = {"grant_type": "refresh_token", "refresh_token": self._tokens["refresh_token"],
                "client_id": self.cfg.client_id}
        try:
            resp = await self.http.post(SPOTIFY_TOKEN_URL, data=data, timeout=self.cfg.timeout_seconds)
        except httpx.HTTPError as exc:
            raise ServiceError(f"Fikk ikke fornyet Spotify-innloggingen ({type(exc).__name__}). Er nettet nede?",
                               code="spotify_network")
        if resp.status_code != 200:
            detail = ""
            try:
                detail = resp.json().get("error_description") or resp.json().get("error") or ""
            except ValueError:
                pass
            if resp.status_code in (400, 401):
                raise ServiceError(f"Spotify-innloggingen er utløpt eller ugyldig ({detail}). "
                                   f"Kjør scripts/spotify_login.py på nytt.", code="spotify_login_expired")
            raise ServiceError(f"Spotify svarte med feil ved fornying (HTTP {resp.status_code})", code="spotify_http")
        body = resp.json()
        self._tokens = {
            **self._tokens,
            "access_token": body["access_token"],
            "refresh_token": body.get("refresh_token") or self._tokens["refresh_token"],
            "expires_at": self._now() + int(body.get("expires_in", 3600)),
        }
        self.store.save(self._tokens)
        log.info("Spotify: fornyet tilgang")

    # --- generelt API-kall --------------------------------------------------

    async def _api(self, method: str, path: str, *, params=None, json=None, retry=True) -> httpx.Response:
        token = await self._access_token()
        try:
            resp = await self.http.request(method, SPOTIFY_API + path, params=params, json=json,
                                           headers={"Authorization": f"Bearer {token}"},
                                           timeout=self.cfg.timeout_seconds)
        except httpx.TimeoutException:
            raise ServiceError("Spotify svarte ikke (tidsavbrudd)", code="spotify_timeout")
        except httpx.HTTPError as exc:
            raise ServiceError(f"Fikk ikke kontakt med Spotify ({type(exc).__name__}). Er nettet nede?",
                               code="spotify_network")

        if resp.status_code == 401 and retry:
            async with self._lock:
                await self._refresh()
            return await self._api(method, path, params=params, json=json, retry=False)
        if resp.status_code == 429:
            raise ServiceError("Spotify ber oss vente litt (for mange kall)", code="spotify_rate_limited")
        if resp.status_code >= 400:
            reason, message = "", ""
            try:
                err = resp.json().get("error") or {}
                reason, message = err.get("reason") or "", err.get("message") or ""
            except ValueError:
                pass
            if reason == "PREMIUM_REQUIRED":
                raise ServiceError("Spotify Premium kreves for å styre avspilling", code="spotify_premium")
            if reason == "NO_ACTIVE_DEVICE" or resp.status_code == 404 and "device" in message.lower():
                raise ServiceError("Ingen aktiv høyttaler. Velg en høyttaler først.", code="spotify_no_device")
            if "Restriction violated" in message:
                raise ServiceError("Spotify tillater ikke dette akkurat nå (f.eks. å hoppe tilbake i det som spilles)",
                                   code="spotify_restricted")
            raise ServiceError(f"Spotify svarte med feil (HTTP {resp.status_code}) {message}".strip(),
                               code="spotify_http")
        return resp

    # --- lesing --------------------------------------------------------------

    async def overview(self) -> MusicOverview:
        if not self.cfg.enabled:
            raise ServiceError("Musikk er skrudd av i config.yaml (spotify.enabled)", code="spotify_disabled", status=404)
        if not self.logged_in:
            return MusicOverview(ready=False, message=NOT_LOGGED_IN, fetched_at=_iso_now())
        state = await self.state()
        devices = await self.devices()
        playlists = await self.playlists()
        return MusicOverview(ready=True, state=state, devices=devices, playlists=playlists, fetched_at=_iso_now())

    async def state(self, fresh: bool = False) -> PlayerState:
        if not fresh and self._state is not None and time.monotonic() - self._state_time < STATE_CACHE_SECONDS:
            return self._state
        resp = await self._api("GET", "/me/player", params={"additional_types": "track,episode"})
        if resp.status_code == 204 or not resp.content:
            self._state = PlayerState()
        else:
            self._state = parse_player(resp.json())
        self._state_time = time.monotonic()
        return self._state

    async def devices(self, fresh: bool = False) -> list[Device]:
        if not fresh and time.monotonic() - self._devices_time < DEVICES_CACHE_SECONDS:
            return self._devices
        resp = await self._api("GET", "/me/player/devices")
        self._devices = [parse_device(d) for d in resp.json().get("devices") or []]
        self._devices_time = time.monotonic()
        return self._devices

    async def playlists(self) -> list[Playlist]:
        if self._playlists and time.monotonic() - self._playlists_time < PLAYLISTS_CACHE_SECONDS:
            return self._playlists
        resp = await self._api("GET", "/me/playlists", params={"limit": min(50, self.cfg.playlist_limit)})
        self._playlists = parse_playlists(resp.json())[: self.cfg.playlist_limit]
        self._playlists_time = time.monotonic()
        return self._playlists

    # --- styring -------------------------------------------------------------

    def _invalidate(self) -> None:
        self._state_time = 0.0
        self._devices_time = 0.0

    async def _pick_device(self, device_id: Optional[str]) -> Optional[str]:
        """Finner enheten å spille på: valgt, aktiv, standard fra config, ellers første."""
        if device_id:
            return device_id
        state = await self.state()
        if state.device:
            return state.device.id
        devices = await self.devices(fresh=True)
        if not devices:
            raise ServiceError("Fant ingen høyttalere. Er Sonos på, og er Spotify lagt til i Sonos-appen?",
                               code="spotify_no_device")
        wanted = (self.cfg.default_device or "").strip().lower()
        for d in devices:
            if d.is_active or (wanted and d.name.lower() == wanted):
                return d.id
        return devices[0].id

    async def play(self, context_uri: Optional[str] = None, device_id: Optional[str] = None) -> None:
        target = await self._pick_device(device_id)
        state = await self.state()
        if context_uri:
            await self._api("PUT", "/me/player/play", params={"device_id": target}, json={"context_uri": context_uri})
        elif state.device and state.device.id != target:
            await self.transfer(target, play=True)
        else:
            await self._api("PUT", "/me/player/play", params={"device_id": target})
        self._invalidate()

    async def pause(self) -> None:
        await self._api("PUT", "/me/player/pause")
        self._invalidate()

    async def next(self) -> None:
        await self._api("POST", "/me/player/next")
        self._invalidate()

    async def previous(self) -> None:
        await self._api("POST", "/me/player/previous")
        self._invalidate()

    async def set_volume(self, percent: int, device_id: Optional[str] = None) -> None:
        params = {"volume_percent": max(0, min(100, percent))}
        if device_id:
            params["device_id"] = device_id
        await self._api("PUT", "/me/player/volume", params=params)
        self._invalidate()

    async def transfer(self, device_id: str, play: Optional[bool] = None) -> None:
        body = {"device_ids": [device_id]}
        if play is not None:
            body["play"] = play
        await self._api("PUT", "/me/player", json=body)
        self._invalidate()

    async def activate_device_by_name(self, name: str) -> bool:
        """Gjør høyttaleren med dette navnet (f.eks. Sonos-rommet "Stue") aktiv i Spotify
        igjen. Returnerer False hvis Spotify ikke kjenner den."""
        wanted = name.strip().lower()
        device = next((d for d in await self.devices(fresh=True) if d.name.strip().lower() == wanted), None)
        if device is None:
            return False
        await self.transfer(device.id, play=True)
        await asyncio.sleep(0.5)
        return True

    async def seek(self, position_ms: int) -> None:
        await self._api("PUT", "/me/player/seek", params={"position_ms": max(0, int(position_ms))})
        self._invalidate()

    async def shuffle(self, state: bool) -> None:
        await self._api("PUT", "/me/player/shuffle", params={"state": "true" if state else "false"})
        self._invalidate()


# ---------------------------------------------------------------------------
# Falsk spiller for utvikling på PC
# ---------------------------------------------------------------------------

_SIM_PLAYLISTS = [
    ("Kveldsstemning", 48), ("Fredag!", 120), ("Frokost", 35), ("Fokus", 80),
    ("Norsk pop", 64), ("Klassisk søndag", 52), ("Løpetur", 41), ("Barnas favoritter", 27),
]
_SIM_TRACKS = [
    ("Lyse netter", "Sondre Justad", "Ingenting i verden"),
    ("Skjærgårdsøy", "Halva Priset", "Sommer"),
    ("Nordlys", "Highasakite", "Silent Treatment"),
    ("Kveldssang", "Ane Brun", "It All Starts With One"),
    ("Regn", "Karpe", "Omar Sheriff"),
]


class SimSpotifyService:
    """Samme grensesnitt som SpotifyService, men alt skjer i minnet."""

    def __init__(self, cfg: SpotifyConfig):
        self.cfg = cfg
        self.devices_list = [
            Device(id="sim-stue", name="Stue", is_active=True, volume=35),
            Device(id="sim-kjokken", name="Kjøkken", volume=20),
            Device(id="sim-soverom", name="Soverom", volume=15),
            Device(id="sim-bad", name="Bad", volume=25),
        ]
        self.playlists_list = [
            Playlist(id=f"sim{i}", name=name, uri=f"spotify:playlist:sim{i}", owner="deg", tracks=n)
            for i, (name, n) in enumerate(_SIM_PLAYLISTS)
        ]
        self.is_playing = True
        self.track_index = 0
        self.context_uri = self.playlists_list[0].uri
        self.shuffle_on = False
        self._started = time.monotonic()   # når nåværende spor startet
        self._paused_at = 0                # progress da vi pauset
        log.info("Spotify: simuleringsmodus")

    @property
    def logged_in(self) -> bool:
        return True

    def _active(self) -> Device:
        return next((d for d in self.devices_list if d.is_active), self.devices_list[0])

    def _track(self) -> Track:
        title, artist, album = _SIM_TRACKS[self.track_index % len(_SIM_TRACKS)]
        return Track(title=title, artists=artist, album=album, duration_ms=214_000, uri=f"spotify:track:sim{self.track_index}")

    def _progress(self) -> int:
        if not self.is_playing:
            return self._paused_at
        p = int((time.monotonic() - self._started) * 1000)
        if p >= 214_000:          # sporet er ferdig → neste
            self.track_index += 1
            self._started = time.monotonic()
            p = 0
        return p

    async def overview(self) -> MusicOverview:
        if not self.cfg.enabled:
            raise ServiceError("Musikk er skrudd av i config.yaml (spotify.enabled)", code="spotify_disabled", status=404)
        return MusicOverview(ready=True, state=await self.state(), devices=self.devices_list,
                             playlists=self.playlists_list, fetched_at=_iso_now())

    async def state(self, fresh: bool = False) -> PlayerState:
        return PlayerState(active=True, is_playing=self.is_playing, progress_ms=self._progress(),
                           shuffle=self.shuffle_on, device=self._active(), track=self._track(),
                           context_uri=self.context_uri)

    async def devices(self, fresh: bool = False) -> list[Device]:
        return self.devices_list

    async def playlists(self) -> list[Playlist]:
        return self.playlists_list

    async def play(self, context_uri: Optional[str] = None, device_id: Optional[str] = None) -> None:
        if device_id:
            await self.transfer(device_id)
        if context_uri:
            if context_uri not in [p.uri for p in self.playlists_list]:
                raise ServiceError("Fant ikke spillelista", code="spotify_http")
            self.context_uri = context_uri
            self.track_index = 0
        self.is_playing = True
        self._started = time.monotonic() - (self._paused_at / 1000 if not context_uri else 0)

    async def pause(self) -> None:
        self._paused_at = self._progress()
        self.is_playing = False

    async def next(self) -> None:
        self.track_index += 1
        self._started, self._paused_at = time.monotonic(), 0

    async def previous(self) -> None:
        self.track_index = max(0, self.track_index - 1)
        self._started, self._paused_at = time.monotonic(), 0

    async def set_volume(self, percent: int, device_id: Optional[str] = None) -> None:
        target = next((d for d in self.devices_list if d.id == device_id), None) or self._active()
        target.volume = max(0, min(100, percent))

    async def transfer(self, device_id: str, play: Optional[bool] = None) -> None:
        if device_id not in [d.id for d in self.devices_list]:
            raise ServiceError("Fant ikke høyttaleren", code="spotify_no_device", status=404)
        for d in self.devices_list:
            d.is_active = d.id == device_id
        if play:
            self.is_playing = True

    async def activate_device_by_name(self, name: str) -> bool:
        device = next((d for d in self.devices_list if d.name.lower() == name.strip().lower()), None)
        if device is None:
            return False
        await self.transfer(device.id, play=True)
        return True

    async def seek(self, position_ms: int) -> None:
        position_ms = max(0, min(214_000, int(position_ms)))
        self._paused_at = position_ms
        self._started = time.monotonic() - position_ms / 1000

    async def shuffle(self, state: bool) -> None:
        self.shuffle_on = state


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()
