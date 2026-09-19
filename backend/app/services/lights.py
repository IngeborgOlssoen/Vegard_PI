"""Styring av WiZ-pærer, lokalt på hjemmenettet.

WiZ-pærer kan styres direkte over UDP (port 38899) uten sky. Vi bruker
biblioteket `pywizlight` til selve protokollen. Denne fila legger på:

  * LightCommand  – det man kan be en pære om (av/på, lysstyrke, farge, temperatur)
  * BulbState     – slik vi beskriver en pære til frontend
  * WizBulb       – snakker med en ekte pære
  * SimBulb       – falsk pære i minnet (for utvikling på PC uten pærer)
  * LightService  – holder oversikt over alle pærene, spør dem jevnlig om
                    status og utfører kommandoer og scener

Alle feil mot en pære gjøres om til ServiceError med norsk melding, og en pære
som ikke svarer merkes som `reachable: false` i stedet for å stoppe resten.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator

from app.config import BulbConfig, LightsConfig
from app.errors import ServiceError

if TYPE_CHECKING:  # bare for typehint, unngår sirkulær import
    from app.services.scenes import Scene, SceneStore

log = logging.getLogger(__name__)

REDISCOVER_INTERVAL = 300  # sekunder mellom hvert automatiske søk etter pærer
REDISCOVER_AFTER_FAILURES = 3  # så mange mislykkede spørringer før vi søker


# ---------------------------------------------------------------------------
# Datamodeller
# ---------------------------------------------------------------------------

class LightCommand(BaseModel):
    """En endring vi vil gjøre på en pære. Bare feltene som er satt endres.

    - on: True/False. Utelatt + andre felt satt = pæra skrus på (som i WiZ-appen)
    - brightness: 0–100 %. WiZ dimmer ikke lavere enn 10 %; 0 tolkes som av.
    - colortemp: kelvin, typisk 2200 (varmt) – 6500 (kaldt)
    - rgb: [r, g, b] 0–255. Har forrang over colortemp hvis begge er satt.
    """
    on: bool | None = None
    brightness: int | None = Field(default=None, ge=0, le=100)
    colortemp: int | None = Field(default=None, ge=1000, le=10000)
    rgb: list[int] | None = None

    @field_validator("rgb")
    @classmethod
    def _check_rgb(cls, value):
        if value is not None and (len(value) != 3 or any(not 0 <= c <= 255 for c in value)):
            raise ValueError("rgb må være [r, g, b] med verdier 0–255")
        return value

    def is_empty(self) -> bool:
        return self.on is None and self.brightness is None and self.colortemp is None and self.rgb is None


class BulbFeatures(BaseModel):
    """Hva pæra kan (leses fra pæra – noen WiZ-pærer har bare hvitt lys)."""
    color: bool = True
    colortemp: bool = True
    brightness: bool = True
    kelvin_min: int = 2200
    kelvin_max: int = 6500


class BulbState(BaseModel):
    id: str
    name: str
    reachable: bool = False
    on: bool = False
    brightness: int = 0          # 0–100
    mode: str = "white"          # "white" (fargetemperatur), "color" (rgb) eller "scene" (WiZ-innebygd)
    colortemp: int | None = None
    rgb: list[int] | None = None
    scene_name: str | None = None
    features: BulbFeatures = Field(default_factory=BulbFeatures)
    error: str | None = None     # norsk feilmelding hvis reachable = false
    updated_at: float = 0.0      # unix-tid for siste vellykkede/mislykkede spørring


# ---------------------------------------------------------------------------
# Drivere: én per pære
# ---------------------------------------------------------------------------

class BulbDriver:
    """Felles grensesnitt for en pære. `state` er siste kjente tilstand."""

    def __init__(self, cfg: BulbConfig):
        self.cfg = cfg
        self.state = BulbState(id=cfg.id, name=cfg.name)

    async def fetch(self) -> BulbState:
        """Spør pæra om nåværende tilstand og returnerer den (oppdaterer også self.state)."""
        raise NotImplementedError

    async def apply(self, cmd: LightCommand) -> None:
        """Sender en kommando til pæra."""
        raise NotImplementedError

    async def set_ip(self, ip: str) -> None:
        self.cfg.ip = ip

    async def close(self) -> None:
        pass


class SimBulb(BulbDriver):
    """Falsk pære som bare lever i minnet. Brukes når lights.simulate = true.

    Tips: sett `ip: unreachable` på en simulert pære i config for å se hvordan
    en pære uten kontakt vises på skjermen.
    """

    def __init__(self, cfg: BulbConfig):
        super().__init__(cfg)
        self.state = BulbState(
            id=cfg.id, name=cfg.name, on=True,
            brightness=80, mode="white", colortemp=2700,
        )

    async def fetch(self) -> BulbState:
        await asyncio.sleep(0.02)  # litt "nettverk"
        if self.cfg.ip == "unreachable":
            raise ServiceError(f"Ingen kontakt med «{self.cfg.name}» (simulert)", code="bulb_unreachable")
        return self.state

    async def apply(self, cmd: LightCommand) -> None:
        await asyncio.sleep(0.02)
        if self.cfg.ip == "unreachable":
            raise ServiceError(f"Ingen kontakt med «{self.cfg.name}» (simulert)", code="bulb_unreachable")
        s = self.state
        if cmd.on is False or cmd.brightness == 0:
            s.on = False
            return
        s.on = True
        if cmd.brightness is not None:
            s.brightness = max(10, cmd.brightness)
        if cmd.rgb is not None:
            s.mode, s.rgb, s.colortemp = "color", list(cmd.rgb), None
        elif cmd.colortemp is not None:
            s.mode, s.colortemp, s.rgb = "white", cmd.colortemp, None
        s.scene_name = None


class WizBulb(BulbDriver):
    """Ekte WiZ-pære via pywizlight."""

    def __init__(self, cfg: BulbConfig, timeout: float):
        super().__init__(cfg)
        self.timeout = timeout
        self._light = None          # pywizlight.wizlight, lages ved første bruk
        self._features_loaded = False

    def _light_or_raise(self):
        from pywizlight import wizlight  # importeres her så simulate-modus ikke trenger biblioteket

        if not self.cfg.ip:
            raise ServiceError(
                f"Pæra «{self.cfg.name}» mangler IP-adresse. Kjør scripts/discover_bulbs.py "
                f"eller fyll inn mac i config.yaml.", code="bulb_no_ip")
        if self._light is None:
            self._light = wizlight(self.cfg.ip, mac=self.cfg.mac)
        return self._light

    async def _call(self, coro, timeout: float | None = None):
        """Kjører et pywizlight-kall med tidsavbrudd og oversetter feil til ServiceError."""
        from pywizlight.exceptions import WizLightConnectionError, WizLightTimeOutError

        name = self.cfg.name
        try:
            return await asyncio.wait_for(coro, timeout or self.timeout)
        except asyncio.TimeoutError:
            raise ServiceError(f"Ingen kontakt med «{name}» (svarer ikke på {self.cfg.ip})", code="bulb_timeout")
        except (WizLightTimeOutError, WizLightConnectionError):
            raise ServiceError(f"Ingen kontakt med «{name}» ({self.cfg.ip})", code="bulb_unreachable")
        except OSError as exc:
            raise ServiceError(f"Nettverksfeil mot «{name}»: {exc}", code="bulb_network")

    async def _load_features(self, light) -> None:
        """Leser hva pæra kan (farge/hvitt, kelvin-område). Feiler det, bruker vi standardverdier."""
        try:
            bt = await self._call(light.get_bulbtype(), timeout=self.timeout * 3)
            kelvin = bt.kelvin_range
            self.state.features = BulbFeatures(
                color=bool(bt.features.color),
                colortemp=bool(bt.features.color_tmp),
                brightness=bool(bt.features.brightness),
                kelvin_min=int(kelvin.min) if kelvin else 2200,
                kelvin_max=int(kelvin.max) if kelvin else 6500,
            )
            log.info("Pære «%s»: %s (%s)", self.cfg.name, bt.name, self.state.features)
        except ServiceError:
            raise
        except Exception as exc:  # ukjent pæretype o.l. – ikke kritisk
            log.warning("Fikk ikke lest egenskaper for «%s» (%s), bruker standard", self.cfg.name, exc)
        self._features_loaded = True

    async def fetch(self) -> BulbState:
        light = self._light_or_raise()
        if not self._features_loaded:
            await self._load_features(light)

        result = await self._call(light.updateState())
        # Nyere pywizlight returnerer en liste (for lamper med to hoder), eldre ett objekt.
        parser = result[0] if isinstance(result, list) else result
        if parser is None:
            raise ServiceError(f"Pæra «{self.cfg.name}» ga ikke noe svar", code="bulb_no_state")

        pilot = parser.pilotResult  # rå-svaret fra pæra, f.eks. {"state": true, "dimming": 50, "temp": 2700}
        s = self.state
        s.on = bool(pilot.get("state", False))
        dimming = pilot.get("dimming")
        s.brightness = int(dimming) if dimming is not None else (100 if s.on else 0)
        s.scene_name = None

        scene_id = pilot.get("sceneId") or 0
        if scene_id:
            from pywizlight.bulb import SCENES
            s.mode = "scene"
            s.scene_name = SCENES.get(scene_id, f"Scene {scene_id}")
            s.rgb, s.colortemp = None, None
        elif "temp" in pilot:
            s.mode, s.colortemp, s.rgb = "white", int(pilot["temp"]), None
        elif all(k in pilot for k in ("r", "g", "b")):
            rgb = [int(pilot["r"]), int(pilot["g"]), int(pilot["b"])]
            if rgb == [0, 0, 0] and (pilot.get("c") or pilot.get("w")):
                s.mode, s.colortemp, s.rgb = "white", None, None  # bare hvit-LED
            else:
                s.mode, s.rgb, s.colortemp = "color", rgb, None
        return s

    async def apply(self, cmd: LightCommand) -> None:
        from pywizlight import PilotBuilder

        light = self._light_or_raise()
        if cmd.on is False or cmd.brightness == 0:
            await self._call(light.turn_off())
            return

        kwargs = {}
        if cmd.brightness is not None:
            # pywizlight vil ha 0–255; WiZ dimmer uansett ikke under 10 %
            kwargs["brightness"] = round(max(10, cmd.brightness) * 255 / 100)
        if cmd.rgb is not None:
            kwargs["rgb"] = tuple(cmd.rgb)
        elif cmd.colortemp is not None:
            f = self.state.features
            kwargs["colortemp"] = min(f.kelvin_max, max(f.kelvin_min, cmd.colortemp))
        await self._call(light.turn_on(PilotBuilder(**kwargs)))

    async def set_ip(self, ip: str) -> None:
        await self.close()
        self.cfg.ip = ip

    async def close(self) -> None:
        if self._light is not None:
            try:
                await self._light.async_close()
            except Exception:  # pragma: no cover
                pass
            self._light = None


# ---------------------------------------------------------------------------
# Tjenesten som holder alle pærene
# ---------------------------------------------------------------------------

class LightService:
    def __init__(self, cfg: LightsConfig, scenes: "SceneStore"):
        self.cfg = cfg
        self.scenes = scenes
        self.bulbs: dict[str, BulbDriver] = {}
        for b in cfg.bulbs:
            self.bulbs[b.id] = SimBulb(b) if cfg.simulate else WizBulb(b, cfg.timeout_seconds)
        self._locks = {bid: asyncio.Lock() for bid in self.bulbs}
        self._failures: dict[str, int] = {bid: 0 for bid in self.bulbs}
        self._task: asyncio.Task | None = None
        self._last_discovery = 0.0
        if cfg.simulate:
            log.info("Lys: simuleringsmodus med %d falske pærer", len(self.bulbs))
        elif not self.bulbs:
            log.warning("Lys: ingen pærer i config.yaml")

    # --- livssyklus ---------------------------------------------------------

    async def start(self) -> None:
        """Starter bakgrunnsjobben som spør pærene om status med jevne mellomrom."""
        if not self.cfg.simulate and any(b.cfg.mac and not b.cfg.ip for b in self.bulbs.values()):
            await self._rediscover()
        await self.refresh_all()  # så første visning har ekte tilstand
        self._task = asyncio.create_task(self._poll_loop(), name="lights-poll")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        for bulb in self.bulbs.values():
            await bulb.close()

    async def _poll_loop(self) -> None:
        while True:
            await asyncio.sleep(self.cfg.poll_interval_seconds)
            try:
                await self.refresh_all()
            except Exception:  # skal aldri skje, men løkka må overleve uansett
                log.exception("Uventet feil ved statussjekk av pærer")

    # --- lesing --------------------------------------------------------------

    def states(self) -> list[BulbState]:
        return [b.state for b in self.bulbs.values()]

    async def refresh_all(self) -> list[BulbState]:
        await asyncio.gather(*(self._refresh(b) for b in self.bulbs.values()))
        return self.states()

    async def _refresh(self, bulb: BulbDriver) -> BulbState:
        try:
            await bulb.fetch()
            bulb.state.reachable = True
            bulb.state.error = None
            self._failures[bulb.cfg.id] = 0
        except ServiceError as exc:
            self._mark_unreachable(bulb, exc.message)
        except Exception as exc:
            log.exception("Uventet feil mot pære «%s»", bulb.cfg.name)
            self._mark_unreachable(bulb, f"Uventet feil mot «{bulb.cfg.name}»: {exc}")
        bulb.state.updated_at = time.time()
        return bulb.state

    def _mark_unreachable(self, bulb: BulbDriver, message: str) -> None:
        if bulb.state.reachable:
            log.warning("%s", message)
        bulb.state.reachable = False
        bulb.state.error = message
        self._failures[bulb.cfg.id] += 1
        if bulb.cfg.mac and self._failures[bulb.cfg.id] >= REDISCOVER_AFTER_FAILURES:
            asyncio.create_task(self._maybe_rediscover())

    # --- styring -------------------------------------------------------------

    def _get(self, bulb_id: str) -> BulbDriver:
        try:
            return self.bulbs[bulb_id]
        except KeyError:
            raise ServiceError(f"Fant ikke pæra «{bulb_id}»", code="bulb_not_found", status=404)

    async def set_bulb(self, bulb_id: str, cmd: LightCommand) -> BulbState:
        """Utfører en kommando på én pære og returnerer ny tilstand."""
        bulb = self._get(bulb_id)
        async with self._locks[bulb_id]:
            try:
                await bulb.apply(cmd)
            except ServiceError as exc:    # pæra svarte ikke – merk den og si fra til den som spurte
                self._mark_unreachable(bulb, exc.message)
                raise
            await asyncio.sleep(0.15)      # pærene trenger et lite øyeblikk før de rapporterer ny tilstand
            return await self._refresh(bulb)

    async def set_all(self, cmd: LightCommand) -> list[BulbState]:
        """Samme kommando til alle pærer. Feiler bare hvis ingen pærer lot seg styre."""
        results = await asyncio.gather(
            *(self.set_bulb(bid, cmd) for bid in self.bulbs), return_exceptions=True)
        failures = [r for r in results if isinstance(r, Exception)]
        if failures and len(failures) == len(results):
            first = failures[0]
            msg = first.message if isinstance(first, ServiceError) else str(first)
            raise ServiceError(f"Ingen av pærene svarte. {msg}", code="all_unreachable")
        return self.states()

    async def toggle_bulb(self, bulb_id: str) -> BulbState:
        bulb = self._get(bulb_id)
        return await self.set_bulb(bulb_id, LightCommand(on=not bulb.state.on))

    async def toggle_all(self) -> list[BulbState]:
        """Er noen pærer på, skrus alle av. Ellers skrus alle på."""
        any_on = any(b.state.reachable and b.state.on for b in self.bulbs.values())
        return await self.set_all(LightCommand(on=not any_on))

    async def apply_scene(self, scene: "Scene") -> list[BulbState]:
        commands = scene.commands_for(list(self.bulbs))
        if not commands:
            raise ServiceError(f"Scenen «{scene.name}» har ingen pærer å styre", code="scene_empty", status=400)
        results = await asyncio.gather(
            *(self.set_bulb(bid, cmd) for bid, cmd in commands.items()), return_exceptions=True)
        failures = [r for r in results if isinstance(r, Exception)]
        if failures and len(failures) == len(results):
            first = failures[0]
            msg = first.message if isinstance(first, ServiceError) else str(first)
            raise ServiceError(f"Ingen av pærene svarte. {msg}", code="all_unreachable")
        return self.states()

    async def activate_scene(self, scene_id: str) -> list[BulbState]:
        return await self.apply_scene(self.scenes.get(scene_id))

    def capture_scene(self, scene_id: str) -> "Scene":
        """Lager en ny versjon av scenen ut fra slik pærene står nå, og lagrer den."""
        from app.services.scenes import SceneState

        scene = self.scenes.get(scene_id)
        bulbs = {}
        for b in self.bulbs.values():
            s = b.state
            if not s.reachable:
                continue  # ukjent tilstand – la scenen beholde det den hadde for denne pæra
            if not s.on:
                bulbs[s.id] = SceneState(on=False)
            elif s.mode == "color" and s.rgb:
                bulbs[s.id] = SceneState(on=True, brightness=s.brightness, rgb=list(s.rgb))
            else:
                bulbs[s.id] = SceneState(on=True, brightness=s.brightness, colortemp=s.colortemp)
        updated = scene.model_copy(update={"bulbs": {**scene.bulbs, **bulbs}})
        self.scenes.upsert(updated)
        return updated

    # --- finne pærer igjen når IP endrer seg ----------------------------------

    async def _maybe_rediscover(self) -> None:
        if time.time() - self._last_discovery >= REDISCOVER_INTERVAL:
            await self._rediscover()

    async def _rediscover(self) -> None:
        """Søker etter WiZ-pærer på nettet og oppdaterer IP for pærer med kjent MAC."""
        self._last_discovery = time.time()
        try:
            from pywizlight import discovery
            found = await discovery.discover_lights(broadcast_space=self.cfg.broadcast_address, wait_time=3)
        except Exception as exc:
            log.warning("Søk etter pærer feilet: %s", exc)
            return
        by_mac = {}
        for f in found:
            if f.mac:
                by_mac[_norm_mac(f.mac)] = f.ip
            try:
                await f.async_close()
            except Exception:
                pass
        log.info("Søk etter pærer fant %d stk", len(found))
        for bulb in self.bulbs.values():
            mac = _norm_mac(bulb.cfg.mac)
            if mac and mac in by_mac and by_mac[mac] != bulb.cfg.ip:
                log.info("Pære «%s» har fått ny IP: %s → %s", bulb.cfg.name, bulb.cfg.ip, by_mac[mac])
                await bulb.set_ip(by_mac[mac])


def _norm_mac(mac: str | None) -> str:
    return (mac or "").lower().replace(":", "").replace("-", "").strip()
