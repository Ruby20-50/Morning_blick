import hashlib
import hmac
import json
import logging
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from nylas.models.response import Response
from nylas.models.webhooks import WebhookTriggers, WebhookWithSecret

from app.config import get_settings
from app.main import create_app
from app.scripts import create_webhook
from app.services.nylas_webhook import is_valid_signature

from tests.test_nylas_routes import make_settings
from tests.test_nylas_schemas import sample_email

SECRET = "test-webhook-secret"  # dummy value, only used in tests


def sign(body: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def webhook_body(obj: dict | None = None) -> bytes:
    return json.dumps(
        {
            "specversion": "1.0",
            "type": "message.created",
            "source": "/google/emails/realtime",
            "id": "evt-1",
            "time": 1731657600,
            "webhook_delivery_attempt": 1,
            "data": {"application_id": "app-1", "object": obj if obj is not None else sample_email()},
        }
    ).encode()


@pytest.fixture
def make_client():
    def _make(**overrides) -> TestClient:
        app = create_app()
        settings = make_settings(**{"nylas_webhook_secret": SECRET, **overrides})
        app.dependency_overrides[get_settings] = lambda: settings
        return TestClient(app)

    return _make


def post_events(client: TestClient, body: bytes, signature: str | None):
    headers = {"content-type": "application/json"}
    if signature is not None:
        headers["x-nylas-signature"] = signature
    return client.post("/events", content=body, headers=headers)


# --- is_valid_signature -----------------------------------------------------

def test_signature_helper():
    body = b'{"a": 1}'
    assert is_valid_signature(body, sign(body), SECRET)
    assert is_valid_signature(body, sign(body).upper(), SECRET)  # hex case-insensitive
    assert not is_valid_signature(body + b" ", sign(body), SECRET)
    assert not is_valid_signature(body, sign(body, "other"), SECRET)
    assert not is_valid_signature(body, None, SECRET)
    assert not is_valid_signature(body, "", SECRET)
    assert not is_valid_signature(body, sign(body), "")
    assert not is_valid_signature(body, "ü" * 64, SECRET)  # non-ASCII must not raise


# --- POST /events -----------------------------------------------------------

def test_valid_signature_200(make_client, caplog):
    body = webhook_body()
    with caplog.at_level(logging.INFO):
        response = post_events(make_client(), body, sign(body))
    assert response.status_code == 200
    assert "msg-1" in caplog.text and "thread-1" in caplog.text
    assert "<p>Hello</p>" not in caplog.text  # body is never logged
    assert SECRET not in caplog.text


def test_wrong_signature_401(make_client):
    body = webhook_body()
    response = post_events(make_client(), body, sign(body, "wrong-secret"))
    assert response.status_code == 401


def test_body_changed_after_signing_401(make_client):
    body = webhook_body()
    response = post_events(make_client(), body.replace(b"Morning", b"Evening"), sign(body))
    assert response.status_code == 401


def test_missing_header_401(make_client):
    response = post_events(make_client(), webhook_body(), None)
    assert response.status_code == 401


def test_secret_not_configured_401(make_client):
    body = webhook_body()
    response = post_events(make_client(nylas_webhook_secret=None), body, sign(body))
    assert response.status_code == 401


def test_malformed_but_signed_body_200(make_client, caplog):
    body = b'{"not": "a webhook"'  # invalid JSON
    response = post_events(make_client(), body, sign(body))
    assert response.status_code == 200
    assert "malformed" in caplog.text


def test_signed_event_with_invalid_inner_object_200(make_client, caplog):
    bad = sample_email()
    del bad["from"]
    body = webhook_body(bad)
    response = post_events(make_client(), body, sign(body))
    assert response.status_code == 200
    assert "from (missing)" in caplog.text


# --- GET /events (unchanged) ------------------------------------------------

def test_challenge_get_echoes(make_client):
    response = make_client(nylas_webhook_secret=None).get("/events", params={"challenge": "xyz123"})
    assert response.status_code == 200
    assert response.text == "xyz123"
    assert response.headers["content-type"].startswith("text/plain")


# --- create_webhook script --------------------------------------------------

def fake_nylas(monkeypatch) -> MagicMock:
    fake = MagicMock()
    fake.webhooks.create.return_value = Response(
        data=WebhookWithSecret(
            id="wh-1",
            trigger_types=[WebhookTriggers.MESSAGE_CREATED],
            webhook_url="https://public.example.com/events",
            status="active",
            notification_email_addresses=[],
            status_updated_at=0,
            created_at=0,
            updated_at=0,
            webhook_secret="printed-once",
        ),
        request_id="r",
    )
    monkeypatch.setattr(create_webhook, "get_nylas_client", lambda: fake)
    return fake


def test_create_webhook_script(monkeypatch, capsys):
    fake = fake_nylas(monkeypatch)
    monkeypatch.setattr(create_webhook, "get_settings", lambda: make_settings(server_url="https://public.example.com/"))
    assert create_webhook.main() == 0
    body = fake.webhooks.create.call_args.kwargs["request_body"]
    assert body == {
        "trigger_types": [WebhookTriggers.MESSAGE_CREATED],
        "webhook_url": "https://public.example.com/events",
        "description": "Morning Blick: message created",
        "notification_email_addresses": ["me@example.com"],
    }
    out = capsys.readouterr().out
    assert "wh-1" in out and out.count("printed-once") == 1 and "NYLAS_WEBHOOK_SECRET" in out


def test_create_webhook_without_email(monkeypatch):
    fake = fake_nylas(monkeypatch)
    monkeypatch.setattr(create_webhook, "get_settings", lambda: make_settings(email=None))
    assert create_webhook.main() == 0
    assert "notification_email_addresses" not in fake.webhooks.create.call_args.kwargs["request_body"]


@pytest.mark.parametrize(
    "overrides",
    [{"nylas_api_key": None}, {"server_url": None}, {"server_url": "http://public.example.com"}],
)
def test_create_webhook_refuses_bad_config(monkeypatch, capsys, overrides):
    fake = fake_nylas(monkeypatch)
    monkeypatch.setattr(create_webhook, "get_settings", lambda: make_settings(**overrides))
    assert create_webhook.main() == 1
    fake.webhooks.create.assert_not_called()
    assert capsys.readouterr().err
