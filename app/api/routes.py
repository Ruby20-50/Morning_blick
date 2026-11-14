"""HTTP routes for the app."""

from datetime import date
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import Settings, get_settings
from app.schemas import CalculationRequest, CalculationResponse, Operation
from app.services.calculator import OPERATIONS

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    # Placeholder data for milestone 1; real sources come later.
    context = {
        "today": date.today().strftime("%A, %d %B %Y"),
        "weather": ["8 °C, light clouds", "Rain expected after 16:00"],
        "tasks": ["Review lecture notes", "Push milestone 1"],
        "updates": ["S-Bahn Ring: delays between Ostkreuz and Treptower Park this morning."],
        "news": [],
    }
    return templates.TemplateResponse(request, "index.html", context)


@router.post("/ask")
async def ask(request: Request) -> dict[str, str]:
    # Parse the urlencoded form manually to avoid a python-multipart dependency.
    form = parse_qs((await request.body()).decode())
    question = form.get("question", [""])[0]
    return {"question": question, "answer": f"You asked: {question}"}


@router.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}


@router.post("/calculate/{operation}", response_model=CalculationResponse)
def calculate(operation: Operation, payload: CalculationRequest) -> CalculationResponse:
    result = OPERATIONS[operation](payload.a, payload.b)
    return CalculationResponse(operation=operation, a=payload.a, b=payload.b, result=result)
