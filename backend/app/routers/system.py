"""Små hjelpe-endepunkter: helse-sjekk og konfigurasjon til frontend."""
from fastapi import APIRouter, Request

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict:
    """Brukes av kiosk-skriptet på Pi-en for å vente til backend er oppe."""
    return {"status": "ok"}


@router.get("/config")
async def frontend_config(request: Request) -> dict:
    """Den delen av konfigurasjonen frontend trenger (aldri hemmeligheter)."""
    cfg = request.app.state.config
    return {
        "title": cfg.dashboard.title,
        "layout": cfg.dashboard.layout,
        "lights": {"poll_interval_seconds": cfg.lights.poll_interval_seconds,
                   "simulate": cfg.lights.simulate},
        "bus": {"enabled": cfg.bus.enabled, "refresh_seconds": cfg.bus.refresh_seconds},
        "weather": {"enabled": cfg.weather.enabled,
                    "refresh_seconds": cfg.weather.refresh_seconds,
                    "place_name": cfg.weather.place_name},
    }
