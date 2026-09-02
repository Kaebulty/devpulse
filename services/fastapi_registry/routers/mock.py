"""Dynamic mock targets for offline testing of the health engine.

These endpoints impersonate an *external* service being monitored. They exist so the
whole Healthy / Degraded / Unhealthy cycle can be demonstrated and tested with no
network access and no third-party service that has to be conveniently broken
(handbook §4.3, hermetic local testing).

Deliberately NOT behind X-Internal-Secret: this is not part of the registry API, it is
a stand-in for a service the registry monitors. Handbook §4.5 has the real target
authenticating with `Authorization: Bearer <token>` against Django's vault; gating it
with the internal gateway secret instead would make the fault-simulation demo impossible.
"""

import asyncio

from fastapi import APIRouter, HTTPException, Query, Response, status

router = APIRouter(prefix="/mock", tags=["mock"])

# A caller could otherwise pin a worker for as long as it liked. This endpoint is
# reachable without credentials, so it needs its own ceiling.
MAX_DELAY_SECONDS = 30.0


@router.get(
    "/health",
    summary="Simulate a monitored service's health endpoint",
    responses={200: {"description": "Simulated healthy response"}},
)
async def mock_health(
    delay: float = Query(
        default=0.0,
        ge=0.0,
        le=MAX_DELAY_SECONDS,
        description="Seconds to wait before responding, to simulate latency.",
    ),
    status_code: int = Query(
        default=status.HTTP_200_OK,
        ge=100,
        le=599,
        alias="status",
        description="HTTP status code to return, to simulate failure.",
    ),
) -> Response:
    """Respond after `delay` seconds with `status`.

    The sleep is `asyncio.sleep`, not `time.sleep`: a blocking sleep would stall the
    entire event loop, so a single slow mock would freeze every other request the
    service is handling. Simulating latency without blocking is the whole point.
    """
    if delay:
        await asyncio.sleep(delay)

    if status_code >= 400:
        raise HTTPException(
            status_code=status_code,
            detail=f"Simulated failure with status {status_code}",
        )

    return Response(
        content=f'{{"status":"ok","simulated_delay":{delay}}}',
        media_type="application/json",
        status_code=status_code,
    )
