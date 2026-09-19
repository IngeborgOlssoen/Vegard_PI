"""Leser config/config.yaml og validerer innholdet.

Alt som er verdt å endre (pærer, holdeplass, sted, layout, knapper) ligger i
config/config.yaml. Denne fila beskriver hvilke felter som finnes og hva
standardverdiene er. Pydantic gir tydelige feilmeldinger hvis noe er feil.

Miljøvariabler:
  HJEMMEPANEL_CONFIG   – sti til en annen config-fil (valgfritt)
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

log = logging.getLogger(__name__)

# Repo-roten (mappa som inneholder backend/, frontend/, config/).
ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "config"
FRONTEND_DIR = ROOT_DIR / "frontend"


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"  # 0.0.0.0 = tilgjengelig fra andre maskiner på nettet
    port: int = 8000


class DashboardConfig(BaseModel):
    title: str = "Hjemmepanel"
    # Layouten er en liten "tegning" av skjermen, rad for rad. Hvert ord er
    # id-en til et kort, og et kort kan dekke flere celler ved å gjentas.
    layout: list[str] = ["lights lights bus", "lights lights weather"]


class BulbConfig(BaseModel):
    id: str  # kort id uten mellomrom, brukes i URL-er og scener
    name: str  # navnet som vises på skjermen
    ip: str | None = None
    mac: str | None = None  # brukes til å finne pæra igjen hvis IP-en endrer seg


class LightsConfig(BaseModel):
    simulate: bool = False  # true = falske pærer i minnet (for utvikling på PC)
    timeout_seconds: float = 3.0  # hvor lenge vi venter på svar fra en pære
    poll_interval_seconds: float = 10.0  # hvor ofte vi spør pærene om status
    broadcast_address: str = "255.255.255.255"  # brukes ved søk etter pærer
    scenes_file: str = "config/scenes.json"  # relativt til repo-roten
    bulbs: list[BulbConfig] = Field(default_factory=list)


class BusConfig(BaseModel):
    enabled: bool = True
    stop_place_id: str = "NSR:StopPlace:58366"  # Jernbanetorget – bytt til din
    stop_name: str | None = None  # overstyr navnet som vises (ellers fra Entur)
    client_name: str = "privat-hjemmepanel"  # Entur krever en identifikator
    number_of_departures: int = 10
    time_range_seconds: int = 2 * 60 * 60  # hvor langt fram vi henter avganger
    refresh_seconds: int = 30
    line_filter: list[str] = Field(default_factory=list)  # tom = alle linjer
    timeout_seconds: float = 8.0


class WeatherConfig(BaseModel):
    enabled: bool = True
    place_name: str = "Oslo"
    lat: float = 59.9139
    lon: float = 10.7522
    # MET krever en User-Agent som identifiserer appen, med e-post eller URL.
    user_agent: str = "hjemmepanel/1.0 (bytt-meg@example.com)"
    refresh_seconds: int = 600
    hours: int = 6  # antall timer i timesvarselet
    days: int = 3  # antall dager i dagsvarselet
    timeout_seconds: float = 10.0


class ButtonConfig(BaseModel):
    gpio: int  # BCM-nummer (f.eks. 17 = fysisk pinne 11)
    action: Literal["scene", "toggle_all", "all_on", "all_off", "toggle_bulb"]
    scene: str | None = None  # scene-id når action = scene
    bulb: str | None = None  # pære-id når action = toggle_bulb

    @model_validator(mode="after")
    def _check_target(self):
        if self.action == "scene" and not self.scene:
            raise ValueError(f"Knapp på GPIO {self.gpio}: action=scene trenger 'scene: <id>'")
        if self.action == "toggle_bulb" and not self.bulb:
            raise ValueError(f"Knapp på GPIO {self.gpio}: action=toggle_bulb trenger 'bulb: <id>'")
        return self


class ButtonsConfig(BaseModel):
    enabled: bool = False
    buttons: list[ButtonConfig] = Field(default_factory=list)


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    lights: LightsConfig = Field(default_factory=LightsConfig)
    bus: BusConfig = Field(default_factory=BusConfig)
    weather: WeatherConfig = Field(default_factory=WeatherConfig)
    buttons: ButtonsConfig = Field(default_factory=ButtonsConfig)

    def resolve(self, relative_path: str) -> Path:
        """Gjør en sti fra config om til en absolutt sti (relativt til repo-roten)."""
        p = Path(relative_path)
        return p if p.is_absolute() else ROOT_DIR / p


def config_path() -> Path:
    """Finner config-fila: miljøvariabel, ellers config/config.yaml,
    ellers config/config.example.yaml (så appen starter selv uten oppsett)."""
    env = os.environ.get("HJEMMEPANEL_CONFIG")
    if env:
        return Path(env)
    real = CONFIG_DIR / "config.yaml"
    if real.exists():
        return real
    log.warning("Fant ikke config/config.yaml – bruker config.example.yaml. "
                "Kopier example-fila til config.yaml og tilpass den.")
    return CONFIG_DIR / "config.example.yaml"


def load_config(path: Path | None = None) -> AppConfig:
    path = path or config_path()
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    config = AppConfig.model_validate(data)
    log.info("Leste konfigurasjon fra %s", path)
    return config
