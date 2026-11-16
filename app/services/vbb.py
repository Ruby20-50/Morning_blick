"""VBB provider for the transport ("Berlin updates") card.

Uses the community-run REST API https://v6.vbb.transport.rest (docs:
https://v6.vbb.transport.rest/api.html). Everything that talks to it sits behind
`get_departures()`, so it can later be swapped for the official VBB
GTFS-Realtime feed without touching the formatting or the page.

Rate limit: 100 requests/minute (burst 200). Departures are cached per stop for
CACHE_TTL_VBB seconds (default 60), so one process makes at most about one
request per minute per stop.
"""

import logging
from urllib.parse import quote

import httpx2
from pydantic import ValidationError

from app.config import Settings
from app.schemas.briefing import TransportSection
from app.schemas.vbb import Departure, DeparturesResponse
from app.services.cache import TTLCache

logger = logging.getLogger(__name__)

BASE_URL = "https://v6.vbb.transport.rest"

_cache = TTLCache("vbb")


def get_departures(client: httpx2.Client, settings: Settings, stop_id: str | None = None) -> list[Departure]:
    """Upcoming departures at a stop. Raises on HTTP errors or an unusable response."""
    stop_id = stop_id or settings.vbb_stop_id
    key = (stop_id, settings.vbb_duration_minutes)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    # The path segment is percent-encoded; query parameters are encoded by httpx2.
    response = client.get(
        f"{BASE_URL}/stops/{quote(stop_id, safe='')}/departures",
        params={"duration": settings.vbb_duration_minutes, "remarks": "false"},
    )
    response.raise_for_status()
    body = DeparturesResponse.model_validate(response.json())
    if body.departures is None:
        raise ValueError("response has no departures list")

    departures: list[Departure] = []
    skipped = 0
    for raw in body.departures:
        if not isinstance(raw, dict):
            skipped += 1
            continue
        try:
            departures.append(Departure.model_validate(raw))
        except ValidationError:
            skipped += 1
    if skipped:
        logger.warning("vbb: skipped %d malformed departures of %d", skipped, len(body.departures))

    _cache.set(key, departures, settings.cache_ttl_vbb)
    return departures


def _label(departure: Departure) -> str:
    line = (departure.line.name if departure.line else None) or "?"
    return f"{line} → {departure.direction}" if departure.direction else line


def noteworthy(departures: list[Departure], min_delay_minutes: int) -> list[str]:
    """Cancellations and delays of at least `min_delay_minutes`, one line per line+direction."""
    cancelled: dict[str, int] = {}
    delayed: dict[str, int] = {}  # label -> largest delay in minutes
    for departure in departures:
        label = _label(departure)
        if departure.cancelled is True:
            cancelled[label] = cancelled.get(label, 0) + 1
            continue
        if departure.delay is not None and departure.delay >= min_delay_minutes * 60:
            minutes = round(departure.delay / 60)
            delayed[label] = max(delayed.get(label, 0), minutes)

    lines = []
    for label in sorted(set(cancelled) | set(delayed)):
        if label in cancelled:
            count = cancelled[label]
            lines.append(f"{label}: cancelled" if count == 1 else f"{label}: {count} departures cancelled")
        if label in delayed:
            lines.append(f"{label}: +{delayed[label]} min")
    return lines


def get_transport_section(client: httpx2.Client, settings: Settings) -> TransportSection:
    departures = get_departures(client, settings)
    # "empty" renders as "No disruptions" in the template.
    return TransportSection.from_items(noteworthy(departures, settings.vbb_min_delay_minutes))
