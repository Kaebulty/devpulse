"""DevPulse service registry application entry point.

Run locally from the repository root:
    uv run uvicorn services.fastapi_registry.main:app --reload --port 8001
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from services.fastapi_registry.config import get_settings
from services.fastapi_registry.health import health_check_loop
from services.fastapi_registry.routers import mock, services

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Own the background health check task for the lifetime of the application."""
    settings = get_settings()

    if not settings.health_check_enabled:
        logger.info("health check loop disabled by configuration")
        yield
        return

    task = asyncio.create_task(health_check_loop(), name="health-check-loop")
    try:
        yield
    finally:
        # Cancel and await it, otherwise shutdown races the task and Python prints a
        # "Task was destroyed but it is pending" warning on exit.
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        logger.info("health check loop stopped")


app = FastAPI(
    title="DevPulse Service Registry",
    description="Private microservice owning the service inventory and health data.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Liveness probe.

    Deliberately unauthenticated and free of database access: it answers
    "is this process up", which container orchestrators need before the
    database is necessarily reachable.
    """
    return {"status": "ok"}


# Registered under /api/v1; the router itself contributes the /services prefix.
app.include_router(services.router, prefix="/api/v1")

# Mounted at the root, not under /api/v1: the mock targets are not part of the
# registry API, they stand in for external services the registry monitors.
app.include_router(mock.router)
