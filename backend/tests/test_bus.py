"""Tester tolkningen av Entur-svar og feilhåndteringen i BusService."""
from datetime import datetime, timezone

import httpx
import pytest

from app.config import BusConfig, BusStopConfig
from app.errors import ServiceError
from app.services.bus import BusService, parse_departures, parse_iso

NOW = datetime(2026, 9, 19, 14, 0, tzinfo=timezone.utc)


def call(line, dest, minutes, realtime=True, cancelled=False, mode="bus", platform="A"):
    t = NOW.timestamp() + minutes * 60
    # Entur skriver tidssonen uten kolon, f.eks. +0200 – vi etterligner det
    iso = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")
    return {
        "realtime": realtime, "cancellation": cancelled,
        "aimedDepartureTime": iso, "expectedDepartureTime": iso,
        "destinationDisplay": {"frontText": dest},
        "quay": {"publicCode": platform},
        "serviceJourney": {"line": {"publicCode": line, "transportMode": mode}},
    }


SAMPLE = {
    "id": "NSR:StopPlace:1", "name": "Testplassen",
    "estimatedCalls": [
        call("31", "Snarøya", 12),
        call("37", "Nydalen", 3, realtime=False),
        call("31", "Grorud", -2),          # allerede gått
        call("17", "Rikshospitalet", 0.5, mode="tram"),
        call("37", "Helsfyr", 25, cancelled=True),
    ],
}
STOP = BusStopConfig(stop_place_id="NSR:StopPlace:1")


def test_parse_iso_handles_entur_and_met_formats():
    assert parse_iso("2026-09-19T14:00:00+0200").isoformat() == "2026-09-19T14:00:00+02:00"
    assert parse_iso("2026-09-19T14:00:00+02:00").utcoffset().total_seconds() == 7200
    assert parse_iso("2026-09-19T12:00:00Z") == datetime(2026, 9, 19, 12, tzinfo=timezone.utc)


def test_parse_sorts_and_drops_departed():
    data = parse_departures(SAMPLE, STOP, NOW)
    assert data.stop_name == "Testplassen"
    assert [(d.line, d.minutes) for d in data.departures] == [("17", 0), ("37", 3), ("31", 12), ("37", 25)]
    assert data.departures[0].mode == "tram"
    assert data.departures[1].realtime is False
    assert data.departures[3].cancelled is True


def test_line_filter_and_name_override():
    stop = BusStopConfig(stop_place_id="NSR:StopPlace:1", line_filter=["31"], name="Hjemme")
    data = parse_departures(SAMPLE, stop, NOW)
    assert data.stop_name == "Hjemme"
    assert [d.line for d in data.departures] == ["31"]


def test_legacy_single_stop_config_still_works():
    cfg = BusConfig(stop_place_id="NSR:StopPlace:9", stop_name="Gamlemåten", line_filter=["1"])
    assert len(cfg.stops) == 1 and cfg.stops[0].name == "Gamlemåten" and cfg.stops[0].line_filter == ["1"]
    assert BusConfig().stops[0].stop_place_id == "NSR:StopPlace:58366"


def make_service(handler, **cfg):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return BusService(BusConfig(**cfg), client, now=lambda: NOW)


async def test_service_fetches_and_caches():
    calls = 0

    def handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        assert request.headers["ET-Client-Name"] == "privat-hjemmepanel"
        return httpx.Response(200, json={"data": {"stopPlace": SAMPLE}})

    svc = make_service(handler)
    first = await svc.get()
    second = await svc.get()
    assert calls == 1 and first is second
    assert len(first.stops) == 1 and len(first.stops[0].departures) == 4


async def test_multiple_stops_are_fetched_and_partial_failure_is_reported():
    def handler(request: httpx.Request):
        if b"NSR:StopPlace:2" in request.content:
            return httpx.Response(200, json={"data": {"stopPlace": None}})
        return httpx.Response(200, json={"data": {"stopPlace": SAMPLE}})

    svc = make_service(handler, stops=[{"stop_place_id": "NSR:StopPlace:1"},
                                       {"stop_place_id": "NSR:StopPlace:2", "name": "Borte"}])
    data = await svc.get()
    assert [s.stop_name for s in data.stops] == ["Testplassen", "Borte"]
    assert data.stops[0].error is None and len(data.stops[0].departures) == 4
    assert "Fant ikke holdeplassen" in data.stops[1].error and data.stops[1].departures == []


async def test_quay_id_uses_quay_query():
    def handler(request: httpx.Request):
        assert b"quay(id:" in request.content
        return httpx.Response(200, json={"data": {"quay": {**SAMPLE, "id": "NSR:Quay:9"}}})

    data = await make_service(handler, stop_place_id="NSR:Quay:9").get()
    assert data.stops[0].stop_id == "NSR:Quay:9"


async def test_unknown_stop_gives_helpful_error():
    svc = make_service(lambda r: httpx.Response(200, json={"data": {"stopPlace": None}}))
    with pytest.raises(ServiceError) as exc:
        await svc.get()
    assert "Fant ikke holdeplassen" in exc.value.message


async def test_network_errors_become_norwegian_messages():
    def timeout(_):
        raise httpx.ReadTimeout("slow")
    with pytest.raises(ServiceError) as exc:
        await make_service(timeout).get()
    assert "tidsavbrudd" in exc.value.message

    with pytest.raises(ServiceError) as exc:
        await make_service(lambda r: httpx.Response(502)).get()
    assert "HTTP 502" in exc.value.message

    with pytest.raises(ServiceError) as exc:
        await make_service(lambda r: httpx.Response(200, json={"errors": [{"message": "bad id"}]})).get()
    assert "bad id" in exc.value.message


async def test_disabled_gives_404():
    svc = make_service(lambda r: httpx.Response(200), enabled=False)
    with pytest.raises(ServiceError) as exc:
        await svc.get()
    assert exc.value.status == 404
