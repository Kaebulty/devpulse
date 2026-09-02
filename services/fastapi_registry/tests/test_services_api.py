"""Service registry CRUD behaviour."""

from httpx import AsyncClient

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
