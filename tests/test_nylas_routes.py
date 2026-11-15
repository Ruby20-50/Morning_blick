import logging
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from nylas import Client
from nylas.models.auth import CodeExchangeResponse
from nylas.models.messages import Message
from nylas.models.response import ListResponse, Response

from app.config import Settings, get_settings
from app.main import create_app
from app.services import nylas_service

from tests.test_nylas_schemas import sample_email

BASE_URL = "http://localhost:8000"


def make_settings(**overrides) -> Settings:
    values = dict(
        nylas_api_key="test-key",
        nylas_client_id="test-client-id",
        nylas_grant_id=None,
        email="me@example.com",
        server_url="https://public.example.com",
        app_base_url=BASE_URL,
    )
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def fake_client(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(nylas_service, "get_nylas_client", lambda: fake)
    return fake


@pytest.fixture
def make_client():
    """Build a TestClient with the given settings (never reads the real .env values)."""

    def _make(**overrides) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_settings] = lambda: make_settings(**overrides)
        return TestClient(app)

    return _make


def sdk_message(**overrides) -> Message:
    # Built through the real SDK model so to_dict() behaves like real data
    # (e.g. absent bcc/cc/attachments come out as None).
    data = sample_email(**overrides)
    del data["attachments"]
    return Message.from_dict(data)


# --- auth / OAuth -----------------------------------------------------------

def test_auth_redirects_to_nylas(monkeypatch, make_client):
    real = Client(api_key="test-key")  # url_for_oauth2 builds the URL locally, no network
    monkeypatch.setattr(nylas_service, "get_nylas_client", lambda: real)
    response = make_client().get("/nylas/auth", follow_redirects=False)
    assert response.status_code == 307
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["client_id"] == ["test-client-id"]
    assert query["redirect_uri"] == [f"{BASE_URL}/oauth/exchange"]


def test_auth_returns_env_grant(fake_client, make_client):
    response = make_client(nylas_grant_id="env-grant").get("/nylas/auth")
    assert response.json() == {"grant_id": "env-grant", "source": "env"}
    fake_client.auth.url_for_oauth2.assert_not_called()


def test_exchange_stores_grant_in_session(fake_client, make_client):
    fake_client.auth.exchange_code_for_token.return_value = CodeExchangeResponse(
        access_token="tok", grant_id="session-grant", scope="email", expires_in=3600
    )
    client = make_client()
    response = client.get("/oauth/exchange", params={"code": "abc"}, follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/nylas/auth"
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "max-age=1209600" in cookie and "samesite=lax" in cookie

    request = fake_client.auth.exchange_code_for_token.call_args.args[0]
    assert request == {"redirect_uri": f"{BASE_URL}/oauth/exchange", "code": "abc", "client_id": "test-client-id"}

    assert client.get("/nylas/auth").json() == {"grant_id": "session-grant", "source": "session"}


def test_exchange_failure_is_generic(fake_client, make_client):
    fake_client.auth.exchange_code_for_token.side_effect = Exception("secret internal detail")
    response = make_client().get("/oauth/exchange", params={"code": "bad"})
    assert response.status_code == 400
    assert "secret internal detail" not in response.text


def test_unknown_session_cookie_gets_new_id(make_client):
    client = make_client()
    client.cookies.set("session_id", "not-a-real-session")
    response = client.get("/health")
    assert response.cookies["session_id"] != "not-a-real-session"


# --- grant id dependency ----------------------------------------------------

def test_grant_dependency_env(fake_client, make_client):
    fake_client.messages.list.return_value = ListResponse(data=[], request_id="r1")
    response = make_client(nylas_grant_id="env-grant").get("/nylas/recent-emails")
    assert response.status_code == 200
    assert fake_client.messages.list.call_args.args == ("env-grant", None)


def test_grant_dependency_session(fake_client, make_client):
    fake_client.auth.exchange_code_for_token.return_value = CodeExchangeResponse(
        access_token="tok", grant_id="session-grant", scope="email", expires_in=3600
    )
    fake_client.messages.list.return_value = ListResponse(data=[], request_id="r1")
    client = make_client()
    client.get("/oauth/exchange", params={"code": "abc"}, follow_redirects=False)
    assert client.get("/nylas/recent-emails").status_code == 200
    assert fake_client.messages.list.call_args.args == ("session-grant", None)


def test_grant_dependency_401(fake_client, make_client):
    response = make_client().get("/nylas/recent-emails")
    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}
    fake_client.messages.list.assert_not_called()


# --- recent emails / send ---------------------------------------------------

def test_recent_emails_shape(fake_client, make_client):
    fake_client.messages.list.return_value = ListResponse(data=[sdk_message()], request_id="r1")
    response = make_client(nylas_grant_id="g").get("/nylas/recent-emails")
    assert response.status_code == 200
    [email] = response.json()
    assert email["from"] == [{"email": "alice@example.com", "name": "Alice"}]
    assert "from_" not in email
    assert email["bcc"] == [] and email["attachments"] == []
    assert email["subject"] == "Morning"


def test_recent_emails_invalid_data_logs_fields(fake_client, make_client, caplog):
    fake_client.messages.list.return_value = ListResponse(data=[sdk_message(subject=None)], request_id="r1")
    with caplog.at_level(logging.ERROR):
        response = make_client(nylas_grant_id="g").get("/nylas/recent-emails")
    assert response.status_code == 500
    assert response.json() == {"detail": "Could not fetch emails"}
    assert "subject (missing)" in caplog.text


def test_recent_emails_generic_error(fake_client, make_client):
    fake_client.messages.list.side_effect = Exception("api key sk-123 rejected")
    response = make_client(nylas_grant_id="g").get("/nylas/recent-emails")
    assert response.status_code == 500
    assert response.json() == {"detail": "Could not fetch emails"}
    assert "sk-123" not in response.text


def test_send_email(fake_client, make_client):
    fake_client.messages.send.return_value = Response(data=sdk_message(id="sent-1"), request_id="r2")
    payload = {"subject": "Hi", "body": "Hello there", "to_email": "bob@example.com"}
    response = make_client(nylas_grant_id="g").post("/nylas/send-email", json=payload)
    assert response.status_code == 200
    assert response.json()["id"] == "sent-1"

    call = fake_client.messages.send.call_args
    assert call.args == ("g",)
    assert call.kwargs["request_body"] == {
        "subject": "Hi",
        "body": "Hello there",
        "reply_to": [{"name": "Name", "email": "me@example.com"}],
        "to": [{"name": "Name", "email": "bob@example.com"}],
    }


def test_send_email_generic_error(fake_client, make_client):
    fake_client.messages.send.side_effect = Exception("boom: internal")
    payload = {"subject": "Hi", "body": "x", "to_email": "bob@example.com"}
    response = make_client(nylas_grant_id="g").post("/nylas/send-email", json=payload)
    assert response.status_code == 500
    assert response.json() == {"detail": "Could not send email"}


# --- client factory ---------------------------------------------------------

def test_client_factory_requires_key(monkeypatch):
    nylas_service.get_nylas_client.cache_clear()
    monkeypatch.setattr(nylas_service, "get_settings", lambda: make_settings(nylas_api_key=None))
    with pytest.raises(RuntimeError):
        nylas_service.get_nylas_client()
    nylas_service.get_nylas_client.cache_clear()
