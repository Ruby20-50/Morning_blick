"""HTTP routes for the app."""

from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import Settings, get_settings
from app.services.briefing import build_briefing
from app.services.http import is_http_url

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
templates.env.tests["http_url"] = is_http_url


@router.get("/", response_class=HTMLResponse)
def index(request: Request, settings: Settings = Depends(get_settings)) -> HTMLResponse:
    # Same grant lookup as nylas_routes.get_grant_id, but optional: no grant just
    # makes the schedule card "unavailable".
    session = getattr(request.state, "session", None) or {}
    grant_id = settings.nylas_grant_id or session.get("grant_id")
    briefing = build_briefing(settings, grant_id=grant_id)
    return templates.TemplateResponse(request, "index.html", {"briefing": briefing})


@router.post("/ask")
async def ask(request: Request) -> dict[str, str]:
    # Parse the urlencoded form manually to avoid a python-multipart dependency.
    form = parse_qs((await request.body()).decode())
    question = form.get("question", [""])[0]
    return {"question": question, "answer": f"You asked: {question}"}


@router.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}

