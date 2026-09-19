"""Musikk: setter sammen Sonos (avspilling, rom, volum) og Spotify (spillelister).

Frontend snakker bare med denne, via /api/music, og trenger ikke vite hvilken
motor som gjør hva:

  * sonos.enabled = true   → avspilling styres lokalt på Sonos ("engine": "sonos"),
                              spillelister hentes fra Spotify hvis den er satt opp
  * bare spotify.enabled   → alt går via Spotify Connect ("engine": "spotify"),
                              som virker for andre høyttalere enn Sonos
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from app.errors import ServiceError
from app.services.spotify import NOT_LOGGED_IN, MusicOverview, Playlist

log = logging.getLogger(__name__)


class MusicService:
    def __init__(self, sonos=None, spotify=None):
        self.sonos = sonos
        self.spotify = spotify

    @property
    def engine(self) -> str:
        return "sonos" if self.sonos else "spotify"

    @property
    def enabled(self) -> bool:
        return self.sonos is not None or self.spotify is not None

    def _check(self) -> None:
        if not self.enabled:
            raise ServiceError("Musikk er ikke satt opp (sonos.enabled / spotify.enabled i config.yaml)",
                               code="music_disabled", status=404)

    async def _playlists(self) -> tuple[list[Playlist], Optional[str]]:
        """Spillelister fra Spotify, med en advarsel i stedet for feil hvis Spotify ikke er klar."""
        if self.spotify is None:
            return [], "Spillelister vises når Spotify er satt opp (se README, «Musikk»)."
        if not self.spotify.logged_in:
            return [], NOT_LOGGED_IN
        try:
            return await self.spotify.playlists(), None
        except ServiceError as exc:
            return [], f"Spillelister: {exc.message}"

    async def overview(self) -> MusicOverview:
        self._check()
        if self.sonos is None:
            ov = await self.spotify.overview()
            ov.engine = "spotify"
            return ov
        state = await self.sonos.state()
        rooms = await self.sonos.rooms()
        playlists, warning = await self._playlists()
        return MusicOverview(ready=True, engine="sonos", state=state, devices=rooms, playlists=playlists,
                             warning=warning, fetched_at=datetime.now(timezone.utc).isoformat())

    # --- kommandoer: går til Sonos hvis den finnes, ellers Spotify ---------------

    def _player(self):
        self._check()
        return self.sonos if self.sonos is not None else self.spotify

    async def _transport(self, name: str, *args) -> None:
        """Kjører spill/pause/neste/forrige. Sonos først; spiller den noe den ikke styrer
        selv (Spotify Connect startet fra Spotify-appen), svarer den 701, og da prøver vi
        samme kommando via Spotify sitt API, som styrer avspillingen i det tilfellet."""
        player = self._player()
        try:
            await getattr(player, name)(*args)
        except ServiceError as exc:
            if exc.code != "sonos_transition":
                raise
            if self.spotify is not None and self.spotify.logged_in:
                log.info("Sonos styrer ikke køen selv – sender «%s» via Spotify", name)
                try:
                    await self._via_spotify(name, *[a for a in args if a is not None][:1] if name == "seek" else [])
                    return
                except ServiceError as spotify_exc:
                    raise ServiceError(f"{exc.message} (Spotify: {spotify_exc.message})", code=exc.code)
            raise

    async def _via_spotify(self, name: str, *args) -> None:
        """Kommando via Spotify. Har Spotify mistet Sonos-rommet som aktiv enhet (skjer etter
        en pause), vekkes rommet ved navn først, og kommandoen prøves på nytt."""
        try:
            await getattr(self.spotify, name)(*args)
        except ServiceError as exc:
            if exc.code != "spotify_no_device" or self.sonos is None:
                raise
            state = await self.sonos.state()
            room = state.device.name.split(" + ")[0] if state.device else None
            if not room or not await self.spotify.activate_device_by_name(room):
                raise ServiceError(f"{exc.message} Spotify kjenner ikke rommet «{room}» akkurat nå – start en "
                                   f"spilleliste fra panelet i stedet.", code="spotify_no_device")
            await getattr(self.spotify, name)(*args)

    async def play(self, context_uri: Optional[str] = None, device_id: Optional[str] = None) -> None:
        if context_uri:
            await self._player().play(context_uri, device_id)   # ny spilleliste går alltid til Sonos-køen
        else:
            await self._transport("play", None, device_id)

    async def pause(self) -> None:
        await self._transport("pause")

    async def next(self) -> None:
        await self._transport("next")

    async def previous(self) -> None:
        await self._transport("previous")

    async def seek(self, position_ms: int) -> None:
        await self._transport("seek", position_ms)

    async def set_volume(self, percent: int, device_id: Optional[str] = None) -> None:
        await self._player().set_volume(percent, device_id)

    async def transfer(self, device_id: str) -> None:
        await self._player().transfer(device_id)

    async def toggle_room(self, device_id: str) -> None:
        """Sonos: legg til/fjern rom i gruppa (eller velg rom). Spotify: bytt høyttaler."""
        player = self._player()
        if hasattr(player, "toggle_room"):
            await player.toggle_room(device_id)
        else:
            await player.transfer(device_id)

    async def shuffle(self, state: bool) -> None:
        await self._player().shuffle(state)

    async def refresh_state(self) -> None:
        await self._player().state(fresh=True)
