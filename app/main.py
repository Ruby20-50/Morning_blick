"""Application entry point: builds the FastAPI app and runs it with uvicorn."""

import uvicorn
from fastapi import FastAPI

from app import __version__
from app.api.nylas_routes import router as nylas_router
from app.api.routes import router
from app.api.session import SessionMiddleware
from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title=settings.app_name, version=__version__, debug=settings.debug)
    application.add_middleware(SessionMiddleware)
    application.include_router(router)
    application.include_router(nylas_router)
    return application


app = create_app()


def main() -> None:
    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.debug)


if __name__ == "__main__":
    main()
