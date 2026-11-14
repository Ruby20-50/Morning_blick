"""Application entry point: builds the FastAPI app and runs it with uvicorn."""

import uvicorn
from fastapi import FastAPI

from app import __version__
from app.api.routes import router
from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title=settings.app_name, version=__version__, debug=settings.debug)
    application.include_router(router)
    return application


app = create_app()


def main() -> None:
    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.debug)


if __name__ == "__main__":
    main()
