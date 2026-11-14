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
    nylas_grant_id: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "Morning Blick"),
        debug=os.getenv("DEBUG", "false").lower() in {"1", "true", "yes"},
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        nylas_api_key=os.getenv("NYLAS_API_KEY"),
        nylas_grant_id=os.getenv("NYLAS_GRANT_ID"),
    )
