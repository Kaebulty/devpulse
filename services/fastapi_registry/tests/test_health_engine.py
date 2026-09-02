"""Background health check engine."""

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.fastapi_registry.health import check_service, evaluate_status, run_health_checks
from services.fastapi_registry.models import ServiceModel
from services.fastapi_registry.schemas import ServiceStatus

# --- evaluate_status: pure, so the boundaries get tested exhaustively -------------


@pytest.mark.parametrize(
    ("latency_ms", "status_code", "expected"),
    [
        # Healthy: 2xx and comfortably under the degraded threshold.
        (0, 200, ServiceStatus.HEALTHY),
        (499, 200, ServiceStatus.HEALTHY),
        (499, 204, ServiceStatus.HEALTHY),
        # Exactly at the degraded threshold tips over — the boundary is inclusive.
        (500, 200, ServiceStatus.DEGRADED),
        (1999, 200, ServiceStatus.DEGRADED),
        # Exactly at the unhealthy threshold likewise.
        (2000, 200, ServiceStatus.UNHEALTHY),
        (9999, 200, ServiceStatus.UNHEALTHY),
        # Non-2xx is unhealthy no matter how fast it answered.
        (1, 301, ServiceStatus.UNHEALTHY),
        (1, 404, ServiceStatus.UNHEALTHY),
        (1, 500, ServiceStatus.UNHEALTHY),
        (1, 503, ServiceStatus.UNHEALTHY),
        # 401 is the revocation case from handbook §4.5.
        (1, 401, ServiceStatus.UNHEALTHY),
        # No response at all: timeout, refused, DNS failure.
        (5000, None, ServiceStatus.UNHEALTHY),
        (1, None, ServiceStatus.UNHEALTHY),
    ],
)
def test_evaluate_status_boundaries(
    latency_ms: int, status_code: int | None, expected: ServiceStatus
) -> None:
    assert evaluate_status(latency_ms, status_code) is expected


# --- check_service: one ping, never raises ----------------------------------------


@respx.mock
async def test_check_service_healthy() -> None:
    respx.get("http://svc/health").mock(return_value=httpx.Response(200))
    service = ServiceModel(id=1, name="svc", environment="development",
                           health_check_url="http://svc/health")

    async with httpx.AsyncClient() as client:
        result = await check_service(client, service)

    assert result.status is ServiceStatus.HEALTHY
    assert result.service_id == 1
    assert result.checked_at.tzinfo is not None


@respx.mock
async def test_check_service_maps_500_to_unhealthy() -> None:
    respx.get("http://svc/health").mock(return_value=httpx.Response(500))
    service = ServiceModel(id=1, name="svc", environment="development",
                           health_check_url="http://svc/health")

    async with httpx.AsyncClient() as client:
        result = await check_service(client, service)

    assert result.status is ServiceStatus.UNHEALTHY


@respx.mock
async def test_check_service_swallows_transport_errors() -> None:
    """A connection failure is a verdict about the service, not an engine error."""
    respx.get("http://svc/health").mock(side_effect=httpx.ConnectError("refused"))
    service = ServiceModel(id=1, name="svc", environment="development",
                           health_check_url="http://svc/health")

    async with httpx.AsyncClient() as client:
        result = await check_service(client, service)  # must not raise

    assert result.status is ServiceStatus.UNHEALTHY


# --- run_health_checks: full cycle, persistence -----------------------------------


@respx.mock
async def test_cycle_persists_status_and_latency(session: AsyncSession) -> None:
    respx.get("http://ok/health").mock(return_value=httpx.Response(200))
    session.add(ServiceModel(name="ok", environment="development",
                             health_check_url="http://ok/health"))
    await session.commit()

    results = await run_health_checks(session)
    assert len(results) == 1

    stored = (await session.execute(select(ServiceModel))).scalars().one()
    assert stored.status == ServiceStatus.HEALTHY.value
    assert stored.latency_ms is not None
    assert stored.last_checked_at is not None


@respx.mock
async def test_one_failing_service_does_not_stop_the_others(session: AsyncSession) -> None:
    """The return_exceptions=True guarantee.

    Without it, a single failure cancels every sibling coroutine and the whole cycle
    is lost — one broken service would halt monitoring for all of them.
    """
    respx.get("http://good/health").mock(return_value=httpx.Response(200))
    respx.get("http://bad/health").mock(side_effect=httpx.ConnectError("refused"))

    session.add_all([
        ServiceModel(name="good", environment="development", health_check_url="http://good/health"),
        ServiceModel(name="bad", environment="development", health_check_url="http://bad/health"),
    ])
    await session.commit()

    results = await run_health_checks(session)
    assert len(results) == 2

    rows = (await session.execute(select(ServiceModel).order_by(ServiceModel.name))).scalars().all()
    statuses = {r.name: r.status for r in rows}
    assert statuses == {
        "good": ServiceStatus.HEALTHY.value,
        "bad": ServiceStatus.UNHEALTHY.value,
    }


async def test_empty_registry_is_a_no_op(session: AsyncSession) -> None:
    assert await run_health_checks(session) == []
