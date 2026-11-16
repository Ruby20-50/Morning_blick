"""Rendering tests for index.html driven by a Briefing object (no network)."""

import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.main import app
from app.schemas.briefing import (
    Briefing,
    DateSection,
    NewsItem,
    NewsSection,
    ScheduleItem,
    ScheduleSection,
    TransportSection,
    WeatherSection,
)

client = TestClient(app)

# Strings index() used to hardcode; none may leak into a page rendered from other data.
OLD_PLACEHOLDERS = [
    "8 °C, light clouds",
    "Rain expected after 16:00",
    "S-Bahn Ring: delays between Ostkreuz and Treptower Park this morning.",
    "Review lecture notes",
    "Push milestone 1",
]


def sentinel_briefing() -> Briefing:
    return Briefing(
        date=DateSection(label="SENTINEL-DATE"),
        weather=WeatherSection.from_items(["SENTINEL-WEATHER-1", "SENTINEL-WEATHER-2"]),
        transport=TransportSection.from_items(["SENTINEL-TRANSPORT"]),
        news=NewsSection.from_items(
            [
                NewsItem(title="SENTINEL-NEWS-LINK", url="https://example.com/story"),
                NewsItem(title="SENTINEL-NEWS-NOLINK"),
            ]
        ),
        schedule=ScheduleSection.from_items(
            [
                ScheduleItem(title="SENTINEL-EVENT", time="09:00"),
                ScheduleItem(title="SENTINEL-ALLDAY", all_day=True),
            ]
        ),
    )


def render(monkeypatch, briefing: Briefing) -> str:
    monkeypatch.setattr(routes, "build_briefing", lambda settings, **kwargs: briefing)
    response = client.get("/")
    assert response.status_code == 200
    return response.text


def card_html(html: str, css_class: str) -> str:
    start = html.index(f'<section class="card {css_class}">')
    return html[start : html.index("</section>", start)]


def test_sentinels_render_and_placeholders_do_not(monkeypatch):
    html = render(monkeypatch, sentinel_briefing())
    for sentinel in [
        "SENTINEL-DATE",
        "SENTINEL-WEATHER-1",
        "SENTINEL-WEATHER-2",
        "SENTINEL-TRANSPORT",
        "SENTINEL-NEWS-LINK",
        "SENTINEL-NEWS-NOLINK",
        "09:00 SENTINEL-EVENT",
        "All day · SENTINEL-ALLDAY",
    ]:
        assert sentinel in html
    for old in OLD_PLACEHOLDERS:
        assert old not in html
    assert "No data yet" not in html
    assert "Currently unavailable" not in html


def test_news_link_has_safe_rel(monkeypatch):
    html = render(monkeypatch, sentinel_briefing())
    assert (
        '<a href="https://example.com/story" rel="noopener noreferrer" target="_blank">SENTINEL-NEWS-LINK</a>'
        in html
    )


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "data:text/html,x", "ftp://example.com/x", "//example.com", "https://"]
)
def test_non_http_urls_are_not_linked(monkeypatch, url):
    briefing = sentinel_briefing()
    briefing.news = NewsSection.from_items([NewsItem(title="SENTINEL-BADLINK", url=url)])
    news = card_html(render(monkeypatch, briefing), "news")
    assert "SENTINEL-BADLINK" in news
    assert "<a " not in news


def test_external_text_is_autoescaped(monkeypatch):
    briefing = sentinel_briefing()
    briefing.news = NewsSection.from_items([NewsItem(title="<script>alert(1)</script>")])
    briefing.weather = WeatherSection.from_items(['<img src=x onerror="x">'])
    html = render(monkeypatch, briefing)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<img src=x" not in html


SECTIONS = {
    # briefing field -> (card css class, section class, text shown when empty)
    "weather": ("weather", WeatherSection, "No data yet"),
    "transport": ("updates", TransportSection, "No disruptions"),
    "news": ("news", NewsSection, "No data yet"),
    "schedule": ("tasks", ScheduleSection, "No data yet"),
}


@pytest.mark.parametrize("field", SECTIONS)
def test_unavailable_state(monkeypatch, field):
    css, section_cls, _ = SECTIONS[field]
    briefing = sentinel_briefing()
    setattr(briefing, field, section_cls.unavailable())
    html = render(monkeypatch, briefing)
    card = card_html(html, css)
    assert "Currently unavailable" in card
    assert "<ul>" not in card
    # The other sections still render normally.
    assert html.count("Currently unavailable") == 1


@pytest.mark.parametrize("field", SECTIONS)
def test_empty_state(monkeypatch, field):
    css, section_cls, empty_text = SECTIONS[field]
    briefing = sentinel_briefing()
    setattr(briefing, field, section_cls.from_items([]))
    assert getattr(briefing, field).status == "empty"
    card = card_html(render(monkeypatch, briefing), css)
    assert empty_text in card
    assert "<ul>" not in card
    assert "Currently unavailable" not in card


def test_default_page_without_network():
    # conftest blocks the network, so every live provider renders "unavailable"
    # while the date, form and footer still render.
    html = client.get("/").text
    assert "Currently unavailable" in card_html(html, "weather")
    assert "Currently unavailable" in card_html(html, "updates")
    assert "Currently unavailable" in card_html(html, "tasks")
    for old in OLD_PLACEHOLDERS:
        assert old not in html
    assert "Currently unavailable" in card_html(html, "news")
    assert 'action="/ask"' in html
