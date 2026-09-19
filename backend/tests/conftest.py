"""Felles oppsett for testene: en app i simuleringsmodus med egen scenes-fil."""
import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig, BulbConfig, LightsConfig
from app.main import create_app


@pytest.fixture
def config(tmp_path) -> AppConfig:
    return AppConfig(
        lights=LightsConfig(
            simulate=True,
            poll_interval_seconds=60,
            scenes_file=str(tmp_path / "scenes.json"),
            bulbs=[
                BulbConfig(id="stue", name="Stue"),
                BulbConfig(id="kjokken", name="Kjøkken"),
                BulbConfig(id="borte", name="Borte", ip="unreachable"),
            ],
        ),
    )


@pytest.fixture
def client(config):
    # `with` sørger for at lifespan kjører (tjenestene startes og stoppes)
    with TestClient(create_app(config)) as c:
        yield c
