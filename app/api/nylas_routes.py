"""Nylas email, OAuth and webhook routes."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.schemas.nylas_email_schema import EmailObject, EmailRequest
from app.schemas.nylas_webhook_schema import WebhookEvent
from app.services import nylas_service, nylas_webhook

logger = logging.getLogger(__name__)

router = APIRouter(tags=["nylas"])


def get_grant_id(request: Request, settings: Settings = Depends(get_settings)) -> str:
    if settings.nylas_grant_id:
        return settings.nylas_grant_id
    grant_id = request.state.session.get("grant_id")
    if grant_id:
        return grant_id
    raise HTTPException(status_code=401, detail="Not authenticated")


@router.get("/nylas/auth", response_model=None)
def nylas_auth(request: Request, settings: Settings = Depends(get_settings)) -> dict[str, str] | RedirectResponse:
    if settings.nylas_grant_id:
        return {"grant_id": settings.nylas_grant_id, "source": "env"}
    grant_id = request.state.session.get("grant_id")
    if not grant_id:
        return RedirectResponse(nylas_service.build_auth_url(settings))
    return {"grant_id": grant_id, "source": "session"}


@router.get(nylas_service.OAUTH_CALLBACK_PATH)
def oauth_exchange(request: Request, code: str = Query(...), settings: Settings = Depends(get_settings)) -> RedirectResponse:
    try:
        grant_id = nylas_service.exchange_code(code, settings)
    except Exception:
        logger.exception("Nylas OAuth code exchange failed")
        raise HTTPException(status_code=400, detail="OAuth code exchange failed")
    request.state.session["grant_id"] = grant_id
    return RedirectResponse("/nylas/auth")


@router.get("/nylas/recent-emails", response_model=list[EmailObject], response_model_by_alias=True)
def recent_emails(grant_id: str = Depends(get_grant_id)) -> list[EmailObject]:
    try:
        return nylas_service.list_recent_emails(grant_id)
    except Exception:
        logger.exception("Fetching recent emails failed")
        raise HTTPException(status_code=500, detail="Could not fetch emails")


@router.post("/nylas/send-email")
def send_email(
    payload: EmailRequest,
    grant_id: str = Depends(get_grant_id),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    try:
        return nylas_service.send_email(grant_id, payload, settings)
    except Exception:
        logger.exception("Sending email failed")
        raise HTTPException(status_code=500, detail="Could not send email")


@router.get("/events", response_class=PlainTextResponse)
def webhook_challenge(challenge: str = Query(...)) -> PlainTextResponse:
    # Nylas verifies a new webhook URL by expecting the challenge echoed back.
    return PlainTextResponse(challenge, status_code=200)


@router.post("/events")
async def webhook_event(request: Request, settings: Settings = Depends(get_settings)) -> dict[str, str]:
    # The signature covers the exact bytes Nylas sent, so read them before any parsing.
    raw_body = await request.body()
    secret = settings.nylas_webhook_secret
    if not secret:
        logger.warning("Rejecting webhook: NYLAS_WEBHOOK_SECRET is not configured")
        raise HTTPException(status_code=401, detail="Invalid signature")
    if not nylas_webhook.is_valid_signature(raw_body, request.headers.get("x-nylas-signature"), secret):
        logger.warning("Rejecting webhook: missing or invalid x-nylas-signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        event = WebhookEvent.model_validate_json(raw_body)
    except ValidationError:
        # Signed by Nylas but not the shape we expect: return 200 so Nylas doesn't retry.
        logger.warning("Ignoring signed webhook with a malformed payload")
        return {"status": "ok"}

    if event.type == "message.created":
        raw = event.data.get("object")
        try:
            if not isinstance(raw, dict):
                raise ValueError("data.object is missing or not an object")
            email = nylas_service.to_email_object(raw)
        except (ValidationError, ValueError):
            # Already logged field-by-field; still return 200 so Nylas doesn't retry.
            logger.warning("Ignoring message.created webhook %s with an unexpected payload", event.id)
        else:
            logger.info("New email id=%s subject=%r thread_id=%s", email.id, email.subject, email.thread_id)
    return {"status": "ok"}
