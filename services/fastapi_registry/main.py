"""DevPulse service registry application entry point.

Run locally from the repository root:
    uv run uvicorn services.fastapi_registry.main:app --reload --port 8001
"""

from fastapi import FastAPI

from services.fastapi_registry.routers import mock, services

app = FastAPI(
    title="DevPulse Service Registry",
    description="Private microservice owning the service inventory and health data.",
    version="0.1.0",
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
