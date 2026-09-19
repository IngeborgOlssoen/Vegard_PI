"""Tester Spotify-tjenesten mot etterlignede svar, og den simulerte spilleren."""
import json

import httpx
import pytest

from app.config import SpotifyConfig
from app.errors import ServiceError
from app.services.spotify import SimSpotifyService, SpotifyService, parse_player, parse_playlists

PLAYER = {
    "device": {"id": "dev1", "name": "Stue", "type": "Speaker", "is_active": True, "volume_percent": 40, "supports_volume": True},
    "is_playing": True, "progress_ms": 12345, "shuffle_state": False,
    "context": {"uri": "spotify:playlist:abc"},
    "item": {"name": "Lyse netter", "uri": "spotify:track:1", "duration_ms": 200000,
             "artists": [{"name": "Sondre Justad"}, {"name": "Noen"}],
             "album": {"name": "Ingenting i verden", "images": [
                 {"url": "big", "width": 640}, {"url": "medium", "width": 300}, {"url": "small", "width": 64}]}},
}
PLAYLISTS = {"items": [
    {"id": "p1", "name": "Kveld", "uri": "spotify:playlist:p1", "images": [{"url": "img1", "width": 300}],
     "owner": {"display_name": "Ingeborg"}, "tracks": {"total": 12}},
    None,
    {"id": "p2", "name": "Fest", "uri": "spotify:playlist:p2", "images": [], "owner": {}, "tracks": {"total": 3}},
    {"id": "p3", "name": "Uten antall", "uri": "spotify:playlist:p3", "images": [], "owner": {}},
    {"id": "p4", "name": "Nytt feltnavn", "uri": "spotify:playlist:p4", "images": [], "owner": {}, "items": {"total": 9}},
]}


def test_parse_player_and_playlists():
    s = parse_player(PLAYER)
    assert s.active and s.is_playing and s.device.name == "Stue" and s.device.volume == 40
    assert s.track.title == "Lyse netter" and s.track.artists == "Sondre Justad, Noen" and s.track.image == "medium"
    assert s.context_uri == "spotify:playlist:abc"
    assert parse_player({}).active is False
    pls = parse_playlists(PLAYLISTS)
    assert [p.name for p in pls] == ["Kveld", "Fest", "Uten antall", "Nytt feltnavn"]
    assert pls[0].image == "img1" and pls[1].image is None
    assert [p.tracks for p in pls] == [12, 3, 0, 9]   # 0 = ukjent, lista skal likevel vises


def make_service(handler, tmp_path, tokens=None, **cfg):
    path = tmp_path / "token.json"
    if tokens is not False:
        path.write_text(json.dumps(tokens or {"access_token": "old", "refresh_token": "rt", "expires_at": 0}))
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SpotifyService(SpotifyConfig(enabled=True, client_id="cid", **cfg), client, path, now=lambda: 1000.0)


async def test_not_logged_in_gives_readable_overview(tmp_path):
    svc = make_service(lambda r: httpx.Response(500), tmp_path, tokens=False)
    ov = await svc.overview()
    assert ov.ready is False and "spotify_login.py" in ov.message


async def test_refreshes_token_and_fetches_overview(tmp_path):
    seen = []

    def handler(request: httpx.Request):
        seen.append((request.method, request.url.path, request.headers.get("Authorization")))
        if request.url.path.endswith("/api/token"):
            assert b"grant_type=refresh_token" in request.content and b"client_id=cid" in request.content
            return httpx.Response(200, json={"access_token": "new", "expires_in": 3600, "refresh_token": "rt2"})
        if request.url.path.endswith("/me/player"):
            return httpx.Response(200, json=PLAYER)
        if request.url.path.endswith("/me/player/devices"):
            return httpx.Response(200, json={"devices": [PLAYER["device"], {"id": "dev2", "name": "Kjøkken"}]})
        if request.url.path.endswith("/me/playlists"):
            return httpx.Response(200, json=PLAYLISTS)
        return httpx.Response(404)

    svc = make_service(handler, tmp_path)
    ov = await svc.overview()
    assert ov.ready and ov.state.track.title == "Lyse netter"
    assert [d.name for d in ov.devices] == ["Stue", "Kjøkken"] and len(ov.playlists) == 4
    # tokenet ble fornyet én gang, brukt med "Bearer new", og ny refresh token lagret
    assert seen[0][1].endswith("/api/token") and all(a == "Bearer new" for _, _, a in seen[1:])
    assert json.loads((tmp_path / "token.json").read_text())["refresh_token"] == "rt2"


async def test_nothing_playing_is_inactive_state(tmp_path):
    def handler(request):
        if request.url.path.endswith("/api/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if request.url.path.endswith("/me/player"):
            return httpx.Response(204)
        return httpx.Response(200, json={"devices": [], "items": []})

    ov = await make_service(handler, tmp_path).overview()
    assert ov.ready and ov.state.active is False and ov.state.track is None


async def test_play_without_devices_and_error_mapping(tmp_path):
    def handler(request):
        if request.url.path.endswith("/api/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if request.url.path.endswith("/me/player"):
            return httpx.Response(204)
        if request.url.path.endswith("/me/player/devices"):
            return httpx.Response(200, json={"devices": []})
        return httpx.Response(500)

    svc = make_service(handler, tmp_path)
    with pytest.raises(ServiceError) as exc:
        await svc.play("spotify:playlist:x")
    assert "Fant ingen høyttalere" in exc.value.message

    def premium(request):
        if request.url.path.endswith("/api/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        return httpx.Response(403, json={"error": {"status": 403, "reason": "PREMIUM_REQUIRED", "message": "Premium required"}})

    with pytest.raises(ServiceError) as exc:
        await make_service(premium, tmp_path).pause()
    assert "Premium" in exc.value.message

    def expired(request):
        return httpx.Response(400, json={"error": "invalid_grant", "error_description": "Refresh token revoked"})

    with pytest.raises(ServiceError) as exc:
        await make_service(expired, tmp_path).pause()
    assert "spotify_login.py" in exc.value.message


async def test_play_uses_default_device_by_name(tmp_path):
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path, dict(request.url.params)))
        if request.url.path.endswith("/api/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if request.url.path.endswith("/me/player"):
            return httpx.Response(204)
        if request.url.path.endswith("/me/player/devices"):
            return httpx.Response(200, json={"devices": [{"id": "a", "name": "Stue"}, {"id": "b", "name": "Kjøkken"}]})
        return httpx.Response(204)

    svc = make_service(handler, tmp_path, default_device="kjøkken")
    await svc.play("spotify:playlist:p1")
    play_call = next(c for c in calls if c[1].endswith("/me/player/play"))
    assert play_call[0] == "PUT" and play_call[2]["device_id"] == "b"


async def test_simulated_player_flow():
    sim = SimSpotifyService(SpotifyConfig(enabled=True, simulate=True))
    ov = await sim.overview()
    assert ov.ready and ov.state.is_playing and ov.state.device.name == "Stue" and len(ov.playlists) == 8
    await sim.pause()
    assert (await sim.state()).is_playing is False
    await sim.play(ov.playlists[2].uri, device_id="sim-kjokken")
    st = await sim.state()
    assert st.is_playing and st.device.name == "Kjøkken" and st.context_uri == ov.playlists[2].uri
    await sim.next()
    assert (await sim.state()).track.title != ov.state.track.title
    await sim.set_volume(55)
    assert (await sim.state()).device.volume == 55
    with pytest.raises(ServiceError):
        await sim.transfer("finnes-ikke")
