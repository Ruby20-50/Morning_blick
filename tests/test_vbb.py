"""VBB provider tests. All HTTP goes through httpx2.MockTransport."""

import logging

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.config import Settings
from app.main import app
from app.schemas.vbb import Departure, Line
from app.services import briefing, vbb
from tests.conftest import load_fixture, mock_client

SETTINGS = Settings()
DEPARTURES = load_fixture("vbb_departures.json")


def vbb_handler(payload=DEPARTURES, calls: list | None = None, status: int = 200):
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.host != "v6.vbb.transport.rest":
            return httpx2.Response(404)  # other providers in build_briefing
        if calls is not None:
            calls.append(request)
        return httpx2.Response(status, json=payload)

    return handler


def test_happy_path_shows_only_delays_and_cancellations():
    calls: list[httpx2.Request] = []
    section = vbb.get_transport_section(mock_client(vbb_handler(calls=calls)), SETTINGS)

    assert section.status == "ok"
    assert section.items == [
        # S5 had 0, 4 and 6 min delays -> one line with the largest; S7 (+1 min) and M5 (null) are not shown.
        "S5 → S Spandau Bhf (Berlin): +6 min",
        "U2 → S+U Pankow (Berlin): cancelled",
    ]
    (request,) = calls
    assert request.url.path == "/stops/900100003/departures"
    assert request.url.params["duration"] == "30"
    assert request.url.params["remarks"] == "false"


def test_stop_id_and_query_parameters_are_url_encoded():
    calls: list[httpx2.Request] = []
    settings = Settings(vbb_stop_id="de:11000:900100003 /x?y", vbb_duration_minutes=15)
    vbb.get_departures(mock_client(vbb_handler(calls=calls)), settings)
    raw = calls[0].url.raw_path.decode()
    assert raw.startswith("/stops/de%3A11000%3A900100003%20%2Fx%3Fy/departures?")
    assert "duration=15" in raw


def test_malformed_departures_are_skipped_and_counted(caplog):
    with caplog.at_level(logging.WARNING):
        departures = vbb.get_departures(mock_client(vbb_handler()), SETTINGS)
    assert len(departures) == 6  # 8 entries minus the null and the one with a text delay
    assert "vbb: skipped 2 malformed departures of 8" in caplog.text


def test_threshold_and_grouping():
    s1 = Line(name="S1")
    departures = [
        Departure(line=s1, direction="Oranienburg", delay=179),  # just under 3 min
        Departure(line=s1, direction="Oranienburg", delay=180),
        Departure(line=s1, direction="Wannsee", cancelled=True),
        Departure(line=s1, direction="Wannsee", cancelled=True),
        Departure(line=s1, direction="Wannsee", delay=-120),  # early, not noteworthy
        Departure(line=None, direction=None, delay=600),
    ]
    assert vbb.noteworthy(departures, 3) == [
        "?: +10 min",
        "S1 → Oranienburg: +3 min",
        "S1 → Wannsee: 2 departures cancelled",
    ]


def test_no_noteworthy_departures_renders_no_disruptions(monkeypatch):
    calm = {"departures": [{"line": {"name": "U8"}, "direction": "Wittenau", "delay": 0}]}
    section = vbb.get_transport_section(mock_client(vbb_handler(calm)), SETTINGS)
    assert section.status == "empty"

    client = mock_client(vbb_handler(calm))
    monkeypatch.setattr(routes, "build_briefing", lambda settings, **kwargs: briefing.build_briefing(settings, client=client))
    html = TestClient(app).get("/").text
    assert "No disruptions" in html


def test_timeout_makes_section_unavailable(caplog):
    def handler(request):
        raise httpx2.ConnectTimeout("timed out", request=request)

    with caplog.at_level(logging.WARNING):
        result = briefing.build_briefing(SETTINGS, client=mock_client(handler))
    assert result.transport.status == "unavailable"
    assert "briefing provider transport failed: ConnectTimeout" in caplog.text


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        ([], 200),  # bare array instead of {departures: [...]}
        ({"realtimeDataUpdatedAt": 1}, 200),  # no departures key
        ({"departures": None}, 200),
        ({"error": True, "msg": "rate limit"}, 429),
        ({"error": True, "msg": "stop not found"}, 404),
    ],
    ids=["array", "missing-key", "null-list", "http-429", "http-404"],
)
def test_malformed_or_error_responses_are_unavailable(payload, status):
    result = briefing.build_briefing(SETTINGS, client=mock_client(vbb_handler(payload, status=status)))
    assert result.transport.status == "unavailable"


def test_cache_hit_avoids_second_request():
    calls: list = []
    client = mock_client(vbb_handler(calls=calls))
    first = vbb.get_departures(client, SETTINGS)
    second = vbb.get_departures(client, SETTINGS)
    assert first == second
    assert len(calls) == 1


def test_cache_is_per_stop_and_expires(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(vbb._cache, "clock", lambda: now[0])
    calls: list = []
    client = mock_client(vbb_handler(calls=calls))
    vbb.get_departures(client, SETTINGS)
    vbb.get_departures(client, SETTINGS, stop_id="900120003")
    assert len(calls) == 2
    now[0] += SETTINGS.cache_ttl_vbb
    vbb.get_departures(client, SETTINGS)
    assert len(calls) == 3


def test_cache_keeps_requests_under_rate_limit():
    calls: list = []
    client = mock_client(vbb_handler(calls=calls))
    for _ in range(150):  # e.g. 150 page loads within one minute
        vbb.get_transport_section(client, SETTINGS)
    assert len(calls) == 1
