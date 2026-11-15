"""Application settings, loaded from environment variables / a .env file."""

import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


class Settings(BaseModel):
    app_name: str = "Morning Blick"
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = 8000
    nylas_api_key: str | None = None
    nylas_api_uri: str = "https://api.us.nylas.com"
    nylas_client_id: str | None = None
    nylas_grant_id: str | None = None
    email: str | None = None
    server_url: str | None = None
    nylas_webhook_secret: str | None = None
    app_base_url: str = "http://localhost:8000"


@lru_cache
def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "Morning Blick"),
        debug=os.getenv("DEBUG", "false").lower() in {"1", "true", "yes"},
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        nylas_api_key=os.getenv("NYLAS_API_KEY") or None,
        nylas_api_uri=os.getenv("NYLAS_API_URI") or "https://api.us.nylas.com",
        nylas_client_id=os.getenv("NYLAS_CLIENT_ID") or None,
        # Empty string in .env counts as "not set" so the OAuth flow is used.
        nylas_grant_id=os.getenv("NYLAS_GRANT_ID") or None,
        email=os.getenv("EMAIL") or None,
        server_url=os.getenv("SERVER_URL") or None,
        nylas_webhook_secret=os.getenv("NYLAS_WEBHOOK_SECRET") or None,
        app_base_url=(os.getenv("APP_BASE_URL") or "http://localhost:8000").rstrip("/"),
    )
