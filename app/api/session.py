"""Cookie-based, in-memory session middleware."""

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

SESSION_COOKIE = "session_id"
SESSION_MAX_AGE = 14 * 24 * 60 * 60  # 14 days in seconds

# In-memory store: session_id -> session dict. Fine for development only:
# it resets on every restart (and on --reload) and is not shared between workers.
SESSIONS: dict[str, dict] = {}


class SessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        session_id = request.cookies.get(SESSION_COOKIE)
        if not session_id or session_id not in SESSIONS:
            session_id = os.urandom(16).hex()
            SESSIONS[session_id] = {}
        request.state.session = SESSIONS[session_id]

        response = await call_next(request)
        response.set_cookie(
            SESSION_COOKIE,
            session_id,
            httponly=True,
            max_age=SESSION_MAX_AGE,
            samesite="lax",
            secure=False,
        )
        return response
