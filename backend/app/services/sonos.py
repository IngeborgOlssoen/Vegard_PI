"""Lokal styring av Sonos-høyttalere med biblioteket SoCo.

Høyttalerne styres direkte på hjemmenettet (ingen sky, ingen innlogging):
hva som spilles, spill/pause/neste, volum per rom og gruppering av rom.
Spillelister fra Spotify startes ved å legge dem i Sonos-køen (Sonos spiller
dem med sin egen Spotify-kobling, så Spotify må være lagt til i Sonos-appen).

Hvorfor ikke bare Spotify sitt API? Det ser ofte ikke Sonos-rom som står
stille, og det får ikke lov til å styre volum på Sonos. Lokal styring virker
alltid, og reagerer raskere.

SoCo er synkront (bruker `requests`), så alle kall kjøres i en tråd via
`_run`, med tidsavbrudd, så resten av panelet aldri venter på en høyttaler.
"""
from __future__ import annotations

import asyncio
import functools
import logging
import re
import time
from typing import Optional

from app.config import SonosConfig
from app.errors import ServiceError
from app.services.spotify import Device, PlayerState, Track

log = logging.getLogger(__name__)

REDISCOVER_SECONDS = 600     # se etter nye/flyttede høyttalere så ofte
RETRY_DISCOVERY_SECONDS = 30  # ikke søk oftere enn dette når ingen ble funnet


def parse_clock(value: Optional[str]) -> int:
    """Sonos oppgir tid som "0:03:21" (timer:min:sek). Gjør om til millisekunder."""
    if not value or ":" not in value:
        return 0
    try:
        parts = [float(p) for p in value.split(":")]
    except ValueError:
        return 0
    while len(parts) < 3:
        parts.insert(0, 0.0)
    h, m, s = parts[-3:]
    return int((h * 3600 + m * 60 + s) * 1000)


def format_clock(ms: int) -> str:
    """Millisekunder → "H:MM:SS" slik Sonos vil ha det."""
    total = max(0, int(ms)) // 1000
    return f"{total // 3600}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def group_name(coordinator_name: str, member_names: list[str]) -> str:
    """"Stue + Kjøkken" for en gruppe, bare "Stue" for et enkelt rom."""
    others = [n for n in member_names if n != coordinator_name]
    return " + ".join([coordinator_name] + sorted(others))


# Sonos har to varianter av Spotify-tjenesten. Hvilken (og hvilket kontonummer)
# et system bruker, står i høyttalerens kontoliste. Legger vi spillelista i køen
# med feil variant, godtar Sonos den, men uten sanger – derfor prøver vi
# varianter til det faktisk kommer sanger i køen.
SPOTIFY_SERVICE_TYPES = ("2311", "3079")
SPOTIFY_URI = re.compile(r"spotify.*[:/](album|playlist|track|episode|show)[:/](\w+)")
DIDL_TEMPLATE = (
    '<DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" '
    'xmlns:r="urn:schemas-rinconnetworks-com:metadata-1-0/" '
    'xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">'
    '<item id="{item_id}" parentID="-1" restricted="true"><dc:title>{title}</dc:title>'
    "<upnp:class>{item_class}</upnp:class>"
    '<desc id="cdudn" nameSpace="urn:schemas-rinconnetworks-com:metadata-1-0/">'
    "SA_RINCON{service}_X_#Svc{service}-{account}-Token</desc></item></DIDL-Lite>"
)


def spotify_accounts(zone) -> list[tuple[str, str]]:
    """(tjenestetype, kontonummer) for Spotify-kontoene i Sonos-systemet, fra høyttaleren."""
    try:
        from soco.music_services.accounts import Account
        accounts = Account.get_accounts(zone)
    except Exception as exc:  # eldre/nyere firmware uten kontolista – vi prøver standardene
        log.info("Sonos: fikk ikke lest kontolista (%s), prøver standardvarianter", exc)
        return []
    found = [(acc.service_type, sn) for sn, acc in accounts.items()
             if acc.service_type in SPOTIFY_SERVICE_TYPES and not getattr(acc, "deleted", False)]
    return sorted(found, key=lambda t: int(t[1]) if str(t[1]).isdigit() else 99)


def enqueue_spotify(coord, uri: str, title: str = "", candidates: Optional[list] = None) -> int:
    """Legger en Spotify-spilleliste/-album/-sang i køen til `coord` og returnerer
    antall sanger som kom inn. Prøver konto-variantene i `candidates` (ellers de
    som leses fra høyttaleren + standardene) til Sonos legger inn sanger."""
    from soco.plugins.sharelink import SpotifyShare

    m = SPOTIFY_URI.search(uri)
    if not m:
        raise ServiceError("Dette er ikke en Spotify-lenke Sonos forstår", code="sonos_bad_uri", status=400)
    kind, ident = m.group(1), m.group(2)
    encoded = f"spotify%3a{kind}%3a{ident}"
    magic = SpotifyShare.magic()[kind]

    if candidates is None:
        candidates = spotify_accounts(coord)
        for service in SPOTIFY_SERVICE_TYPES:
            for account in ("0", "1", "2"):
                if (service, account) not in candidates:
                    candidates.append((service, account))

    for service, account in candidates:
        metadata = DIDL_TEMPLATE.format(item_id=magic["key"] + encoded, title=title, item_class=magic["class"],
                                        service=service, account=account)
        try:
            response = coord.avTransport.AddURIToQueue([
                ("InstanceID", 0), ("EnqueuedURI", magic["prefix"] + encoded), ("EnqueuedURIMetaData", metadata),
                ("DesiredFirstTrackNumberEnqueued", 0), ("EnqueueAsNext", 0),
            ])
        except Exception as exc:
            log.info("Sonos: kø-legging med Spotify-variant %s/%s avvist: %s", service, account, exc)
            continue
        added = int(response.get("NumTracksAdded") or 0)
        if added > 0:
            log.info("Sonos: la %d sanger i køen (Spotify-variant %s, konto %s)", added, service, account)
            return added
        log.info("Sonos: Spotify-variant %s/%s ga ingen sanger, prøver neste", service, account)
        coord.clear_queue()
    return 0


class SonosService:
    def __init__(self, cfg: SonosConfig):
        self.cfg = cfg
        self._zones: dict = {}                 # uid → soco.SoCo (synlige rom)
        self._selected_uid: Optional[str] = None
        self._last_context: Optional[str] = None   # spillelista vi sist startet (for markering)
        self._last_discovery = 0.0
        self._lock = asyncio.Lock()
        try:
            import soco.config
            soco.config.REQUEST_TIMEOUT = cfg.timeout_seconds
        except ImportError:
            log.error("Pakken soco mangler – kjør pip install -r backend/requirements.txt")

    # --- hjelpere -------------------------------------------------------------

    async def _run(self, fn, *args):
        """Kjører et blokkerende SoCo-kall i en tråd, med tidsavbrudd og norske feil."""
        from soco.exceptions import SoCoException
        import requests

        loop = asyncio.get_running_loop()
        try:
            return await asyncio.wait_for(loop.run_in_executor(None, functools.partial(fn, *args)),
                                          self.cfg.timeout_seconds * 3)
        except asyncio.TimeoutError:
            raise ServiceError("Sonos svarte ikke (tidsavbrudd)", code="sonos_timeout")
        except SoCoException as exc:
            code = "sonos_transition" if "701" in str(exc) else "sonos_error"
            raise ServiceError(_friendly_soco_error(exc), code=code)
        except (requests.RequestException, OSError) as exc:
            self._zones = {}  # tving nytt søk neste gang
            raise ServiceError(f"Fikk ikke kontakt med Sonos ({type(exc).__name__}). Er høyttalerne på?",
                               code="sonos_network")

    def _discover_sync(self) -> dict:
        from soco import SoCo, discover

        zones = set()
        for speaker in self.cfg.speakers:
            try:
                zones |= set(SoCo(speaker.ip).all_zones)   # alle rom i husholdningen via denne
            except Exception as exc:
                log.warning("Sonos: fikk ikke kontakt med %s: %s", speaker.ip, exc)
        if not zones:
            for zone in discover(timeout=self.cfg.discovery_timeout_seconds) or set():
                try:
                    zones |= set(zone.all_zones)
                except Exception:
                    zones.add(zone)
        out = {}
        for zone in zones:
            try:
                if zone.is_visible and not zone.is_bridge:
                    out[zone.uid] = zone
            except Exception as exc:
                log.debug("Hopper over %s: %s", getattr(zone, "ip_address", "?"), exc)
        return out

    async def ensure_zones(self) -> None:
        """Sørger for at vi kjenner høyttalerne. Søker ved oppstart, ved feil og av og til ellers."""
        age = time.monotonic() - self._last_discovery
        if self._zones and age < REDISCOVER_SECONDS:
            return
        if not self._zones and self._last_discovery and age < RETRY_DISCOVERY_SECONDS:
            raise ServiceError(self._not_found_message(), code="sonos_not_found")
        async with self._lock:
            age = time.monotonic() - self._last_discovery
            if self._zones and age < REDISCOVER_SECONDS:
                return
            self._last_discovery = time.monotonic()
            zones = await self._run(self._discover_sync)
            if zones:
                self._zones = zones
                log.info("Sonos: fant %s", ", ".join(sorted(z.player_name for z in zones.values())))
            elif not self._zones:
                raise ServiceError(self._not_found_message(), code="sonos_not_found")

    def _not_found_message(self) -> str:
        return ("Fant ingen Sonos-høyttalere på nettet. Er de på, og på samme nett? Hvis søk ikke virker "
                "(f.eks. gjennom en extender), sett sonos.speakers med IP-en til én høyttaler i config.yaml.")

    def _zone(self, uid: Optional[str]):
        zone = self._zones.get(uid or "")
        if zone is None:
            raise ServiceError("Fant ikke rommet. Er høyttaleren på?", code="sonos_no_room", status=404)
        return zone

    def _target_sync(self):
        """Rommet som styres: det valgte, ellers standardrommet, ellers et som spiller, ellers første."""
        zones = list(self._zones.values())
        zone = self._zones.get(self._selected_uid or "")
        if zone is None and self.cfg.default_room:
            wanted = self.cfg.default_room.strip().lower()
            zone = next((z for z in zones if z.player_name.lower() == wanted), None)
        if zone is None:
            for z in zones:
                try:
                    if z.is_coordinator and z.get_current_transport_info()["current_transport_state"] == "PLAYING":
                        zone = z
                        break
                except Exception:
                    continue
        if zone is None:
            zone = sorted(zones, key=lambda z: z.player_name)[0]
        self._selected_uid = zone.uid
        return zone.group.coordinator if zone.group else zone

    # --- lesing -----------------------------------------------------------------

    def _state_sync(self) -> PlayerState:
        coord = self._target_sync()
        transport = coord.get_current_transport_info().get("current_transport_state", "")
        info = coord.get_current_track_info()
        members = [m.player_name for m in coord.group.members if m.is_visible] if coord.group else [coord.player_name]
        device = Device(id=coord.uid, name=group_name(coord.player_name, members), is_active=True,
                        volume=coord.group.volume if coord.group else coord.volume, is_coordinator=True)
        title = info.get("title") or ""
        track = None
        if title:
            track = Track(title=title, artists=info.get("artist") or "", album=info.get("album") or "",
                          image=info.get("album_art") or None, duration_ms=parse_clock(info.get("duration")),
                          uri=info.get("uri") or "")
        uri = info.get("uri") or ""
        return PlayerState(active=track is not None or transport == "PLAYING", is_playing=transport == "PLAYING",
                           progress_ms=parse_clock(info.get("position")), device=device, track=track,
                           context_uri=self._last_context, external=uri.startswith("x-sonos-vli:"))

    async def state(self, fresh: bool = False) -> PlayerState:
        await self.ensure_zones()
        return await self._run(self._state_sync)

    def _rooms_sync(self) -> list[Device]:
        coord = self._target_sync()
        in_group = {m.uid for m in coord.group.members} if coord.group else {coord.uid}
        rooms = []
        for z in self._zones.values():
            rooms.append(Device(id=z.uid, name=z.player_name, is_active=z.uid in in_group,
                                volume=z.volume, is_coordinator=z.uid == coord.uid))
        return sorted(rooms, key=lambda d: d.name)

    async def rooms(self) -> list[Device]:
        await self.ensure_zones()
        return await self._run(self._rooms_sync)

    # --- styring ----------------------------------------------------------------

    def _play_sync(self, context_uri: Optional[str]) -> None:
        coord = self._target_sync()
        if context_uri:
            coord.clear_queue()
            added = enqueue_spotify(coord, context_uri)
            if added == 0:
                raise ServiceError("Sonos la ikke sangene i køen. Er Spotify lagt til i Sonos-appen med samme "
                                   "konto som spillelistene kommer fra?", code="sonos_enqueue_failed")
            coord.play_from_queue(0)
            self._last_context = context_uri
        else:
            coord.play()

    async def play(self, context_uri: Optional[str] = None, device_id: Optional[str] = None) -> None:
        await self.ensure_zones()
        if device_id:
            self._selected_uid = self._zone(device_id).uid
        await self._run(self._play_sync, context_uri)

    async def pause(self) -> None:
        await self.ensure_zones()
        await self._run(lambda: self._target_sync().pause())

    async def next(self) -> None:
        await self.ensure_zones()
        await self._run(lambda: self._target_sync().next())

    async def previous(self) -> None:
        await self.ensure_zones()
        await self._run(lambda: self._target_sync().previous())

    def _volume_sync(self, percent: int, device_id: Optional[str]) -> None:
        percent = max(0, min(100, percent))
        if device_id:
            self._zone(device_id).volume = percent
        else:
            coord = self._target_sync()
            if coord.group:
                coord.group.volume = percent
            else:
                coord.volume = percent

    async def set_volume(self, percent: int, device_id: Optional[str] = None) -> None:
        await self.ensure_zones()
        await self._run(self._volume_sync, percent, device_id)

    async def transfer(self, device_id: str, play: Optional[bool] = None) -> None:
        """Velger rommet som skal styres (og spilles i ved neste start)."""
        await self.ensure_zones()
        self._selected_uid = self._zone(device_id).uid
        if play:
            await self._run(self._play_sync, None)

    def _toggle_sync(self, uid: str) -> None:
        zone = self._zone(uid)
        coord = self._target_sync()
        if zone.uid == coord.uid:
            return  # rommet som "eier" avspillingen kan ikke fjernes fra sin egen gruppe
        in_group = zone.group is not None and zone.group.coordinator.uid == coord.uid
        if in_group:
            zone.unjoin()
        else:
            playing = coord.get_current_transport_info().get("current_transport_state") == "PLAYING"
            if playing:
                zone.join(coord)          # bli med i gruppa som spiller
            else:
                self._selected_uid = zone.uid   # ingenting spiller: bytt hvilket rom som styres

    async def toggle_room(self, device_id: str) -> None:
        """Legger et rom til / fjerner det fra gruppa som spiller, eller velger det hvis ingenting spiller."""
        await self.ensure_zones()
        await self._run(self._toggle_sync, device_id)

    async def seek(self, position_ms: int) -> None:
        """Spoler i sporet som spilles (virker når Sonos styrer køen selv)."""
        await self.ensure_zones()
        await self._run(lambda: self._target_sync().seek(format_clock(position_ms)))

    async def shuffle(self, state: bool) -> None:
        await self.ensure_zones()

        def _set():
            coord = self._target_sync()
            coord.play_mode = "SHUFFLE_NOREPEAT" if state else "NORMAL"
        await self._run(_set)


def _friendly_soco_error(exc: Exception) -> str:
    text = str(exc)
    if "701" in text:
        return ("Sonos kan ikke gjøre dette med det som spilles nå, siden avspillingen styres fra en annen app "
                "(f.eks. Spotify-appen). Start en spilleliste fra panelet, så virker alle knappene.")
    if "800" in text or "UPnP" in text and "Spotify" in text:
        return "Sonos kunne ikke spille dette. Er Spotify lagt til i Sonos-appen med samme konto?"
    return f"Sonos svarte med feil: {text}"


# ---------------------------------------------------------------------------
# Falske rom for utvikling på PC
# ---------------------------------------------------------------------------

class SimSonosService:
    """Samme grensesnitt som SonosService, men fire falske rom i minnet."""

    def __init__(self, cfg: SonosConfig):
        from app.services.spotify import _SIM_TRACKS
        self.cfg = cfg
        self._tracks = _SIM_TRACKS
        self.rooms_state = {
            "sim-stue": {"name": "Stue", "volume": 35},
            "sim-kjokken": {"name": "Kjøkken", "volume": 20},
            "sim-soverom": {"name": "Soverom", "volume": 15},
            "sim-bad": {"name": "Bad", "volume": 25},
        }
        self.groups = {uid: uid for uid in self.rooms_state}   # uid → koordinator-uid
        self._selected = "sim-stue"
        self.is_playing = False
        self.track_index = 0
        self._last_context: Optional[str] = None
        self._started = time.monotonic()
        self._paused_at = 0
        log.info("Sonos: simuleringsmodus")

    def _coord(self) -> str:
        return self.groups[self._selected]

    def _members(self, coord: str) -> list[str]:
        return [uid for uid, c in self.groups.items() if c == coord]

    def _progress(self) -> int:
        if not self.is_playing:
            return self._paused_at
        p = int((time.monotonic() - self._started) * 1000)
        if p >= 214_000:
            self.track_index += 1
            self._started = time.monotonic()
            p = 0
        return p

    async def ensure_zones(self) -> None:
        return None

    async def state(self, fresh: bool = False) -> PlayerState:
        coord = self._coord()
        names = [self.rooms_state[u]["name"] for u in self._members(coord)]
        vol = round(sum(self.rooms_state[u]["volume"] for u in self._members(coord)) / len(names))
        device = Device(id=coord, name=group_name(self.rooms_state[coord]["name"], names), is_active=True,
                        volume=vol, is_coordinator=True)
        track = None
        if self._last_context or self.is_playing or self._paused_at:
            title, artist, album = self._tracks[self.track_index % len(self._tracks)]
            track = Track(title=title, artists=artist, album=album, duration_ms=214_000)
        return PlayerState(active=track is not None, is_playing=self.is_playing, progress_ms=self._progress(),
                           device=device, track=track, context_uri=self._last_context)

    async def rooms(self) -> list[Device]:
        coord = self._coord()
        return sorted((Device(id=uid, name=r["name"], is_active=self.groups[uid] == coord, volume=r["volume"],
                              is_coordinator=uid == coord) for uid, r in self.rooms_state.items()),
                      key=lambda d: d.name)

    async def play(self, context_uri: Optional[str] = None, device_id: Optional[str] = None) -> None:
        if device_id:
            if device_id not in self.rooms_state:
                raise ServiceError("Fant ikke rommet", code="sonos_no_room", status=404)
            self._selected = device_id
        if context_uri:
            self._last_context = context_uri
            self.track_index = 0
            self._paused_at = 0
        self.is_playing = True
        self._started = time.monotonic() - self._paused_at / 1000

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
        percent = max(0, min(100, percent))
        targets = [device_id] if device_id else self._members(self._coord())
        for uid in targets:
            if uid not in self.rooms_state:
                raise ServiceError("Fant ikke rommet", code="sonos_no_room", status=404)
            self.rooms_state[uid]["volume"] = percent

    async def transfer(self, device_id: str, play: Optional[bool] = None) -> None:
        if device_id not in self.rooms_state:
            raise ServiceError("Fant ikke rommet", code="sonos_no_room", status=404)
        self._selected = device_id
        if play:
            self.is_playing = True

    async def toggle_room(self, device_id: str) -> None:
        if device_id not in self.rooms_state:
            raise ServiceError("Fant ikke rommet", code="sonos_no_room", status=404)
        coord = self._coord()
        if device_id == coord:
            return
        if self.groups[device_id] == coord:
            self.groups[device_id] = device_id       # forlat gruppa
        elif self.is_playing:
            self.groups[device_id] = coord           # bli med
        else:
            self._selected = device_id               # bytt rom

    async def seek(self, position_ms: int) -> None:
        position_ms = max(0, min(214_000, int(position_ms)))
        self._paused_at = position_ms
        self._started = time.monotonic() - position_ms / 1000

    async def shuffle(self, state: bool) -> None:
        return None
