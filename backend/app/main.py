"""Setter opp FastAPI-appen: konfigurasjon, tjenester, API-ruter og frontend.

Oppstart:  cd backend && python -m app
API:       http://localhost:8000/api/...
Frontend:  http://localhost:8000/
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app.config import FRONTEND_DIR, AppConfig, load_config
from app.errors import install_error_handlers
from app.routers import system

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


def create_app(config: AppConfig) -> FastAPI:
    """Lager appen ut fra en konfigurasjon. Brukes både ved vanlig oppstart og i tester."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Alt som skal startes/stoppes sammen med serveren settes opp her.
        log.info("Hjemmepanel starter")
        yield
        log.info("Hjemmepanel stopper")

    app = FastAPI(title="Hjemmepanel", lifespan=lifespan)
    app.state.config = config
    install_error_handlers(app)

    # API-ruter (alle under /api)
    app.include_router(system.router, prefix="/api")

    # Frontend: statiske filer fra frontend/-mappa. html=True gjør at "/" gir index.html.
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

    @app.middleware("http")
    async def no_cache_for_static(request: Request, call_next):
        # Kiosk-nettleseren skal alltid få ferske filer etter en oppdatering,
        # så vi ber den om å ikke cache frontend-filene.
        response = await call_next(request)
        if not request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    return app


app = create_app(load_config())
