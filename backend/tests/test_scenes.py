"""Tester scene-logikken og lagring til fil."""
import json
import os
import time

from app.services.scenes import Scene, SceneState, SceneStore


def test_commands_for_uses_default_and_overrides():
    scene = Scene(id="x", name="X", default=SceneState(on=True, brightness=50, colortemp=2700),
                  bulbs={"soverom": SceneState(on=False)})
    cmds = scene.commands_for(["stue", "soverom"])
    assert cmds["stue"].on is True and cmds["stue"].brightness == 50 and cmds["stue"].colortemp == 2700
    assert cmds["soverom"].on is False and cmds["soverom"].brightness is None


def test_commands_for_without_default_only_touches_named_bulbs():
    scene = Scene(id="x", name="X", bulbs={"stue": SceneState(on=True, rgb=[1, 2, 3])})
    cmds = scene.commands_for(["stue", "kjokken"])
    assert list(cmds) == ["stue"] and cmds["stue"].rgb == [1, 2, 3]


def test_store_creates_defaults_and_reloads_on_change(tmp_path):
    path = tmp_path / "scenes.json"
    store = SceneStore(path)
    assert path.exists()
    assert [s.id for s in store.list()] == ["kveld", "film", "dag", "alt_av"]

    # Endre fila for hånd → leses på nytt
    data = json.loads(path.read_text(encoding="utf-8"))
    data["scenes"].append({"id": "ny", "name": "Ny", "default": {"on": True}})
    path.write_text(json.dumps(data), encoding="utf-8")
    os.utime(path, (time.time() + 5, time.time() + 5))  # sikre ny mtime
    assert "ny" in [s.id for s in store.list()]


def test_store_keeps_old_data_when_file_is_broken(tmp_path):
    path = tmp_path / "scenes.json"
    store = SceneStore(path)
    path.write_text("{ dette er ikke json", encoding="utf-8")
    os.utime(path, (time.time() + 5, time.time() + 5))
    assert len(store.list()) == 4


def test_upsert_replaces_and_appends(tmp_path):
    store = SceneStore(tmp_path / "scenes.json")
    store.upsert(Scene(id="kveld", name="Kveld 2", default=SceneState(on=True, brightness=10)))
    store.upsert(Scene(id="fest", name="Fest", icon="party", default=SceneState(on=True, rgb=[255, 0, 255])))
    ids = [s.id for s in store.list()]
    assert ids == ["kveld", "film", "dag", "alt_av", "fest"]
    assert store.get("kveld").name == "Kveld 2"
