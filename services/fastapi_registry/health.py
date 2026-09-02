"""Background health check engine.

Decoupled by design (handbook §4.2): this loop pings every registered service on an
interval and writes the verdict to services_db. The API then answers queries straight
from that table rather than pinging on demand, so a page load never waits on a
third-party service — and one dead target cannot stall the dashboard.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.fastapi_registry.config import get_settings
from services.fastapi_registry.database import SessionLocal
from services.fastapi_registry.models import ServiceModel
from services.fastapi_registry.schemas import ServiceStatus

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CheckResult:
    """Outcome of pinging a single service."""

    service_id: int
    status: ServiceStatus
    latency_ms: int
    checked_at: datetime


def evaluate_status(latency_ms: int, status_code: int | None) -> ServiceStatus:
    """Classify one probe result.

    Pure and side-effect free on purpose: all the branching lives here, so every
    boundary can be tested without a network, a database, or a clock.

    `status_code=None` means the request never completed — timeout, DNS failure,
    connection refused. That is unhealthy regardless of how fast it failed.
    """
    settings = get_settings()

    if status_code is None or not (200 <= status_code < 300):
        return ServiceStatus.UNHEALTHY
    if latency_ms >= settings.health_unhealthy_threshold_ms:
        return ServiceStatus.UNHEALTHY
    if latency_ms >= settings.health_degraded_threshold_ms:
        return ServiceStatus.DEGRADED
    return ServiceStatus.HEALTHY


async def check_service(client: httpx.AsyncClient, service: ServiceModel) -> CheckResult:
    """Ping one service and classify the response.

    Never raises: any transport failure is a verdict about the service, not an error in
    the engine. Letting it propagate would take down the whole cycle.
    """
    # Where the vault token goes once Django's /api/v1/vault/verify/ exists
    # (handbook §4.5): the target verifies this bearer against Django, and revoking
    # the key flips the service to UNHEALTHY via a 401. Empty until that ticket lands.
    headers: dict[str, str] = {}

    # perf_counter is monotonic. Wall-clock time can step backwards under an NTP
    # correction, which would produce negative latencies.
    started = time.perf_counter()
    status_code: int | None = None
    try:
        response = await client.get(service.health_check_url, headers=headers)
        status_code = response.status_code
    except httpx.HTTPError as exc:
        logger.warning("health check failed for %s: %s", service.name, exc)
    except TimeoutError:
        logger.warning("health check timed out for %s", service.name)

    latency_ms = int((time.perf_counter() - started) * 1000)

    return CheckResult(
        service_id=service.id,
        status=evaluate_status(latency_ms, status_code),
        latency_ms=latency_ms,
        checked_at=datetime.now(UTC),
    )


async def run_health_checks(session: AsyncSession) -> list[CheckResult]:
    """Run one full cycle: ping every service concurrently, then persist the verdicts."""
    settings = get_settings()

    services = list((await session.execute(select(ServiceModel))).scalars().all())
    if not services:
        return []

    async with httpx.AsyncClient(
        timeout=settings.health_check_timeout_seconds,
        follow_redirects=False,
    ) as client:
        # return_exceptions=True is load-bearing. Without it, a single unexpected
        # exception cancels every sibling coroutine and the entire cycle is lost —
        # one broken service would stop monitoring for all of them.
        outcomes = await asyncio.gather(
            *(check_service(client, s) for s in services),
            return_exceptions=True,
        )

    results: list[CheckResult] = []
    by_id = {s.id: s for s in services}
    for outcome in outcomes:
        if isinstance(outcome, BaseException):
            logger.exception("unexpected error during health check", exc_info=outcome)
            continue
        service = by_id[outcome.service_id]
        service.status = outcome.status.value
        service.latency_ms = outcome.latency_ms
        service.last_checked_at = outcome.checked_at
        results.append(outcome)

    await session.commit()
    return results


async def health_check_loop() -> None:
    """Run a cycle every interval, forever, until cancelled.

    NOTE: this runs once per Uvicorn worker. With more than one worker that means
    duplicate pings and racing writes, so the service is pinned to a single worker
    (see the Dockerfile). A Postgres advisory lock would be the fix if it ever needs
    to scale horizontally.
    """
    interval = get_settings().health_check_interval_seconds
    logger.info("health check loop started, interval=%ss", interval)

    while True:
        try:
            async with SessionLocal() as session:
                results = await run_health_checks(session)
            logger.info("health check cycle complete, %d service(s) checked", len(results))
        except asyncio.CancelledError:
            logger.info("health check loop stopping")
            raise
        except Exception:
            # An unhandled exception inside a bare asyncio.Task kills the task
            # silently: monitoring would simply stop with nothing in the logs.
            logger.exception("health check cycle failed, continuing")

        await asyncio.sleep(interval)
