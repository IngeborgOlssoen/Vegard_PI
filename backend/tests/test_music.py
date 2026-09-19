"""Tester Sonos-hjelperne, den simulerte Sonos-tjenesten og musikk-API-et."""
import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig, SonosConfig, SpotifyConfig
from app.errors import ServiceError
from app.main import create_app
from app.services.music import MusicService
from app.services.sonos import SimSonosService, format_clock, group_name, parse_clock
from app.services.spotify import SimSpotifyService


def test_parse_clock_and_group_name():
    assert parse_clock("0:03:21") == 201_000
    assert parse_clock("1:00:00.500") == 3_600_500
    assert parse_clock("NOT_IMPLEMENTED") == 0 and parse_clock("") == 0 and parse_clock(None) == 0
    assert group_name("Stue", ["Kjøkken", "Stue", "Bad"]) == "Stue + Bad + Kjøkken"
    assert group_name("Stue", ["Stue"]) == "Stue"
    assert format_clock(201_000) == "0:03:21" and format_clock(3_600_500) == "1:00:00" and format_clock(-5) == "0:00:00"


async def test_sim_sonos_rooms_groups_and_volume():
    sonos = SimSonosService(SonosConfig(enabled=True, simulate=True))
    rooms = await sonos.rooms()
    assert [r.name for r in rooms] == ["Bad", "Kjøkken", "Soverom", "Stue"]
    assert (await sonos.state()).device.name == "Stue" and (await sonos.state()).active is False

    # Ingenting spiller: trykk på rom = bytt rom
    await sonos.toggle_room("sim-kjokken")
    assert (await sonos.state()).device.name == "Kjøkken"

    # Start spilleliste, så blir "trykk på rom" = bli med i gruppa
    await sonos.play("spotify:playlist:x")
    st = await sonos.state()
    assert st.is_playing and st.track and st.context_uri == "spotify:playlist:x"
    await sonos.toggle_room("sim-stue")
    st = await sonos.state()
    assert st.device.name == "Kjøkken + Stue"
    assert {r.name: r.is_active for r in await sonos.rooms()} == {"Bad": False, "Kjøkken": True, "Soverom": False, "Stue": True}
    # ... og ut igjen
    await sonos.toggle_room("sim-stue")
    assert (await sonos.state()).device.name == "Kjøkken"

    await sonos.set_volume(50)                       # gruppa
    await sonos.set_volume(10, device_id="sim-bad")  # ett rom
    vols = {r.name: r.volume for r in await sonos.rooms()}
    assert vols["Kjøkken"] == 50 and vols["Bad"] == 10
    with pytest.raises(ServiceError):
        await sonos.toggle_room("finnes-ikke")


async def test_music_service_combines_sonos_and_spotify():
    sonos = SimSonosService(SonosConfig(enabled=True, simulate=True))
    spotify = SimSpotifyService(SpotifyConfig(enabled=True, simulate=True))
    music = MusicService(sonos=sonos, spotify=spotify)
    ov = await music.overview()
    assert ov.engine == "sonos" and ov.ready and len(ov.playlists) == 8 and ov.warning is None
    assert [d.name for d in ov.devices] == ["Bad", "Kjøkken", "Soverom", "Stue"]

    # Uten Spotify: fortsatt klar, men med advarsel om spillelister
    ov = await MusicService(sonos=sonos, spotify=None).overview()
    assert ov.ready and ov.playlists == [] and "Spotify" in ov.warning

    with pytest.raises(ServiceError) as exc:
        await MusicService().overview()
    assert exc.value.status == 404


def test_music_api_with_simulated_sonos(tmp_path):
    cfg = AppConfig(sonos=SonosConfig(enabled=True, simulate=True),
                    spotify=SpotifyConfig(enabled=True, simulate=True))
    cfg.lights.simulate = True
    cfg.lights.scenes_file = str(tmp_path / "scenes.json")
    with TestClient(create_app(cfg)) as client:
        ov = client.get("/api/music").json()
        assert ov["engine"] == "sonos" and ov["state"]["is_playing"] is False
        uri = ov["playlists"][1]["uri"]

        ov = client.post("/api/music/play", json={"context_uri": uri, "device_id": "sim-soverom"}).json()
        assert ov["state"]["is_playing"] and ov["state"]["context_uri"] == uri and ov["state"]["device"]["name"] == "Soverom"

        ov = client.post("/api/music/rooms/sim-bad/toggle").json()
        assert ov["state"]["device"]["name"] == "Soverom + Bad"

        ov = client.post("/api/music/volume", json={"percent": 33}).json()
        assert ov["state"]["device"]["volume"] == 33

        ov = client.post("/api/music/pause").json()
        assert ov["state"]["is_playing"] is False

        ov = client.post("/api/music/seek", json={"position_ms": 90_000}).json()
        assert 89_000 <= ov["state"]["progress_ms"] <= 91_000

        # Spilleliste-visning og start fra en bestemt sang
        pl = client.get(f"/api/music/playlists/{ov['playlists'][0]['id']}").json()
        assert pl["playlist"]["name"] == "Kveldsstemning" and len(pl["tracks"]) == 40 and pl["total_ms"] > 0
        assert pl["tracks"][7]["index"] == 7 and pl["tracks"][7]["uri"] == "spotify:track:sim7"
        ov = client.post("/api/music/play", json={"context_uri": pl["playlist"]["uri"], "offset": 7}).json()
        assert ov["state"]["track"]["uri"] == "spotify:track:sim7" and ov["state"]["is_playing"]
        assert client.get("/api/music/playlists/finnes-ikke").status_code == 404

        assert client.post("/api/music/volume", json={"percent": 150}).status_code == 422
        r = client.post("/api/music/rooms/finnes-ikke/toggle")
        assert r.status_code == 404 and "Fant ikke" in r.json()["error"]["message"]

    cfg_off = client.get("/api/config").json()["music"]
    assert cfg_off["enabled"] and cfg_off["engine"] == "sonos"


def test_music_api_disabled(client):
    r = client.get("/api/music")
    assert r.status_code == 404 and "ikke satt opp" in r.json()["error"]["message"]


class _SonosInConnectMode:
    """Later som Sonos som spiller via Spotify Connect: neste/forrige gir 701."""
    def __init__(self):
        self.calls = []

    async def next(self):
        self.calls.append("next")
        raise ServiceError("UPnP Error 701", code="sonos_transition")

    async def previous(self):
        raise ServiceError("UPnP Error 701", code="sonos_transition")

    async def pause(self):
        self.calls.append("pause")


class _SpotifyRecorder:
    logged_in = True

    def __init__(self):
        self.calls = []

    async def next(self):
        self.calls.append("next")

    async def previous(self):
        raise ServiceError("Spotify tillater ikke dette akkurat nå", code="spotify_restricted")


async def test_next_falls_back_to_spotify_when_sonos_cannot_control_queue():
    sonos, spotify = _SonosInConnectMode(), _SpotifyRecorder()
    music = MusicService(sonos=sonos, spotify=spotify)
    await music.next()
    assert sonos.calls == ["next"] and spotify.calls == ["next"]
    await music.pause()                       # virker lokalt, ingen omvei
    assert sonos.calls == ["next", "pause"] and spotify.calls == ["next"]

    with pytest.raises(ServiceError) as exc:  # begge feiler → én samlet, forståelig melding
        await music.previous()
    assert "Spotify:" in exc.value.message

    with pytest.raises(ServiceError) as exc:  # uten Spotify: Sonos sin melding
        await MusicService(sonos=_SonosInConnectMode(), spotify=None).next()
    assert exc.value.code == "sonos_transition"


class _SonosExternal:
    """Sonos i Connect-modus: alt som rører køen gir 701. Rommet heter Stue."""
    async def next(self):
        raise ServiceError("UPnP Error 701", code="sonos_transition")

    async def seek(self, ms):
        raise ServiceError("UPnP Error 701", code="sonos_transition")

    async def state(self):
        from app.services.spotify import Device, PlayerState
        return PlayerState(active=True, device=Device(id="x", name="Stue + Kjøkken"), external=True)


class _SpotifyForgotDevice:
    """Spotify som har mistet den aktive enheten til den vekkes ved navn."""
    logged_in = True

    def __init__(self, known_rooms):
        self.known = known_rooms
        self.active = False
        self.calls = []

    async def activate_device_by_name(self, name):
        self.calls.append(("activate", name))
        if name in self.known:
            self.active = True
        return self.active

    async def next(self):
        if not self.active:
            raise ServiceError("Ingen aktiv høyttaler. Velg en høyttaler først.", code="spotify_no_device")
        self.calls.append(("next",))

    async def seek(self, ms):
        if not self.active:
            raise ServiceError("Ingen aktiv høyttaler.", code="spotify_no_device")
        self.calls.append(("seek", ms))


async def test_wakes_room_in_spotify_before_retrying():
    spotify = _SpotifyForgotDevice(known_rooms=["Stue"])
    music = MusicService(sonos=_SonosExternal(), spotify=spotify)
    await music.next()
    assert spotify.calls == [("activate", "Stue"), ("next",)]
    await music.seek(5000)
    assert spotify.calls[-1] == ("seek", 5000)


async def test_clear_message_when_spotify_does_not_know_the_room():
    music = MusicService(sonos=_SonosExternal(), spotify=_SpotifyForgotDevice(known_rooms=[]))
    with pytest.raises(ServiceError) as exc:
        await music.next()
    assert "kjenner ikke rommet «Stue»" in exc.value.message


class _FakeAvTransport:
    """Later som Sonos: bare riktig (type, konto)-token gir sanger i køen."""
    def __init__(self, working):
        self.working = working
        self.calls = []

    def AddURIToQueue(self, args):
        params = dict(args)
        self.calls.append(params)
        meta = params["EnqueuedURIMetaData"]
        ok = any(f"SA_RINCON{s}_X_#Svc{s}-{a}-Token" in meta for s, a in self.working)
        return {"NumTracksAdded": "42" if ok else "0", "FirstTrackNumberEnqueued": "1"}


class _FakeZone:
    def __init__(self, working):
        self.avTransport = _FakeAvTransport(working)
        self.cleared = 0

    def clear_queue(self):
        self.cleared += 1


def test_enqueue_tries_spotify_variants_until_tracks_arrive():
    from app.services.sonos import enqueue_spotify

    zone = _FakeZone(working=[("3079", "1")])
    added = enqueue_spotify(zone, "spotify:playlist:abc123", candidates=[("2311", "0"), ("3079", "0"), ("3079", "1")])
    assert added == 42 and len(zone.avTransport.calls) == 3 and zone.cleared == 2
    first = zone.avTransport.calls[0]
    assert first["EnqueuedURI"] == "x-rincon-cpcontainer:1006206cspotify%3aplaylist%3aabc123"
    assert "object.container.playlistContainer" in first["EnqueuedURIMetaData"]

    # Nettlenke virker også, og ukjent lenke avvises
    zone = _FakeZone(working=[("2311", "0")])
    assert enqueue_spotify(zone, "https://open.spotify.com/album/xyz?si=1", candidates=[("2311", "0")]) == 42
    with pytest.raises(ServiceError):
        enqueue_spotify(zone, "https://example.com/ikke-spotify", candidates=[("2311", "0")])
    assert enqueue_spotify(_FakeZone(working=[]), "spotify:track:t", candidates=[("2311", "0")]) == 0


class _SonosEmptyQueue:
    async def play(self, context_uri=None, device_id=None, offset=None):
        raise ServiceError("Sonos la ikke sangene i køen.", code="sonos_enqueue_failed")

    async def state(self):
        from app.services.spotify import Device, PlayerState
        return PlayerState(active=False, device=Device(id="x", name="Cocina"))


class _SpotifyConnect:
    logged_in = True

    def __init__(self, knows_room):
        self.knows_room = knows_room
        self.played = []

    async def activate_device_by_name(self, name):
        return self.knows_room

    async def play(self, context_uri=None, device_id=None, offset=None):
        self.played.append((context_uri, offset))


async def test_play_falls_back_to_spotify_connect_when_queue_stays_empty():
    spotify = _SpotifyConnect(knows_room=True)
    await MusicService(sonos=_SonosEmptyQueue(), spotify=spotify).play("spotify:playlist:p", offset=3)
    assert spotify.played == [("spotify:playlist:p", 3)]

    with pytest.raises(ServiceError) as exc:
        await MusicService(sonos=_SonosEmptyQueue(), spotify=_SpotifyConnect(knows_room=False)).play("spotify:playlist:p")
    assert "Cocina" in exc.value.message


def test_spotify_track_uri_from_sonos_uri():
    from app.services.sonos import spotify_track_uri
    assert spotify_track_uri("x-sonos-spotify:spotify%3atrack%3a4uLU6hMCjMI75M1A2tKUQC?sid=9&flags=8232&sn=1") == "spotify:track:4uLU6hMCjMI75M1A2tKUQC"
    assert spotify_track_uri("x-sonos-vli:RINCON_1:2,spotify:abc") is None
    assert spotify_track_uri(None) is None


def test_parse_playlist_tracks_handles_both_item_shapes():
    from app.services.spotify import parse_playlist_tracks
    pages = [{"items": [
        {"track": {"name": "A", "uri": "spotify:track:a", "duration_ms": 1000, "artists": [{"name": "X"}], "album": {"name": "Al", "images": [{"url": "u", "width": 64}]}}},
        {"item": {"name": "B", "uri": "spotify:track:b", "duration_ms": 2000, "artists": [{"name": "Y"}, {"name": "Z"}], "album": {}}},
        {"track": None},
    ]}]
    tracks = parse_playlist_tracks(pages)
    assert [(t.index, t.title, t.artists, t.image) for t in tracks] == [(0, "A", "X", "u"), (1, "B", "Y, Z", None)]


class _Group:
    def __init__(self, coordinator, members):
        self.coordinator = coordinator
        self.members = members


class _Zone:
    """Falsk SoCo-sone med egen transporttilstand og gruppe."""
    def __init__(self, uid, name, state="STOPPED"):
        self.uid, self.player_name, self.state = uid, name, state
        self.is_visible, self.is_bridge = True, False
        self.group = _Group(self, [self])

    def get_current_transport_info(self):
        return {"current_transport_state": self.state}


def make_sonos(zones, default_room=None, selected=None):
    import time as _time
    from app.services.sonos import SonosService
    svc = SonosService(SonosConfig(enabled=True, default_room=default_room))
    svc._zones = {z.uid: z for z in zones}
    svc._last_discovery = _time.monotonic()
    svc._selected_uid = selected
    return svc


def test_target_follows_the_group_that_is_playing():
    cocina, sala, bano = _Zone("c", "Cocina"), _Zone("s", "Sala", "PLAYING"), _Zone("b", "Baño")
    svc = make_sonos([cocina, sala, bano], default_room="Cocina", selected="c")
    assert svc._target_sync().player_name == "Sala"          # musikk startet i Sala fra Sonos-appen
    assert svc._selected_uid == "s"

    sala.state, cocina.state = "STOPPED", "PLAYING"           # så tilbake til Cocina
    assert svc._target_sync().player_name == "Cocina"

    cocina.state = "PAUSED_PLAYBACK"                          # pause i valgt rom: bli der
    assert svc._target_sync().player_name == "Cocina"

    sala.state = "PLAYING"                                    # ... til noe annet faktisk spiller
    assert svc._target_sync().player_name == "Sala"


def test_target_prefers_default_room_when_several_play_and_uses_coordinator():
    cocina, sala, bano = _Zone("c", "Cocina", "PLAYING"), _Zone("s", "Sala", "PLAYING"), _Zone("b", "Baño")
    bano.group = _Group(cocina, [cocina, bano])                # Baño er med i Cocinas gruppe
    cocina.group = bano.group
    svc = make_sonos([sala, bano, cocina], default_room="Cocina")
    assert svc._target_sync().player_name == "Cocina"

    svc = make_sonos([sala, bano, cocina], selected="b")      # valgt rom er medlem → styr koordinatoren
    assert svc._target_sync().player_name == "Cocina"

    quiet = make_sonos([_Zone("x", "Xyz"), _Zone("a", "Abc")])   # ingenting spiller, ingen valg → første
    assert quiet._target_sync().player_name == "Abc"


def test_playback_source_from_uri():
    from app.services.sonos import playback_source
    assert playback_source("x-sonos-spotify:spotify%3atrack%3aabc?sid=9") == "queue"
    assert playback_source("x-sonos-vli:RINCON_1:2,spotify:abc") == "connect"
    assert playback_source("x-sonos-vli:RINCON_1:1,airplay:abc") == "airplay"
    assert playback_source("x-sonosapi-stream:s1234?sid=254") == "radio"
    assert playback_source("x-sonos-htastream:RINCON_1:spdif") == "tv"
    assert playback_source("") == "idle" and playback_source(None) == "idle"


def test_skip_falls_back_to_queue_position_when_sonos_refuses():
    from soco.exceptions import SoCoUPnPException

    class _QueueZone(_Zone):
        def __init__(self):
            super().__init__("c", "Cocina", "PLAYING")
            self.jumped = []
            self.refuse = True

        def next(self):
            if self.refuse:
                raise SoCoUPnPException("UPnP Error 701 received: Transition not available", "701", "<xml/>")

        def previous(self):
            self.next()

        def get_current_track_info(self):
            return {"uri": "x-sonos-spotify:spotify%3atrack%3aabc?sid=9", "playlist_position": "5",
                    "position": "0:01:00", "duration": "0:03:00", "title": "T"}

        def play_from_queue(self, index):
            self.jumped.append(index)

    zone = _QueueZone()
    svc = make_sonos([zone], selected="c")
    svc._skip_sync(1)
    svc._skip_sync(-1)
    assert zone.jumped == [5, 3]          # 1-basert 5 → 0-basert 4, pluss/minus én

    # Spotify Connect: ingen køposisjon å hoppe til → forklarende 701-melding med fakta
    class _ConnectZone(_QueueZone):
        def get_current_track_info(self):
            return {"uri": "x-sonos-vli:RINCON_1:2,spotify:abc", "playlist_position": "1",
                    "position": "0:00:00", "duration": "0:00:00", "title": "T"}

    svc = make_sonos([_ConnectZone()], selected="c")
    with pytest.raises(ServiceError) as exc:
        svc._skip_sync(1)
    assert exc.value.code == "sonos_transition" and "kilde: connect" in exc.value.message and "annen app" in exc.value.message
