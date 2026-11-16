"""Hacker News item, field names from https://github.com/HackerNews/API#items.

Only `id` is required by the API; everything else is optional and unknown
fields are ignored.
"""

from pydantic import BaseModel, ConfigDict


class HNItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    deleted: bool | None = None
    dead: bool | None = None
    type: str | None = None  # "job", "story", "comment", "poll" or "pollopt"
    by: str | None = None
    time: int | None = None  # Unix time
    title: str | None = None  # HTML
    url: str | None = None
    score: int | None = None
    descendants: int | None = None
