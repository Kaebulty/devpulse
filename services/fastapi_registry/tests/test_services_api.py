"""Service registry CRUD behaviour."""

from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from services.fastapi_registry.models import ServiceModel
from services.fastapi_registry.schemas import ServiceStatus

PAYLOAD = {
    "name": "payments-api",
    "environment": "production",
    "health_check_url": "http://localhost:8001/mock/health",
}


async def test_list_is_empty_initially(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.get("/api/v1/services", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []


async def test_create_then_list_round_trip(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await client.post("/api/v1/services", json=PAYLOAD, headers=auth_headers)
    assert created.status_code == 201

    body = created.json()
    assert body["name"] == "payments-api"
    assert body["environment"] == "production"
    assert body["id"] > 0
    # Status is owned by the health engine, not the caller.
    assert body["status"] == "UNKNOWN"

    listed = await client.get("/api/v1/services", headers=auth_headers)
    assert [s["name"] for s in listed.json()] == ["payments-api"]


async def test_duplicate_name_conflicts(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await client.post("/api/v1/services", json=PAYLOAD, headers=auth_headers)
    duplicate = await client.post("/api/v1/services", json=PAYLOAD, headers=auth_headers)
    assert duplicate.status_code == 409


async def test_invalid_environment_is_rejected(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    payload = PAYLOAD | {"environment": "not-a-real-environment"}
    response = await client.post("/api/v1/services", json=payload, headers=auth_headers)
    assert response.status_code == 422


async def test_invalid_url_is_rejected(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    payload = PAYLOAD | {"health_check_url": "not-a-url"}
    response = await client.post("/api/v1/services", json=payload, headers=auth_headers)
    assert response.status_code == 422


async def test_delete_removes_the_service(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await client.post("/api/v1/services", json=PAYLOAD, headers=auth_headers)
    service_id = created.json()["id"]

    deleted = await client.delete(f"/api/v1/services/{service_id}", headers=auth_headers)
    assert deleted.status_code == 204

    listed = await client.get("/api/v1/services", headers=auth_headers)
    assert listed.json() == []


async def test_delete_unknown_id_is_not_found(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.delete("/api/v1/services/9999", headers=auth_headers)
    assert response.status_code == 404


async def test_create_after_conflict_still_works(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """A rolled-back conflict must not poison the session for later writes."""
    await client.post("/api/v1/services", json=PAYLOAD, headers=auth_headers)
    await client.post("/api/v1/services", json=PAYLOAD, headers=auth_headers)  # 409

    other = await client.post(
        "/api/v1/services", json=PAYLOAD | {"name": "billing-api"}, headers=auth_headers
    )
    assert other.status_code == 201


async def test_new_service_reports_no_health_data_yet(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Before the engine has run, health fields are explicitly null rather than absent."""
    created = await client.post("/api/v1/services", json=PAYLOAD, headers=auth_headers)
    body = created.json()

    assert body["latency_ms"] is None
    assert body["last_checked_at"] is None


async def test_api_exposes_health_data_written_by_the_engine(
    client: AsyncClient, auth_headers: dict[str, str], session: AsyncSession
) -> None:
    """Regression: the engine's results must reach the API response.

    The columns were added with the health engine but left out of ServiceRead, so
    latency sat in the database and never crossed the API boundary — invisible to
    the gateway and therefore to the dashboard's latency badge (handbook §4.4).

    Asserts on the serialised response, not the ORM object: the original tests
    checked stored state, which is exactly why they missed this.
    """
    created = await client.post("/api/v1/services", json=PAYLOAD, headers=auth_headers)
    service_id = created.json()["id"]

    stored = await session.get(ServiceModel, service_id)
    stored.status = ServiceStatus.DEGRADED.value
    stored.latency_ms = 1208
    stored.last_checked_at = datetime(2026, 9, 2, 12, 30, tzinfo=UTC)
    await session.commit()

    listed = await client.get("/api/v1/services", headers=auth_headers)
    body = listed.json()[0]

    assert body["status"] == "DEGRADED"
    assert body["latency_ms"] == 1208
    assert body["last_checked_at"].startswith("2026-09-02T12:30")
