"""Hacker News provider for the news card. Docs: https://github.com/HackerNews/API"""

import html
import logging
from concurrent.futures import ThreadPoolExecutor

import httpx2
from pydantic import ValidationError

from app.config import Settings
from app.schemas.briefing import NewsItem, NewsSection
from app.schemas.hackernews import HNItem
from app.services.cache import TTLCache
from app.services.http import is_http_url

logger = logging.getLogger(__name__)

BASE_URL = "https://hacker-news.firebaseio.com/v0"
ITEM_PAGE_URL = "https://news.ycombinator.com/item?id={id}"
# Extra ids fetched up front so deleted/dead/untitled items can be backfilled
# without a second round trip.
BACKFILL = 5
MAX_WORKERS = 10

_cache = TTLCache("hackernews")


def fetch_top_story_ids(client: httpx2.Client) -> list[int]:
    response = client.get(f"{BASE_URL}/topstories.json")
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise ValueError("topstories is not a list")
    return [i for i in data if isinstance(i, int) and not isinstance(i, bool)]


def fetch_item(client: httpx2.Client, item_id: int) -> HNItem | None:
    """Returns None for null or unparseable items; raises on HTTP/transport errors."""
    response = client.get(f"{BASE_URL}/item/{item_id}.json")
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        return None
    try:
        return HNItem.model_validate(data)
    except ValidationError:
        return None


def to_news_item(item: HNItem | None) -> NewsItem | None:
    if item is None or item.deleted or item.dead:
        return None
    title = html.unescape(item.title or "").strip()
    if not title:
        return None
    url = item.url if is_http_url(item.url) else ITEM_PAGE_URL.format(id=item.id)
    return NewsItem(title=title, url=url)


def get_news_section(client: httpx2.Client, settings: Settings) -> NewsSection:
    """Raises if topstories fails or every item request fails; skips bad items otherwise."""
    count = max(settings.hn_story_count, 0)
    key = ("top", count)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    ids = fetch_top_story_ids(client)[: count + BACKFILL] if count else []
    items: list[HNItem | None | Exception] = []
    if ids:
        with ThreadPoolExecutor(max_workers=min(len(ids), MAX_WORKERS), thread_name_prefix="hn") as pool:
            futures = [pool.submit(fetch_item, client, item_id) for item_id in ids]
            for future in futures:  # keeps topstories rank order
                try:
                    items.append(future.result())
                except Exception as exc:  # noqa: BLE001 - one item must not sink the card
                    items.append(exc)

    failed = sum(isinstance(item, Exception) for item in items)
    if ids and failed == len(ids):
        raise items[0]
    if failed:
        logger.warning("hackernews: %d of %d item requests failed", failed, len(ids))

    news = [n for n in (to_news_item(i) for i in items if not isinstance(i, Exception)) if n][:count]
    section = NewsSection.from_items(news)
    _cache.set(key, section, settings.cache_ttl_hn)
    return section
