"""Tester tolkningen av MET-svar og mellomlagringen i WeatherService."""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.config import WeatherConfig
from app.errors import ServiceError
from app.services.weather import WeatherService, describe_symbol, parse_forecast, wind_direction_text, wind_text
from tests.met_sample import make_sample

START = datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc)   # lørdag
NOW = START + timedelta(hours=2, minutes=20)                  # 12:20 UTC = 14:20 i Oslo


def test_describe_symbol():
    assert describe_symbol("clearsky_day") == ("sun", "Klarvær")
    assert describe_symbol("clearsky_night") == ("moon", "Klarvær")
    assert describe_symbol("heavyrainshowersandthunder_day")[0] == "thunder"
    assert describe_symbol("lightsnowshowers_polartwilight") == ("snow", "Lette snøbyger")
    assert describe_symbol(None) == ("cloud", "")


def test_wind_helpers():
    assert wind_direction_text(0) == "N" and wind_direction_text(225) == "SV" and wind_direction_text(350) == "N"
    assert wind_text(0.1) == "Stille" and wind_text(6) == "Laber bris" and wind_text(40) == "Orkan"


def test_parse_now_hours_and_days():
    data = parse_forecast(make_sample(START), WeatherConfig(place_name="Test", hours=6, days=3), NOW)
    assert data.place == "Test"
    # "nå" er oppføringen for kl 12 UTC (siste som ikke er fram i tid)
    assert data.now.time.startswith("2026-09-19T12:00")
    assert data.now.icon in ("sun", "partly_day", "cloud", "rain", "partly_night")
    assert data.now.wind_dir_text and data.now.wind_text
    # timene starter etter "nå"
    assert len(data.hours) == 6
    assert data.hours[0].time.startswith("2026-09-19T13:00")
    # tre dager fra i morgen, med norske etiketter
    assert [d.label for d in data.days] == ["I morgen", "Man", "Tir"]
    for day in data.days:
        assert day.tmax >= day.tmin and day.precip >= 0 and day.icon


def test_parse_before_first_entry_uses_first():
    data = parse_forecast(make_sample(START), WeatherConfig(), START - timedelta(hours=3))
    assert data.now.time.startswith("2026-09-19T10:00")


def make_service(handler, now=None, **cfg):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return WeatherService(WeatherConfig(**cfg), client, now=now or (lambda: NOW))


async def test_service_caches_and_sends_user_agent():
    calls = 0

    def handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        assert request.headers["User-Agent"] == "test/1.0 (test@test.no)"
        assert request.url.params["lat"] == "59.9139"
        return httpx.Response(200, json=make_sample(START),
                              headers={"Expires": "Sat, 19 Sep 2026 13:00:00 GMT", "Last-Modified": "Sat, 19 Sep 2026 11:30:00 GMT"})

    svc = make_service(handler, user_agent="test/1.0 (test@test.no)")
    a = await svc.get()
    b = await svc.get()
    assert calls == 1 and a.now.temp == b.now.temp


async def test_service_keeps_old_forecast_with_warning_on_failure():
    state = {"fail": False}

    def handler(request):
        if state["fail"]:
            raise httpx.ConnectError("down")
        return httpx.Response(200, json=make_sample(START))

    svc = make_service(handler, refresh_seconds=0)
    first = await svc.get()
    assert first.warning is None
    state["fail"] = True
    second = await svc.get()
    assert second.warning and "MET" in second.warning
    assert second.now.temp == first.now.temp


async def test_first_failure_is_an_error():
    svc = make_service(lambda r: httpx.Response(403))
    with pytest.raises(ServiceError) as exc:
        await svc.get()
    assert "user_agent" in exc.value.message
