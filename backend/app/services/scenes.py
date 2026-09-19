"""Lys-scener: ferdige innstillinger for alle pærene ("Kveld", "Film", "Alt av").

Scenene ligger i config/scenes.json. Fila leses på nytt automatisk når den
endres, så du kan redigere den for hånd mens appen kjører. Fra skjermen kan
en scene overskrives med nåværende tilstand (hold scene-knappen inne).

Format:
{
  "scenes": [
    {
      "id": "kveld", "name": "Kveld", "icon": "moon",
      "default": {"on": true, "brightness": 35, "colortemp": 2700},
      "bulbs":   {"soverom": {"on": false}}
    }
  ]
}
`default` gjelder alle pærer som ikke er nevnt under `bulbs`. Utelates
`default`, styres bare pærene som er nevnt.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from app.errors import ServiceError
from app.services.lights import LightCommand

log = logging.getLogger(__name__)

SCENE_ICONS = ["moon", "film", "off", "sun", "star", "coffee", "book", "party"]


class SceneState(BaseModel):
    """Ønsket tilstand for én pære i en scene."""
    on: bool = True
    brightness: int | None = Field(default=None, ge=0, le=100)
    colortemp: int | None = Field(default=None, ge=1000, le=10000)
    rgb: list[int] | None = None

    @field_validator("rgb")
    @classmethod
    def _check_rgb(cls, value):
        if value is not None and (len(value) != 3 or any(not 0 <= c <= 255 for c in value)):
            raise ValueError("rgb må være [r, g, b] med verdier 0–255")
        return value

    def to_command(self) -> LightCommand:
        if not self.on:
            return LightCommand(on=False)
        return LightCommand(on=True, brightness=self.brightness, colortemp=self.colortemp, rgb=self.rgb)


class Scene(BaseModel):
    id: str
    name: str
    icon: str = "star"
    default: SceneState | None = None
    bulbs: dict[str, SceneState] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        if not value or any(c in value for c in " /?#"):
            raise ValueError("Scene-id kan ikke inneholde mellomrom eller /?#")
        return value

    def commands_for(self, bulb_ids: list[str]) -> dict[str, LightCommand]:
        """Kommandoen som skal sendes til hver pære når scenen aktiveres."""
        out: dict[str, LightCommand] = {}
        for bid in bulb_ids:
            state = self.bulbs.get(bid, self.default)
            if state is not None:
                out[bid] = state.to_command()
        return out


class ScenesFile(BaseModel):
    scenes: list[Scene] = Field(default_factory=list)


DEFAULT_SCENES = ScenesFile(scenes=[
    Scene(id="kveld", name="Kveld", icon="moon", default=SceneState(on=True, brightness=35, colortemp=2700)),
    Scene(id="film", name="Film", icon="film", default=SceneState(on=True, brightness=15, rgb=[255, 120, 40])),
    Scene(id="dag", name="Dag", icon="sun", default=SceneState(on=True, brightness=100, colortemp=4200)),
    Scene(id="alt_av", name="Alt av", icon="off", default=SceneState(on=False)),
])


class SceneStore:
    """Leser og skriver scenes.json. Holder en kopi i minnet og leser på nytt ved endring."""

    def __init__(self, path: Path):
        self.path = path
        self._mtime: float | None = None
        self._data = ScenesFile()
        self._ensure_file()
        self._reload_if_changed()

    def _ensure_file(self) -> None:
        if self.path.exists():
            return
        example = self.path.with_name("scenes.example.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if example.exists():
            shutil.copy(example, self.path)
            log.info("Laget %s fra %s", self.path.name, example.name)
        else:
            self._write(DEFAULT_SCENES)
            log.info("Laget %s med standardscener", self.path)

    def _reload_if_changed(self) -> None:
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            self._ensure_file()
            mtime = self.path.stat().st_mtime
        if mtime == self._mtime:
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                self._data = ScenesFile.model_validate(json.load(f))
            self._mtime = mtime
            log.info("Leste %d scener fra %s", len(self._data.scenes), self.path)
        except Exception as exc:
            # En skrivefeil i JSON skal ikke ta ned appen – behold forrige versjon.
            log.error("Kunne ikke lese %s: %s", self.path, exc)
            if self._mtime is None:
                self._data = DEFAULT_SCENES
                self._mtime = mtime

    def _write(self, data: ScenesFile) -> None:
        # Skriv til midlertidig fil og bytt, så fila aldri blir halvskrevet ved strømbrudd.
        tmp = self.path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data.model_dump(exclude_none=True), f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, self.path)
        self._data = data
        self._mtime = self.path.stat().st_mtime

    # --- API -------------------------------------------------------------------

    def list(self) -> list[Scene]:
        self._reload_if_changed()
        return list(self._data.scenes)

    def get(self, scene_id: str) -> Scene:
        for scene in self.list():
            if scene.id == scene_id:
                return scene
        raise ServiceError(f"Fant ikke scenen «{scene_id}»", code="scene_not_found", status=404)

    def upsert(self, scene: Scene) -> Scene:
        """Erstatter scenen med samme id, eller legger den til bakerst."""
        scenes = self.list()
        for i, existing in enumerate(scenes):
            if existing.id == scene.id:
                scenes[i] = scene
                break
        else:
            scenes.append(scene)
        self._write(ScenesFile(scenes=scenes))
        return scene
