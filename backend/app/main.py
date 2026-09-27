"""Launch from the repository root: python -m uvicorn backend.app.main:app."""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.config import get_settings
from backend.app.database import close_mongo_client
from backend.app.api import router as api_router
from backend.app.repository import clear_repository_cache
from backend.app.data_routes import router as data_router
from backend.app.integrations.relay_routes import router as relay_integration_router
from backend.app.calls.repository import clear_call_repository_cache
from backend.app.calls.routes import router as call_router
from relay_gateway.api import app as relay_app
from relay_gateway.fleet_gateway import create_app as create_fleet_app


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
        close_mongo_client()
        clear_repository_cache()
        clear_call_repository_cache()


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="Grid Hazard Rover API",
        description="Utility coordination and infrastructure hazard analysis API.",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization"],
    )
    application.include_router(api_router)
    application.include_router(data_router)
    application.include_router(relay_integration_router)
    application.include_router(call_router)

    # Relay keeps its own API, models, static dashboard, telemetry cache, and
    # runtime state. Namespaced mounts avoid route collisions while providing
    # one demo-friendly process. Put the more-specific fleet mount first.
    application.mount("/relay/fleet", create_fleet_app(), name="relay-fleet")
    application.mount("/relay", relay_app, name="relay")

    @application.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        """Process liveness only; deliberately independent of MongoDB."""
        return {"status": "ok"}

    return application


app = create_app()
