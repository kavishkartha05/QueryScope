import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

logging.basicConfig(level=logging.INFO)

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.config import router as config_router
from app.api.runs import admin_router as runs_admin_router
from app.api.runs import router as runs_router
from app.core.config import settings
from app.core.db import engine
from app.core.security import validate_auth_settings
from app.services.reaper import reap_stale_runs, reaper_loop


async def _probe_database() -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


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
    async def health():
        # Readiness, not just liveness: an orchestrator should stop sending
        # traffic to an instance that cannot reach its database. The response
        # says only that the database is down, never why (no hostnames or
        # driver errors in a public endpoint); the reason goes to the log.
        try:
            await asyncio.wait_for(_probe_database(), timeout=settings.health_db_timeout_s)
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "Health check: database unavailable (%s)", type(exc).__name__
            )
            return JSONResponse(
                status_code=503, content={"status": "unavailable", "database": "down"}
            )
        return {"status": "ok", "database": "ok"}

    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(config_router)
    app.include_router(runs_admin_router)
    # prefix="" because the router already carries /benchmark and /runs prefixes
    app.include_router(runs_router)

    return app


app = create_app()
