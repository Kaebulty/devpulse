"""DevPulse service registry application entry point.

Run locally from the repository root:
    uv run uvicorn services.fastapi_registry.main:app --reload --port 8001
"""

from fastapi import FastAPI

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
