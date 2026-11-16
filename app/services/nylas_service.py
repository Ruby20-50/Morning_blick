"""Nylas integration: client factory, OAuth helpers, email, and today's calendar events."""

import logging
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

from nylas import Client
from nylas.models.auth import CodeExchangeRequest, URLForAuthenticationConfig
from nylas.models.drafts import EmailName, SendMessageRequest  # EmailName is defined in nylas.models.events
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.schemas.briefing import ScheduleItem, ScheduleSection
from app.schemas.nylas_email_schema import EmailObject, EmailRequest
from app.schemas.nylas_event_schema import CalendarEvent, CalendarObject
from app.services.cache import TTLCache

logger = logging.getLogger(__name__)

OAUTH_CALLBACK_PATH = "/oauth/exchange"


@lru_cache
def get_nylas_client() -> Client:
    """Create the Nylas client on first use (never at import time) and cache it."""
    settings = get_settings()
    if not settings.nylas_api_key:
        raise RuntimeError("NYLAS_API_KEY is not configured")
    return Client(api_key=settings.nylas_api_key, api_uri=settings.nylas_api_uri)


def redirect_uri(settings: Settings) -> str:
    """The OAuth redirect URI; must be registered exactly like this in the Nylas dashboard."""
    return f"{settings.app_base_url.rstrip('/')}{OAUTH_CALLBACK_PATH}"


def build_auth_url(settings: Settings) -> str:
    config = URLForAuthenticationConfig(
        client_id=settings.nylas_client_id,
        redirect_uri=redirect_uri(settings),
    )
    return get_nylas_client().auth.url_for_oauth2(config)


def exchange_code(code: str, settings: Settings) -> str:
    """Exchange an OAuth code for a grant and return its grant_id."""
    request = CodeExchangeRequest(
        redirect_uri=redirect_uri(settings),
        code=code,
        client_id=settings.nylas_client_id,
    )
    exchange = get_nylas_client().auth.exchange_code_for_token(request)
    return exchange.grant_id


def _drop_none(data: dict[str, Any]) -> dict[str, Any]:
    # The SDK's to_dict() emits None for fields the API left out (e.g. bcc, cc,
    # attachments). Dropping them lets the model's defaults apply; required
    # fields that are None still fail validation as "missing".
    return {key: value for key, value in data.items() if value is not None}


def to_email_object(raw: dict[str, Any]) -> EmailObject:
    """Validate one raw message dict; logs failing fields (never their values) on error."""
    try:
        return EmailObject.model_validate(_drop_none(raw))
    except ValidationError as exc:
        fields = [".".join(str(part) for part in err["loc"]) + f" ({err['type']})" for err in exc.errors()]
        logger.error("EmailObject validation failed for message id=%s: %s", raw.get("id"), ", ".join(fields))
        raise


def list_recent_emails(grant_id: str) -> list[EmailObject]:
    # messages.list returns a ListResponse tuple: (data, request_id, next_cursor, headers).
    messages = get_nylas_client().messages.list(grant_id, None)[0]
    return [to_email_object(message.to_dict()) for message in messages]


def send_email(grant_id: str, payload: EmailRequest, settings: Settings) -> dict[str, Any]:
    body = SendMessageRequest(
        subject=payload.subject,
        body=payload.body,
        reply_to=[EmailName(name="Name", email=settings.email)],
        to=[EmailName(name="Name", email=payload.to_email)],
    )
    result = get_nylas_client().messages.send(grant_id, request_body=body)
    # .data is a Message dataclass; to_dict() keeps the API's "from" key.
    return result.data.to_dict()


# --- Calendar events for the briefing --------------------------------------
# Logging rule: ids and counts only. Never titles, and no calendar ids either
# (for Google accounts the calendar id is an email address).

MAX_PAGES = 5  # pagination safety net (default page size is 50)

_events_cache = TTLCache("nylas_events")


class NylasNotConfiguredError(RuntimeError):
    """No API key or no grant: the schedule card shows "unavailable"."""


def _list_all(list_page, max_pages: int = MAX_PAGES) -> list[dict[str, Any]]:
    """Follow next_cursor; `list_page(page_token)` returns an SDK ListResponse."""
    items: list[dict[str, Any]] = []
    token = None
    for _ in range(max_pages):
        response = list_page(token)
        items.extend(_drop_none(obj.to_dict()) for obj in response.data or [])
        token = response.next_cursor
        if not token:
            break
    return items


def _validated(model, raws: list[dict[str, Any]], kind: str) -> list:
    valid, skipped = [], 0
    for raw in raws:
        try:
            valid.append(model.model_validate(raw))
        except ValidationError:
            skipped += 1
    if skipped:
        logger.warning("nylas: skipped %d malformed %s of %d", skipped, kind, len(raws))
    return valid


def pick_primary_calendar(calendars: list[CalendarObject]) -> CalendarObject | None:
    """The calendar flagged is_primary; else the first one the user owns; else the first one."""
    for predicate in (lambda c: c.is_primary is True, lambda c: c.is_owned_by_user is True, lambda c: True):
        for calendar in calendars:
            if predicate(calendar):
                return calendar
    return None


def today(tz: ZoneInfo) -> date:
    return datetime.now(tz).date()


def day_bounds(day: date, tz: ZoneInfo) -> tuple[int, int]:
    """Local midnight to next local midnight, as Unix seconds (DST-safe)."""
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return int(start.timestamp()), int(end.timestamp())


def _parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def to_schedule_item(event: CalendarEvent, day: date, tz: ZoneInfo) -> tuple[int, ScheduleItem] | None:
    """(sort key, item) for an event on `day`, or None if it is not on that day or unusable.

    Handles every `when` type: time, timespan, date and datespan.
    """
    if event.status == "cancelled" or event.when is None:
        return None
    when = event.when
    title = (event.title or "").strip() or "(no title)"
    day_start, day_end = day_bounds(day, tz)

    if when.object == "timespan" or (when.object is None and when.start_time is not None):
        if when.start_time is None:
            return None
        start = when.start_time
        end = max(when.end_time if when.end_time is not None else start, start)
        # Keep events that overlap today, including zero-length ones that start today.
        if not (start < day_end and (end > day_start or start >= day_start)):
            return None
        # An event that began before midnight (e.g. overnight) is listed at 00:00.
        label = datetime.fromtimestamp(start, tz).strftime("%H:%M") if start >= day_start else "00:00"
        return max(start, day_start), ScheduleItem(title=title, time=label)

    if when.object == "time" or (when.object is None and when.time is not None):
        if when.time is None or not (day_start <= when.time < day_end):
            return None
        return when.time, ScheduleItem(title=title, time=datetime.fromtimestamp(when.time, tz).strftime("%H:%M"))

    if when.object == "date" or (when.object is None and when.date is not None):
        if _parse_date(when.date) != day:
            return None
        return day_start, ScheduleItem(title=title, all_day=True)

    if when.object == "datespan" or (when.object is None and when.start_date is not None):
        first, after_last = _parse_date(when.start_date), _parse_date(when.end_date)
        if first is None:
            return None
        if after_last is None or after_last <= first:
            after_last = first + timedelta(days=1)
        if not (first <= day < after_last):  # end_date is exclusive per the Nylas docs
            return None
        return day_start, ScheduleItem(title=title, all_day=True)

    return None


def list_today_events(grant_id: str, settings: Settings, day: date | None = None) -> list[ScheduleItem]:
    """Today's events from the grant's primary calendar, sorted by start (all-day first)."""
    tz = ZoneInfo(settings.timezone)
    day = day or today(tz)
    client = get_nylas_client()
    overrides = {"timeout": settings.http_timeout}

    calendars = _validated(
        CalendarObject,
        _list_all(lambda token: client.calendars.list(
            grant_id, query_params={"page_token": token} if token else None, overrides=overrides
        )),
        "calendars",
    )
    calendar = pick_primary_calendar(calendars)
    if calendar is None:
        logger.info("nylas: grant has no calendars")
        return []

    start, end = day_bounds(day, tz)

    def events_page(token):
        params = {"calendar_id": calendar.id, "start": start, "end": end}
        if token:
            params["page_token"] = token
        return client.events.list(grant_id, query_params=params, overrides=overrides)

    events = _validated(CalendarEvent, _list_all(events_page), "events")
    entries = [entry for entry in (to_schedule_item(e, day, tz) for e in events) if entry]
    entries.sort(key=lambda entry: (not entry[1].all_day, entry[0]))
    logger.info(
        "nylas: %d calendars, %d events fetched, %d shown for today", len(calendars), len(events), len(entries)
    )
    return [item for _, item in entries]


def get_schedule_section(grant_id: str | None, settings: Settings) -> ScheduleSection:
    """Blocking (Nylas SDK); the briefing runs it in its thread pool."""
    if not settings.nylas_api_key or not grant_id:
        raise NylasNotConfiguredError("Nylas API key or grant missing")
    day = today(ZoneInfo(settings.timezone))
    key = (grant_id, day.isoformat())
    cached = _events_cache.get(key)
    if cached is not None:
        return cached
    section = ScheduleSection.from_items(list_today_events(grant_id, settings, day))
    _events_cache.set(key, section, settings.cache_ttl_nylas)
    return section
