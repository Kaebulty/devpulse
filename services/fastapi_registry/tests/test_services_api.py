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


async def test_auth_token_is_accepted_but_never_returned(
    client: AsyncClient, auth_headers: dict[str, str], session: AsyncSession
) -> None:
    """The vault token is write-only: stored for the health engine, never echoed back.

    Regression: ServiceCreate previously had no `auth_token` field at all, so Pydantic
    silently dropped it — every service's health ping went out with no bearer token
    regardless of what Django sent.
    """
    payload = PAYLOAD | {"auth_token": "s3cr3t-token"}
    created = await client.post("/api/v1/services", json=payload, headers=auth_headers)
    assert created.status_code == 201
    assert "auth_token" not in created.json()

    stored = await session.get(ServiceModel, created.json()["id"])
    assert stored.auth_token == "s3cr3t-token"


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


# --- PATCH: partial update -------------------------------------------------------


async def _create(client: AsyncClient, headers: dict[str, str]) -> int:
    response = await client.post("/api/v1/services", json=PAYLOAD, headers=headers)
    return response.json()["id"]


async def test_patch_sets_simulation_url(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    service_id = await _create(client, auth_headers)

    response = await client.patch(
        f"/api/v1/services/{service_id}",
        json={"simulation_url": "http://localhost:8001/mock/health?status=503"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["simulation_url"] == "http://localhost:8001/mock/health?status=503"


async def test_patch_clears_simulation_url_with_explicit_null(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    service_id = await _create(client, auth_headers)
    await client.patch(
        f"/api/v1/services/{service_id}",
        json={"simulation_url": "http://localhost:8001/mock/health?status=503"},
        headers=auth_headers,
    )

    response = await client.patch(
        f"/api/v1/services/{service_id}", json={"simulation_url": None}, headers=auth_headers
    )

    assert response.json()["simulation_url"] is None


async def test_patch_leaves_omitted_fields_untouched(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Absent is not null — the whole reason this is a PATCH and not a PUT.

    Rotating a token must not silently wipe an active simulation, and setting a
    simulation must not wipe the token. Both are one `exclude_unset` away from
    being wrong, and neither would be noticed until a demo.
    """
    service_id = await _create(client, auth_headers)
    await client.patch(
        f"/api/v1/services/{service_id}",
        json={"simulation_url": "http://localhost:8001/mock/health?delay=2"},
        headers=auth_headers,
    )

    # Touch only auth_token; the simulation must survive.
    response = await client.patch(
        f"/api/v1/services/{service_id}", json={"auth_token": "rotated"}, headers=auth_headers
    )

    assert response.json()["simulation_url"] == "http://localhost:8001/mock/health?delay=2"


async def test_patch_never_returns_the_auth_token(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    service_id = await _create(client, auth_headers)

    response = await client.patch(
        f"/api/v1/services/{service_id}", json={"auth_token": "s3cr3t"}, headers=auth_headers
    )

    assert "auth_token" not in response.json()
    assert "s3cr3t" not in response.text


async def test_patch_unknown_id_is_not_found(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.patch(
        "/api/v1/services/9999", json={"auth_token": "x"}, headers=auth_headers
    )
    assert response.status_code == 404


async def test_patch_requires_the_internal_secret(client: AsyncClient) -> None:
    response = await client.patch("/api/v1/services/1", json={"auth_token": "x"})
    assert response.status_code == 401
