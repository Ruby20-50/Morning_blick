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
    timezone: str = "Europe/Berlin"
    # Morning briefing providers
    http_timeout: float = 5.0  # per HTTP request, seconds
    provider_timeout: float = 8.0  # per provider (may include several requests), seconds
    weather_latitude: float = 52.52  # Berlin
    weather_longitude: float = 13.41
    weather_timezone: str = "Europe/Berlin"
    cache_ttl_weather: int = 900  # seconds
    hn_story_count: int = 5
    cache_ttl_hn: int = 600
    vbb_stop_id: str = "900100003"  # S+U Alexanderplatz Bhf (Berlin)
    vbb_duration_minutes: int = 30  # look-ahead window for departures
    vbb_min_delay_minutes: int = 3  # smaller delays are not shown
    cache_ttl_vbb: int = 60
    cache_ttl_nylas: int = 60


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
        timezone=os.getenv("TIMEZONE") or "Europe/Berlin",
        http_timeout=float(os.getenv("HTTP_TIMEOUT") or 5.0),
        provider_timeout=float(os.getenv("PROVIDER_TIMEOUT") or 8.0),
        weather_latitude=float(os.getenv("WEATHER_LATITUDE") or 52.52),
        weather_longitude=float(os.getenv("WEATHER_LONGITUDE") or 13.41),
        weather_timezone=os.getenv("WEATHER_TIMEZONE") or "Europe/Berlin",
        cache_ttl_weather=int(os.getenv("CACHE_TTL_WEATHER") or 900),
        hn_story_count=int(os.getenv("HN_STORY_COUNT") or 5),
        cache_ttl_hn=int(os.getenv("CACHE_TTL_HN") or 600),
        vbb_stop_id=os.getenv("VBB_STOP_ID") or "900100003",
        vbb_duration_minutes=int(os.getenv("VBB_DURATION_MINUTES") or 30),
        vbb_min_delay_minutes=int(os.getenv("VBB_MIN_DELAY_MINUTES") or 3),
        cache_ttl_vbb=int(os.getenv("CACHE_TTL_VBB") or 60),
        cache_ttl_nylas=int(os.getenv("CACHE_TTL_NYLAS") or 60),
    )
