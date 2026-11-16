"""Hacker News provider tests. All HTTP goes through httpx2.MockTransport."""

import json
import logging
import re
import threading
import time

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.config import Settings
from app.main import app
from app.schemas.briefing import NewsItem
from app.services import briefing, hackernews
from tests.conftest import load_fixture, mock_client

SETTINGS = Settings()
TOP = load_fixture("hn_topstories.json")
ITEMS = load_fixture("hn_items.json")
ITEM_PATH = re.compile(r"^/v0/item/(\d+)\.json$")


def json_response(payload) -> httpx2.Response:
    # Response(json=None) sends an empty body; the real API sends the literal `null`.
    return httpx2.Response(200, content=json.dumps(payload), headers={"content-type": "application/json"})


def hn_handler(top=TOP, items=ITEMS, calls: list | None = None, item_override=None):
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.host == "hacker-news.firebaseio.com"
        if calls is not None:
            calls.append(request.url.path)
        if request.url.path == "/v0/topstories.json":
            return json_response(top)
        match = ITEM_PATH.match(request.url.path)
        assert match, request.url.path
        if item_override:
            response = item_override(int(match[1]), request)
            if response is not None:
                return response
        return json_response(items.get(match[1]))

    return handler


def test_happy_path_skips_bad_items_and_keeps_rank_order():
    calls: list[str] = []
    section = hackernews.get_news_section(mock_client(hn_handler(calls=calls)), SETTINGS)

    assert section.status == "ok"
    assert section.items == [
        NewsItem(title="Show HN: Tea & Biscuits, a tiny scheduler", url="https://example.com/tea"),
        # No url -> HN item page
        NewsItem(title="Ask HN: How do you take notes?", url="https://news.ycombinator.com/item?id=9005"),
        NewsItem(title="Acme (YC W24) is hiring engineers", url="https://acme.example/jobs"),
        # Non-http url -> HN item page instead
        NewsItem(title="Suspicious link", url="https://news.ycombinator.com/item?id=9008"),
        NewsItem(title="A story about <b>bold</b> HTML", url="http://example.org/bold"),
    ]
    # topstories + count + BACKFILL item requests; 9011/9012 are never fetched.
    assert calls[0] == "/v0/topstories.json"
    assert sorted(calls[1:]) == [f"/v0/item/{i}.json" for i in range(9001, 9011)]


def test_story_count_setting_is_respected():
    section = hackernews.get_news_section(mock_client(hn_handler()), Settings(hn_story_count=2))
    assert [item.title for item in section.items] == [
        "Show HN: Tea & Biscuits, a tiny scheduler",
        "Ask HN: How do you take notes?",
    ]


def test_items_are_fetched_concurrently():
    active = 0
    peak = 0
    lock = threading.Lock()

    def slow_item(item_id, request):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.2)
        with lock:
            active -= 1
        return None

    started = time.monotonic()
    hackernews.get_news_section(mock_client(hn_handler(item_override=slow_item)), SETTINGS)
    elapsed = time.monotonic() - started
    assert peak > 1
    assert elapsed < 1.0  # 10 items x 0.2 s sequentially would be 2 s


def test_topstories_timeout_makes_section_unavailable(caplog):
    def handler(request):
        raise httpx2.ReadTimeout("timed out", request=request)

    with caplog.at_level(logging.WARNING):
        result = briefing.build_briefing(SETTINGS, client=mock_client(handler))
    assert result.news.status == "unavailable"
    assert "briefing provider news failed: ReadTimeout" in caplog.text


def test_single_item_timeout_is_skipped(caplog):
    def flaky(item_id, request):
        if item_id == 9001:
            raise httpx2.ReadTimeout("timed out", request=request)
        return None

    with caplog.at_level(logging.WARNING):
        section = hackernews.get_news_section(mock_client(hn_handler(item_override=flaky)), SETTINGS)
    titles = [item.title for item in section.items]
    assert "Show HN: Tea & Biscuits, a tiny scheduler" not in titles
    assert titles[-1] == "Sixth valid story"  # backfilled
    assert "hackernews: 1 of 10 item requests failed" in caplog.text
    # Titles are never logged.
    assert "Ask HN" not in caplog.text


def test_all_item_requests_failing_is_unavailable():
    def broken(item_id, request):
        return httpx2.Response(500)

    result = briefing.build_briefing(SETTINGS, client=mock_client(hn_handler(item_override=broken)))
    assert result.news.status == "unavailable"


@pytest.mark.parametrize("top", [None, {"0": 1}, "9001"], ids=["null", "object", "string"])
def test_malformed_topstories_is_unavailable(top):
    result = briefing.build_briefing(SETTINGS, client=mock_client(hn_handler(top=top)))
    assert result.news.status == "unavailable"


def test_empty_topstories_is_empty():
    section = hackernews.get_news_section(mock_client(hn_handler(top=[])), SETTINGS)
    assert section.status == "empty"


def test_malformed_and_null_items_are_skipped():
    top = [1, 2, 3, 4, 5, "x", True, 6]
    items = {
        "1": None,
        "2": {"id": "not-a-number", "title": "bad id"},
        "3": {"id": 3, "title": 12345},  # title must be a string
        "4": [1, 2],
        "5": {"id": 5, "title": "   ", "type": "story"},
        "6": {"id": 6, "title": "The only good one", "type": "story"},
    }
    section = hackernews.get_news_section(mock_client(hn_handler(top=top, items=items)), SETTINGS)
    assert section.items == [NewsItem(title="The only good one", url="https://news.ycombinator.com/item?id=6")]


def test_cache_hit_avoids_second_round_trip():
    calls: list[str] = []
    client = mock_client(hn_handler(calls=calls))
    first = hackernews.get_news_section(client, SETTINGS)
    count = len(calls)
    second = hackernews.get_news_section(client, SETTINGS)
    assert first == second
    assert len(calls) == count == 11


def test_page_renders_news_links(monkeypatch):
    client = mock_client(hn_handler())
    monkeypatch.setattr(routes, "build_briefing", lambda settings, **kwargs: briefing.build_briefing(settings, client=client))
    html = TestClient(app).get("/").text
    assert (
        '<a href="https://example.com/tea" rel="noopener noreferrer" target="_blank">'
        "Show HN: Tea &amp; Biscuits, a tiny scheduler</a>" in html
    )
    assert "A story about &lt;b&gt;bold&lt;/b&gt; HTML" in html
    assert "javascript:" not in html
