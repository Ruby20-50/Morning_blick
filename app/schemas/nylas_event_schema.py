"""Nylas calendars and events, parsed from the SDK's `to_dict()` output.

Field names from the Nylas v3 docs:
- Calendars: https://developer.nylas.com/docs/reference/api/calendar/get-all-calendars/
- Events: https://developer.nylas.com/docs/reference/api/events/get-all-events/
- `when` objects: https://developer.nylas.com/docs/v3/calendar/using-the-events-api/
  plus the SDK's nylas.models.events (Time, Timespan, Date, Datespan).

Everything except `id` is optional and unknown fields are ignored.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class _NylasModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class CalendarObject(_NylasModel):
    id: str
    name: str | None = None
    is_primary: bool | None = None
    is_owned_by_user: bool | None = None
    read_only: bool | None = None
    timezone: str | None = None


class EventWhen(_NylasModel):
    """One of four shapes, told apart by `object`."""

    object: Literal["time", "timespan", "date", "datespan"] | str | None = None
    # time: a single point in time
    time: int | None = None
    timezone: str | None = None
    # timespan: start/end as Unix seconds
    start_time: int | None = None
    end_time: int | None = None
    start_timezone: str | None = None
    end_timezone: str | None = None
    # date: one all-day date (ISO 8601)
    date: str | None = None
    # datespan: all-day range; end_date is the day *after* the last day (exclusive)
    start_date: str | None = None
    end_date: str | None = None


class CalendarEvent(_NylasModel):
    id: str
    calendar_id: str | None = None
    title: str | None = None
    status: str | None = None  # "confirmed", "tentative", "cancelled"
    busy: bool | None = None
    when: EventWhen | None = None
