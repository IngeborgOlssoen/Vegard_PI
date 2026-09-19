"""Tester at knappehandlingene gjør det samme som API-et (uten ekte GPIO)."""
import asyncio

import pytest
from pydantic import ValidationError

from app.buttons import ButtonManager
from app.config import BulbConfig, ButtonConfig, ButtonsConfig, LightsConfig
from app.services.lights import LightService
from app.services.scenes import SceneStore


def test_button_config_requires_target():
    with pytest.raises(ValidationError):
        ButtonConfig(gpio=17, action="scene")
    with pytest.raises(ValidationError):
        ButtonConfig(gpio=17, action="toggle_bulb")
    assert ButtonConfig(gpio=17, action="toggle_all").scene is None


async def test_actions_control_lights(tmp_path):
    scenes = SceneStore(tmp_path / "scenes.json")
    lights = LightService(LightsConfig(simulate=True, bulbs=[BulbConfig(id="a", name="A"), BulbConfig(id="b", name="B")]), scenes)
    await lights.refresh_all()
    mgr = ButtonManager(ButtonsConfig(enabled=True), lights, asyncio.get_running_loop())

    await mgr.run_action(ButtonConfig(gpio=1, action="all_off"))
    assert all(not s.on for s in lights.states())
    await mgr.run_action(ButtonConfig(gpio=2, action="toggle_bulb", bulb="a"))
    assert {s.id: s.on for s in lights.states()} == {"a": True, "b": False}
    await mgr.run_action(ButtonConfig(gpio=3, action="toggle_all"))   # noen er på → alle av
    assert all(not s.on for s in lights.states())
    await mgr.run_action(ButtonConfig(gpio=4, action="scene", scene="kveld"))
    assert all(s.on and s.brightness == 35 for s in lights.states())
    # ukjent scene skal bare logges, ikke kaste
    await mgr.run_action(ButtonConfig(gpio=5, action="scene", scene="finnes_ikke"))


def test_start_without_gpiozero_is_harmless(tmp_path, monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "gpiozero":
            raise ImportError("no gpiozero here")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    lights = LightService(LightsConfig(simulate=True), SceneStore(tmp_path / "s.json"))
    mgr = ButtonManager(ButtonsConfig(enabled=True, buttons=[ButtonConfig(gpio=17, action="toggle_all")]), lights, asyncio.new_event_loop())
    mgr.start()
    mgr.stop()
