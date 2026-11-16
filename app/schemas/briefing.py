"""View model for the index page: one typed section per card.

Every section carries a status:
- "ok": the provider answered and there is something to show
- "empty": the provider answered but there is nothing to show
- "unavailable": the provider failed (timeout, HTTP error, bad data, not configured)
"""

from typing import Literal, Self

from pydantic import BaseModel, Field

Status = Literal["ok", "empty", "unavailable"]


class _Section(BaseModel):
    status: Status = "empty"

    @classmethod
    def from_items(cls, items: list) -> Self:
        return cls(status="ok" if items else "empty", items=items)

    @classmethod
    def unavailable(cls) -> Self:
        return cls(status="unavailable")


class DateSection(BaseModel):
    label: str


class WeatherSection(_Section):
    items: list[str] = Field(default_factory=list)


class TransportSection(_Section):
    items: list[str] = Field(default_factory=list)


class NewsItem(BaseModel):
    title: str
    url: str | None = None


class NewsSection(_Section):
    items: list[NewsItem] = Field(default_factory=list)


class ScheduleItem(BaseModel):
    title: str
    time: str | None = None  # "09:00"; None when there is no clock time
    all_day: bool = False


class ScheduleSection(_Section):
    items: list[ScheduleItem] = Field(default_factory=list)


class Briefing(BaseModel):
    date: DateSection
    weather: WeatherSection
    transport: TransportSection
    news: NewsSection
    schedule: ScheduleSection
