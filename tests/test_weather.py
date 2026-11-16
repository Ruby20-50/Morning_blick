"""Open-Meteo provider tests. All HTTP goes through httpx2.MockTransport."""

import logging
import time

import httpx2
import pytest

from app.config import Settings
from app.services import briefing, weather
from tests.conftest import load_fixture, mock_client

SETTINGS = Settings()


def forecast_handler(payload, calls: list | None = None, status: int = 200):
    def handler(request: httpx2.Request) -> httpx2.Response:
        if calls is not None:
            calls.append(request)
        return httpx2.Response(status, json=payload)

    return handler


def test_happy_path_lines_and_query_parameters():
    calls: list[httpx2.Request] = []
    client = mock_client(forecast_handler(load_fixture("open_meteo_forecast.json"), calls))

    section = weather.get_weather_section(client, SETTINGS)

    assert section.status == "ok"
    assert section.items == ["8 °C, Overcast", "Today 3–9 °C · rain chance 40 %"]
    (request,) = calls
    assert str(request.url).startswith("https://api.open-meteo.com/v1/forecast?")
    params = request.url.params
    assert params["latitude"] == "52.52"
    assert params["longitude"] == "13.41"
    assert params["current"] == "temperature_2m,weather_code"
    assert params["daily"] == "temperature_2m_max,temperature_2m_min,precipitation_probability_max"
    assert params["timezone"] == "Europe/Berlin"
    assert params["forecast_days"] == "1"
    # URL-encoded on the wire.
    assert "timezone=Europe%2FBerlin" in str(request.url)


def test_nulls_and_unknown_fields_are_tolerated():
    client = mock_client(forecast_handler(load_fixture("open_meteo_nulls.json")))
    section = weather.get_weather_section(client, SETTINGS)
    # No condition text (null code), no min/max (one side null), no rain chance (null array).
    assert section.items == ["8 °C"]


@pytest.mark.parametrize(
    "payload",
    [{}, {"current": None, "daily": None}, {"daily": {"temperature_2m_max": [], "temperature_2m_min": []}}],
)
def test_no_usable_values_gives_empty(payload):
    section = weather.get_weather_section(mock_client(forecast_handler(payload)), SETTINGS)
    assert section.status == "empty"
    assert section.items == []


def test_unknown_weather_code_shows_temperature_only():
    payload = {"current": {"temperature_2m": -2.4, "weather_code": 12345}}
    section = weather.get_weather_section(mock_client(forecast_handler(payload)), SETTINGS)
    assert section.items == ["-2 °C"]


@pytest.mark.parametrize(
    "handler",
    [
        lambda request: httpx2.Response(200, text="<html>not json</html>"),
        lambda request: httpx2.Response(200, json=[1, 2, 3]),
        lambda request: httpx2.Response(200, json={"current": {"temperature_2m": "warm"}}),
        lambda request: httpx2.Response(400, json={"error": True, "reason": "Invalid timezone"}),
        lambda request: httpx2.Response(503),
    ],
    ids=["not-json", "not-an-object", "wrong-type", "http-400", "http-503"],
)
def test_malformed_or_error_responses_make_section_unavailable(handler):
    result = briefing.build_briefing(SETTINGS, client=mock_client(handler))
    assert result.weather.status == "unavailable"


def test_timeout_makes_section_unavailable_and_logs_without_details(caplog):
    def handler(request):
        raise httpx2.ReadTimeout("timed out reading https://api.open-meteo.com/v1/forecast?latitude=52.52", request=request)

    with caplog.at_level(logging.WARNING, logger="app.services.briefing"):
        result = briefing.build_briefing(SETTINGS, client=mock_client(handler))

    assert result.weather.status == "unavailable"
    assert "briefing provider weather failed: ReadTimeout" in caplog.text
    assert "52.52" not in caplog.text
    assert "open-meteo" not in caplog.text
    # The rest of the page is unaffected.
    assert result.date.label


def test_provider_deadline_overrun_is_unavailable_and_does_not_block():
    def slow(request):
        time.sleep(1.0)
        return httpx2.Response(200, json=load_fixture("open_meteo_forecast.json"))

    started = time.monotonic()
    result = briefing.build_briefing(Settings(provider_timeout=0.1), client=mock_client(slow))
    assert result.weather.status == "unavailable"
    assert time.monotonic() - started < 0.8


def test_cache_hit_avoids_second_request():
    calls: list = []
    client = mock_client(forecast_handler(load_fixture("open_meteo_forecast.json"), calls))
    first = weather.get_weather_section(client, SETTINGS)
    second = weather.get_weather_section(client, SETTINGS)
    assert first == second
    assert len(calls) == 1


def test_cache_expires_after_ttl(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(weather._cache, "clock", lambda: now[0])
    calls: list = []
    client = mock_client(forecast_handler(load_fixture("open_meteo_forecast.json"), calls))

    weather.get_weather_section(client, SETTINGS)
    now[0] += SETTINGS.cache_ttl_weather - 1
    weather.get_weather_section(client, SETTINGS)
    assert len(calls) == 1
    now[0] += 2
    weather.get_weather_section(client, SETTINGS)
    assert len(calls) == 2


def test_failures_are_not_cached():
    responses = iter([httpx2.Response(503), httpx2.Response(200, json=load_fixture("open_meteo_forecast.json"))])

    def handler(request):
        # build_briefing also calls the other providers; only Open-Meteo answers.
        if request.url.host != "api.open-meteo.com":
            return httpx2.Response(404)
        return next(responses)

    client = mock_client(handler)
    assert briefing.build_briefing(SETTINGS, client=client).weather.status == "unavailable"
    assert briefing.build_briefing(SETTINGS, client=client).weather.status == "ok"


def test_cache_can_be_disabled(monkeypatch):
    monkeypatch.setattr(weather._cache, "enabled", False)
    calls: list = []
    client = mock_client(forecast_handler(load_fixture("open_meteo_forecast.json"), calls))
    weather.get_weather_section(client, SETTINGS)
    weather.get_weather_section(client, SETTINGS)
    assert len(calls) == 2


def test_page_shows_weather_and_attribution(monkeypatch):
    from fastapi.testclient import TestClient

    from app.api import routes
    from app.main import app

    client = mock_client(forecast_handler(load_fixture("open_meteo_forecast.json")))
    monkeypatch.setattr(routes, "build_briefing", lambda settings, **kwargs: briefing.build_briefing(settings, client=client))
    html = TestClient(app).get("/").text
    assert "<li>8 °C, Overcast</li>" in html
    assert '<a href="https://open-meteo.com/" rel="noopener noreferrer" target="_blank">Weather data by Open-Meteo.com</a>' in html
    assert "creativecommons.org/licenses/by/4.0/" in html
