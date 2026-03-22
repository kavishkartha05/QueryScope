from fastapi import FastAPI

from app.api.runs import router as runs_router
from app.core.config import settings


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, debug=settings.debug)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    # prefix="" because the router already carries /benchmark and /runs prefixes
    app.include_router(runs_router)

    return app


app = create_app()
