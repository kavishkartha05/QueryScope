import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.runs import admin_router as runs_admin_router
from app.api.runs import router as runs_router
from app.core.config import settings
from app.core.security import validate_auth_settings
from app.services.reaper import reap_stale_runs, reaper_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs that were mid-flight when the previous process stopped will never be
    # finished by anyone: fail them now, then keep checking while we run.
    try:
        await reap_stale_runs()
    except Exception as exc:
        # The database may not be reachable yet; the periodic pass retries.
        logging.getLogger(__name__).warning("Startup reaper pass failed: %s", exc)
    task = asyncio.create_task(reaper_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def create_app() -> FastAPI:
    # Refuse to start with the gate enabled but unkeyed.
    validate_auth_settings()
    if not settings.auth_enabled:
        logging.getLogger(__name__).warning(
            "AUTH_ENABLED is false: all routes are open. Local development only."
        )

    app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

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
