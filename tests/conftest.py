"""Shared test setup: no test may reach the network, and caches start empty."""

import json
from pathlib import Path

import httpx2
import pytest
import requests

from app.services import cache, http

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _refuse_network(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ConnectError("network access is disabled in tests", request=request)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any client the app builds itself refuses to connect; tests pass their own MockTransport client."""
    monkeypatch.setattr(
        http, "make_http_client", lambda settings: httpx2.Client(transport=httpx2.MockTransport(_refuse_network))
    )


@pytest.fixture(autouse=True)
def no_nylas_network(monkeypatch):
    """The Nylas SDK sends requests via requests.request; refuse them (tests use a fake client)."""

    def refuse(*args, **kwargs):
        raise requests.ConnectionError("network access is disabled in tests")

    monkeypatch.setattr(requests, "request", refuse)


@pytest.fixture(autouse=True)
def empty_caches():
    cache.clear_all()
    yield
    cache.clear_all()


def mock_client(handler) -> httpx2.Client:
    return httpx2.Client(transport=httpx2.MockTransport(handler))
