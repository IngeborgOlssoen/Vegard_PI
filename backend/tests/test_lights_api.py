"""Tester lys-API-et mot simulerte pærer."""


def test_get_lights_lists_bulbs_and_scenes(client):
    data = client.get("/api/lights").json()
    ids = [b["id"] for b in data["bulbs"]]
    assert ids == ["stue", "kjokken", "borte"]
    assert [s["id"] for s in data["scenes"]] == ["kveld", "film", "dag", "alt_av"]


def test_unreachable_bulb_is_marked_not_crashing(client):
    bulbs = {b["id"]: b for b in client.get("/api/lights").json()["bulbs"]}
    assert bulbs["stue"]["reachable"] is True
    assert bulbs["borte"]["reachable"] is False
    assert "Ingen kontakt" in bulbs["borte"]["error"]


def test_set_bulb_color_and_brightness(client):
    r = client.post("/api/lights/bulbs/stue", json={"brightness": 40, "rgb": [255, 0, 0]})
    assert r.status_code == 200
    s = r.json()
    assert s["on"] and s["brightness"] == 40 and s["mode"] == "color" and s["rgb"] == [255, 0, 0]

    s = client.post("/api/lights/bulbs/stue", json={"colortemp": 4000}).json()
    assert s["mode"] == "white" and s["colortemp"] == 4000 and s["rgb"] is None


def test_toggle_bulb(client):
    assert client.post("/api/lights/bulbs/stue/toggle").json()["on"] is False
    assert client.post("/api/lights/bulbs/stue/toggle").json()["on"] is True


def test_set_all_and_toggle_all(client):
    bulbs = client.post("/api/lights/all", json={"on": False}).json()["bulbs"]
    assert all(not b["on"] for b in bulbs if b["reachable"])
    bulbs = client.post("/api/lights/all/toggle").json()["bulbs"]
    assert all(b["on"] for b in bulbs if b["reachable"])


def test_command_to_unreachable_bulb_gives_norwegian_error(client):
    r = client.post("/api/lights/bulbs/borte", json={"on": True})
    assert r.status_code == 503
    assert "Ingen kontakt" in r.json()["error"]["message"]


def test_unknown_bulb_is_404(client):
    r = client.post("/api/lights/bulbs/finnes_ikke", json={"on": True})
    assert r.status_code == 404
    assert "Fant ikke" in r.json()["error"]["message"]


def test_invalid_command_gives_readable_error(client):
    r = client.post("/api/lights/bulbs/stue", json={"brightness": 300})
    assert r.status_code == 422
    assert r.json()["error"]["message"].startswith("Ugyldig forespørsel")
    r = client.post("/api/lights/bulbs/stue", json={})
    assert r.status_code == 400


def test_activate_scene(client):
    bulbs = client.post("/api/lights/scenes/kveld/activate").json()["bulbs"]
    stue = next(b for b in bulbs if b["id"] == "stue")
    assert stue["on"] and stue["brightness"] == 35 and stue["colortemp"] == 2700
    bulbs = client.post("/api/lights/scenes/alt_av/activate").json()["bulbs"]
    assert all(not b["on"] for b in bulbs if b["reachable"])


def test_capture_scene_saves_current_state(client):
    client.post("/api/lights/bulbs/stue", json={"brightness": 55, "rgb": [0, 0, 255]})
    client.post("/api/lights/bulbs/kjokken", json={"on": False})
    scene = client.post("/api/lights/scenes/film/capture").json()
    assert scene["bulbs"]["stue"] == {"on": True, "brightness": 55, "rgb": [0, 0, 255]}
    assert scene["bulbs"]["kjokken"] == {"on": False}
    assert "borte" not in scene["bulbs"]  # ukjent tilstand → ikke overskrevet

    # og scenen kan brukes etterpå
    client.post("/api/lights/all", json={"on": True, "colortemp": 3000})
    bulbs = {b["id"]: b for b in client.post("/api/lights/scenes/film/activate").json()["bulbs"]}
    assert bulbs["stue"]["rgb"] == [0, 0, 255] and bulbs["kjokken"]["on"] is False


def test_put_scene(client):
    scene = {"id": "lesing", "name": "Lesing", "icon": "book",
             "default": {"on": True, "brightness": 90, "colortemp": 3500}}
    assert client.put("/api/lights/scenes/lesing", json=scene).status_code == 200
    assert "lesing" in [s["id"] for s in client.get("/api/lights/scenes").json()["scenes"]]
    assert client.put("/api/lights/scenes/annen", json=scene).status_code == 400
