"""Fysiske knapper koblet til GPIO på Raspberry Pi (valgfritt).

Koble en trykknapp mellom en GPIO-pinne og GND. Pinnen bruker intern
pull-up, så et trykk trekker den lav. Oppsettet ligger i config.yaml:

buttons:
  enabled: true
  buttons:
    - { gpio: 17, action: scene, scene: kveld }
    - { gpio: 27, action: toggle_all }
    - { gpio: 22, action: toggle_bulb, bulb: kjokken }

Bruker `gpiozero` (følger med Raspberry Pi OS; på Pi 5 trengs også `lgpio`,
som install.sh installerer). Mangler biblioteket, logges en advarsel og
resten av panelet fungerer som før. Knappene gjør nøyaktig det samme som
API-et, så alt som virker fra skjermen kan kobles til en knapp.
"""
from __future__ import annotations

import asyncio
import logging

from app.config import ButtonConfig, ButtonsConfig
from app.errors import ServiceError
from app.services.lights import LightCommand, LightService

log = logging.getLogger(__name__)


class ButtonManager:
    def __init__(self, cfg: ButtonsConfig, lights: LightService, loop: asyncio.AbstractEventLoop):
        self.cfg = cfg
        self.lights = lights
        self.loop = loop
        self._buttons: list = []

    def start(self) -> None:
        if not self.cfg.enabled:
            return
        try:
            from gpiozero import Button
        except ImportError:
            log.warning("buttons.enabled er true, men gpiozero er ikke installert – ingen fysiske knapper. "
                        "Kjør pi/install.sh, eller `pip install gpiozero lgpio` i .venv.")
            return

        for b in self.cfg.buttons:
            try:
                btn = Button(b.gpio, pull_up=True, bounce_time=0.05)
            except Exception as exc:  # feil pinne, ikke på en Pi, mangler rettigheter ...
                log.error("Kunne ikke sette opp knapp på GPIO %s: %s", b.gpio, exc)
                continue
            btn.when_pressed = self._make_handler(b)
            self._buttons.append(btn)
            log.info("Knapp på GPIO %s → %s %s", b.gpio, b.action, b.scene or b.bulb or "")
        log.info("%d fysiske knapper klare", len(self._buttons))

    def stop(self) -> None:
        for btn in self._buttons:
            try:
                btn.close()
            except Exception:
                pass
        self._buttons.clear()

    def _make_handler(self, b: ButtonConfig):
        def handler() -> None:
            # gpiozero kaller oss fra sin egen tråd; hopp over til asyncio-løkka
            asyncio.run_coroutine_threadsafe(self.run_action(b), self.loop)
        return handler

    async def run_action(self, b: ButtonConfig) -> None:
        """Utfører handlingen for en knapp. Feil logges, men stopper ingenting."""
        try:
            if b.action == "scene":
                await self.lights.activate_scene(b.scene)
            elif b.action == "toggle_all":
                await self.lights.toggle_all()
            elif b.action == "all_on":
                await self.lights.set_all(LightCommand(on=True))
            elif b.action == "all_off":
                await self.lights.set_all(LightCommand(on=False))
            elif b.action == "toggle_bulb":
                await self.lights.toggle_bulb(b.bulb)
        except ServiceError as exc:
            log.warning("Knapp GPIO %s (%s): %s", b.gpio, b.action, exc.message)
        except Exception:
            log.exception("Uventet feil fra knapp GPIO %s", b.gpio)
