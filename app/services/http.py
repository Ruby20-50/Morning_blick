"""Factory for the shared httpx2 client used by the briefing providers.

Tests replace `make_http_client` (see tests/conftest.py) so no request can
reach the network.
"""

from urllib.parse import urlsplit

import httpx2

from app.config import Settings

USER_AGENT = "morning-blick/0.1"


def make_http_client(settings: Settings) -> httpx2.Client:
    return httpx2.Client(
        timeout=httpx2.Timeout(settings.http_timeout),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=False,
    )


def is_http_url(value: object) -> bool:
    """Only http(s) URLs with a host may become links (also registered as a Jinja test)."""
    if not isinstance(value, str):
        return False
    parts = urlsplit(value.strip())
    return parts.scheme in {"http", "https"} and bool(parts.netloc)
