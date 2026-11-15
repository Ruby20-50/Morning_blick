"""Nylas integration: client factory, OAuth helpers, listing and sending email."""

import logging
from functools import lru_cache
from typing import Any

from nylas import Client
from nylas.models.auth import CodeExchangeRequest, URLForAuthenticationConfig
from nylas.models.drafts import EmailName, SendMessageRequest  # EmailName is defined in nylas.models.events
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.schemas.nylas_email_schema import EmailObject, EmailRequest

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
