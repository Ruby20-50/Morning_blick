"""Create the Nylas "message.created" webhook for Morning Blick.

Run from the project root:  uv run python -m app.scripts.create_webhook

Before running it, the app (uv run uvicorn app.main:app --reload) and the Cloudflare
tunnel must already be running: while the webhook is created, Nylas sends a challenge
request to SERVER_URL/events and only creates the webhook if it is echoed back.

The webhook secret is printed once. Copy it into .env as NYLAS_WEBHOOK_SECRET and
restart the app. It is never written to a file or the logs.
"""

import sys

from nylas.models.webhooks import CreateWebhookRequest, WebhookTriggers

from app.config import get_settings
from app.services.nylas_service import get_nylas_client  # same SDK client the app uses


def main() -> int:
    settings = get_settings()
    if not settings.nylas_api_key:
        print("NYLAS_API_KEY is not set in .env.", file=sys.stderr)
        return 1
    if not settings.server_url:
        print("SERVER_URL is not set in .env (use the public https URL of your tunnel).", file=sys.stderr)
        return 1
    if not settings.server_url.startswith("https://"):
        print("SERVER_URL must start with https:// (Nylas only delivers to https URLs).", file=sys.stderr)
        return 1

    request_body = CreateWebhookRequest(
        trigger_types=[WebhookTriggers.MESSAGE_CREATED],
        webhook_url=settings.server_url.rstrip("/") + "/events",
        description="Morning Blick: message created",
    )
    if settings.email:
        request_body["notification_email_addresses"] = [settings.email]

    webhook, _, _ = get_nylas_client().webhooks.create(request_body=request_body)

    print(f"Webhook created: id={webhook.id} url={webhook.webhook_url}")
    print("Copy the secret into .env as NYLAS_WEBHOOK_SECRET (never commit it), then restart the app:")
    print(webhook.webhook_secret)
    return 0


if __name__ == "__main__":
    sys.exit(main())
