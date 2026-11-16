"""Builds the Briefing shown on the index page.

Each provider runs in its own worker thread with its own deadline and error
handling, so total latency is roughly the slowest provider and one failure
only turns its own card "unavailable".
"""

import logging
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx2

from app.config import Settings
from app.schemas.briefing import (
    Briefing,
    DateSection,
    NewsSection,
    ScheduleSection,
    TransportSection,
    WeatherSection,
)
from app.services import hackernews, http, nylas_service, vbb, weather

logger = logging.getLogger(__name__)

DATE_FORMAT = "%A, %d %B %Y"


def today_label(settings: Settings) -> str:
    return datetime.now(ZoneInfo(settings.timezone)).strftime(DATE_FORMAT)


# name -> (zero-argument callable returning a section, section class for the fallback)
Providers = dict[str, tuple[Callable[[], object], type]]


def run_providers(providers: Providers, timeout: float) -> dict[str, object]:
    """Run all providers concurrently; any error or overrun becomes `unavailable()`."""
    results: dict[str, object] = {}
    executor = ThreadPoolExecutor(max_workers=max(len(providers), 1), thread_name_prefix="briefing")
    try:
        futures: dict[str, Future] = {name: executor.submit(fn) for name, (fn, _) in providers.items()}
        deadline = time.monotonic() + timeout
        for name, future in futures.items():
            fallback = providers[name][1]
            try:
                results[name] = future.result(timeout=max(0.0, deadline - time.monotonic()))
            except Exception as exc:  # noqa: BLE001 - one provider must never break the page
                # Only the exception type: messages can contain URLs, ids or payload snippets.
                logger.warning("briefing provider %s failed: %s", name, type(exc).__name__)
                results[name] = fallback.unavailable()
    finally:
        # Do not wait for a provider that overran its deadline.
        executor.shutdown(wait=False, cancel_futures=True)
    return results


def build_briefing(
    settings: Settings, *, client: httpx2.Client | None = None, grant_id: str | None = None
) -> Briefing:
    """All four providers concurrently; the Nylas SDK is blocking and runs in the same pool."""
    own_client = client is None
    if own_client:
        client = http.make_http_client(settings)
    try:
        providers: Providers = {
            "weather": (lambda: weather.get_weather_section(client, settings), WeatherSection),
            "news": (lambda: hackernews.get_news_section(client, settings), NewsSection),
            "transport": (lambda: vbb.get_transport_section(client, settings), TransportSection),
            "schedule": (lambda: nylas_service.get_schedule_section(grant_id, settings), ScheduleSection),
        }
        results = run_providers(providers, settings.provider_timeout)
    finally:
        if own_client:
            client.close()

    return Briefing(
        date=DateSection(label=today_label(settings)),
        weather=results["weather"],
        transport=results["transport"],
        news=results["news"],
        schedule=results["schedule"],
    )
