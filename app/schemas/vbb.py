"""VBB departures, as returned by the community REST API v6.vbb.transport.rest.

Docs: https://v6.vbb.transport.rest/api.html (GET /stops/:id/departures) and the
underlying hafas-client departure format. Everything is optional and unknown
fields are ignored. `delay` is in seconds (the docs' example shows 60 for one
minute; it equals `when - plannedWhen`).
"""

from pydantic import BaseModel, ConfigDict


class _VBBModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Line(_VBBModel):
    id: str | None = None
    name: str | None = None  # e.g. "S5", "U2", "M48"
    product: str | None = None  # e.g. "suburban", "subway", "bus"
    mode: str | None = None


class Departure(_VBBModel):
    tripId: str | None = None
    direction: str | None = None
    line: Line | None = None
    when: str | None = None  # ISO 8601, includes the delay; null when cancelled
    plannedWhen: str | None = None
    delay: int | None = None  # seconds; null when unknown or cancelled
    platform: str | None = None
    plannedPlatform: str | None = None
    cancelled: bool | None = None  # true on cancelled departures, otherwise absent


class DeparturesResponse(_VBBModel):
    # Raw dicts: each departure is validated on its own so one bad entry is skipped.
    departures: list[object] | None = None
    realtimeDataUpdatedAt: int | None = None
