import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)

from app.api.runs import router as runs_router
from app.core.config import settings


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, debug=settings.debug)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    # prefix="" because the router already carries /benchmark and /runs prefixes
    app.include_router(runs_router)

    return app


app = create_app()
