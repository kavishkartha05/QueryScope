import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.runs import admin_router as runs_admin_router
from app.api.runs import router as runs_router
from app.core.config import settings
from app.core.security import validate_auth_settings


def create_app() -> FastAPI:
    # Refuse to start with the gate enabled but unkeyed.
    validate_auth_settings()
    if not settings.auth_enabled:
        logging.getLogger(__name__).warning(
            "AUTH_ENABLED is false: all routes are open. Local development only."
        )

    app = FastAPI(title=settings.app_name, debug=settings.debug)

    # Auth uses a Bearer header, not cookies, so credentials are not needed and
    # stay off. Origins must be an explicit list (never "*") in production.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(runs_admin_router)
    # prefix="" because the router already carries /benchmark and /runs prefixes
    app.include_router(runs_router)

    return app


app = create_app()
