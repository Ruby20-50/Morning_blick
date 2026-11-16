"""Nylas calendar events for the schedule card. The SDK client is a MagicMock;
responses are decoded with the real SDK models from hand-written fixtures."""

import logging
import time
from datetime import date
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import httpx2
import pytest
from fastapi.testclient import TestClient
from nylas.models.calendars import Calendar
from nylas.models.errors import NylasSdkTimeoutError
from nylas.models.events import Event
from nylas.models.response import ListResponse

from app.api import routes
from app.config import Settings
from app.main import app
from app.schemas.briefing import ScheduleItem
from app.schemas.nylas_event_schema import CalendarObject
from app.services import briefing, nylas_service
from tests.conftest import load_fixture, mock_client

BERLIN = ZoneInfo("Europe/Berlin")
DAY = date(2026, 11, 16)
SETTINGS = Settings(nylas_api_key="test-key", http_timeout=5.0)
GRANT = "grant-test"

EXPECTED = [
    ScheduleItem(title="Sam's birthday", all_day=True),
    ScheduleItem(title="Conference", all_day=True),
    ScheduleItem(title="Night train", time="00:00"),  # started yesterday 23:00
    ScheduleItem(title="Lecture: Distributed Systems", time="09:00"),
    ScheduleItem(title="Call the dentist", time="12:00"),
    ScheduleItem(title="Team sync", time="14:30"),
]


def sdk_list(fixture: str, model) -> ListResponse:
    return ListResponse.from_dict(load_fixture(fixture), model)


class Raw:
    """Stand-in for an SDK object whose data the SDK itself would not decode."""

    def __init__(self, data):
        self.data = data

    def to_dict(self):
        return dict(self.data)


@pytest.fixture
def fake_client(monkeypatch):
    fake = MagicMock()
    fake.calendars.list.return_value = sdk_list("nylas_calendars.json", Calendar)
    fake.events.list.return_value = sdk_list("nylas_events.json", Event)
    monkeypatch.setattr(nylas_service, "get_nylas_client", lambda: fake)
    monkeypatch.setattr(nylas_service, "today", lambda tz: DAY)
    return fake


def test_happy_path_primary_calendar_today_sorted(fake_client):
    section = nylas_service.get_schedule_section(GRANT, SETTINGS)

    assert section.status == "ok"
    assert section.items == EXPECTED
    fake_client.calendars.list.assert_called_once_with(GRANT, query_params=None, overrides={"timeout": 5.0})
    _, kwargs = fake_client.events.list.call_args
    assert fake_client.events.list.call_args.args == (GRANT,)
    # Primary calendar is picked from the list, not hardcoded; bounds are Berlin midnight to midnight.
    assert kwargs["query_params"] == {"calendar_id": "cal-primary", "start": 1794783600, "end": 1794870000}
    assert kwargs["overrides"] == {"timeout": 5.0}


def test_day_bounds_are_berlin_midnights_and_dst_safe():
    assert nylas_service.day_bounds(DAY, BERLIN) == (1794783600, 1794870000)
    start, end = nylas_service.day_bounds(date(2026, 3, 29), BERLIN)  # clocks go forward: 23 h
    assert end - start == 23 * 3600
    start, end = nylas_service.day_bounds(date(2026, 10, 25), BERLIN)  # clocks go back: 25 h
    assert end - start == 25 * 3600


@pytest.mark.parametrize(
    ("calendars", "expected"),
    [
        ([{"id": "a", "is_primary": False}, {"id": "b", "is_primary": True}], "b"),
        ([{"id": "a", "is_owned_by_user": False}, {"id": "b", "is_owned_by_user": True}], "b"),
        ([{"id": "a"}, {"id": "b"}], "a"),
        ([], None),
    ],
    ids=["is_primary", "owned-fallback", "first-fallback", "none"],
)
def test_pick_primary_calendar(calendars, expected):
    picked = nylas_service.pick_primary_calendar([CalendarObject(**c) for c in calendars])
    assert (picked.id if picked else None) == expected


def test_pagination_follows_next_cursor(fake_client):
    events = load_fixture("nylas_events.json")["data"]
    fake_client.events.list.side_effect = [
        ListResponse(data=[Raw(e) for e in events[:4]], request_id="r1", next_cursor="page-2"),
        ListResponse(data=[Raw(e) for e in events[4:]], request_id="r2", next_cursor=None),
    ]
    section = nylas_service.get_schedule_section(GRANT, SETTINGS)
    assert section.items == EXPECTED
    second_call = fake_client.events.list.call_args_list[1]
    assert second_call.kwargs["query_params"]["page_token"] == "page-2"


def test_timeout_makes_section_unavailable_without_logging_details(fake_client, caplog):
    fake_client.events.list.side_effect = NylasSdkTimeoutError(url="https://api.us.nylas.com/v3/grants/grant-test/events", timeout=5)
    with caplog.at_level(logging.DEBUG):
        result = briefing.build_briefing(SETTINGS, client=mock_client(lambda r: httpx2.Response(404)), grant_id=GRANT)
    assert result.schedule.status == "unavailable"
    assert "briefing provider schedule failed: NylasSdkTimeoutError" in caplog.text
    assert "grant-test" not in caplog.text


@pytest.mark.parametrize(
    "settings, grant",
    [(Settings(nylas_api_key=None), GRANT), (SETTINGS, None)],
    ids=["no-api-key", "no-grant"],
)
def test_not_configured_is_unavailable_and_never_calls_nylas(fake_client, settings, grant):
    with pytest.raises(nylas_service.NylasNotConfiguredError):
        nylas_service.get_schedule_section(grant, settings)
    result = briefing.build_briefing(settings, client=mock_client(lambda r: httpx2.Response(404)), grant_id=grant)
    assert result.schedule.status == "unavailable"
    fake_client.calendars.list.assert_not_called()


def test_malformed_and_odd_events_are_skipped(fake_client, caplog):
    raw_events = [
        {"title": "no id", "when": {"object": "timespan", "start_time": 1794816000, "end_time": 1794819600}},
        {"id": "ev-no-when", "title": "No when"},
        {"id": "ev-null-when", "title": "Null when", "when": None},
        {"id": "ev-bad-date", "title": "Bad date", "when": {"object": "date", "date": "16/11/2026"}},
        {"id": "ev-unknown", "title": "Unknown kind", "when": {"object": "somethingnew", "start_time": 1}},
        {"id": "ev-bad-type", "title": "Text time", "when": {"object": "timespan", "start_time": "nine"}},
        {"id": "ev-no-start", "title": "No start", "when": {"object": "timespan", "end_time": 1794819600}},
        {"id": "ev-untitled", "when": {"object": "timespan", "start_time": 1794816000, "end_time": 1794819600}},
        {"id": "ev-span-no-end", "title": "Open datespan", "when": {"object": "datespan", "start_date": "2026-11-16"}},
        {"id": "ev-ok", "title": "Valid", "when": {"object": "timespan", "start_time": 1794819600, "end_time": 1794823200}},
    ]
    fake_client.events.list.return_value = ListResponse(data=[Raw(e) for e in raw_events], request_id="r", next_cursor=None)
    with caplog.at_level(logging.WARNING):
        section = nylas_service.get_schedule_section(GRANT, SETTINGS)
    assert section.items == [
        ScheduleItem(title="Open datespan", all_day=True),
        ScheduleItem(title="(no title)", time="09:00"),
        ScheduleItem(title="Valid", time="10:00"),
    ]
    assert "nylas: skipped 2 malformed events of 10" in caplog.text  # no id, text start_time


def test_no_calendars_gives_empty(fake_client):
    fake_client.calendars.list.return_value = ListResponse(data=[], request_id="r", next_cursor=None)
    section = nylas_service.get_schedule_section(GRANT, SETTINGS)
    assert section.status == "empty"
    fake_client.events.list.assert_not_called()


def test_cache_hit_avoids_second_round_trip(fake_client):
    first = nylas_service.get_schedule_section(GRANT, SETTINGS)
    second = nylas_service.get_schedule_section(GRANT, SETTINGS)
    assert first == second
    assert fake_client.calendars.list.call_count == 1
    assert fake_client.events.list.call_count == 1
    # Another grant is cached separately.
    nylas_service.get_schedule_section("grant-other", SETTINGS)
    assert fake_client.calendars.list.call_count == 2


def test_logs_contain_counts_but_no_titles_or_calendar_ids(fake_client, caplog):
    with caplog.at_level(logging.DEBUG, logger="app.services.nylas_service"):
        nylas_service.get_schedule_section(GRANT, SETTINGS)
    assert "nylas: 2 calendars, 9 events fetched, 6 shown for today" in caplog.text
    for secret in ["Lecture", "birthday", "Team sync", "cal-primary", "Personal", GRANT]:
        assert secret not in caplog.text


def test_page_renders_schedule_and_uses_env_grant(fake_client, monkeypatch):
    calls = []

    def fake_build(settings, **kwargs):
        calls.append(kwargs.get("grant_id"))
        return briefing.build_briefing(
            SETTINGS, client=mock_client(lambda r: httpx2.Response(404)), grant_id=kwargs.get("grant_id")
        )

    monkeypatch.setattr(routes, "build_briefing", fake_build)
    app.dependency_overrides[routes.get_settings] = lambda: Settings(nylas_api_key="k", nylas_grant_id=GRANT)
    try:
        html = TestClient(app).get("/").text
    finally:
        app.dependency_overrides.clear()
    assert calls == [GRANT]
    assert "<li>09:00 Lecture: Distributed Systems</li>" in html
    assert "<li>All day · Sam&#39;s birthday</li>" in html


def test_all_four_providers_run_concurrently(fake_client):
    def slow_http(request):
        time.sleep(0.3)
        return httpx2.Response(404)

    def slow_calendars(*args, **kwargs):
        time.sleep(0.3)
        return sdk_list("nylas_calendars.json", Calendar)

    fake_client.calendars.list.side_effect = slow_calendars
    started = time.monotonic()
    result = briefing.build_briefing(SETTINGS, client=mock_client(slow_http), grant_id=GRANT)
    elapsed = time.monotonic() - started
    assert result.schedule.status == "ok"
    assert elapsed < 0.9  # sequentially: weather + topstories + vbb + nylas >= 1.2 s
