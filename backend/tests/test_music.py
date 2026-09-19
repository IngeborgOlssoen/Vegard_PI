"""Tester Sonos-hjelperne, den simulerte Sonos-tjenesten og musikk-API-et."""
import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig, SonosConfig, SpotifyConfig
from app.errors import ServiceError
from app.main import create_app
from app.services.music import MusicService
from app.services.sonos import SimSonosService, group_name, parse_clock
from app.services.spotify import SimSpotifyService


def test_parse_clock_and_group_name():
    assert parse_clock("0:03:21") == 201_000
    assert parse_clock("1:00:00.500") == 3_600_500
    assert parse_clock("NOT_IMPLEMENTED") == 0 and parse_clock("") == 0 and parse_clock(None) == 0
    assert group_name("Stue", ["Kjøkken", "Stue", "Bad"]) == "Stue + Bad + Kjøkken"
    assert group_name("Stue", ["Stue"]) == "Stue"


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

        assert client.post("/api/music/volume", json={"percent": 150}).status_code == 422
        r = client.post("/api/music/rooms/finnes-ikke/toggle")
        assert r.status_code == 404 and "Fant ikke" in r.json()["error"]["message"]

    cfg_off = client.get("/api/config").json()["music"]
    assert cfg_off["enabled"] and cfg_off["engine"] == "sonos"


def test_music_api_disabled(client):
    r = client.get("/api/music")
    assert r.status_code == 404 and "ikke satt opp" in r.json()["error"]["message"]
