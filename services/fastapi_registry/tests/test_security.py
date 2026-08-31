"""The internal trust boundary."""

import pytest
from httpx import AsyncClient

from services.fastapi_registry.tests.conftest import TEST_SECRET


async def test_request_without_header_is_rejected(client: AsyncClient) -> None:
    response = await client.get("/api/v1/services")
    assert response.status_code == 401


async def test_request_with_wrong_secret_is_rejected(client: AsyncClient) -> None:
    response = await client.get("/api/v1/services", headers={"X-Internal-Secret": "wrong"})
    assert response.status_code == 401


async def test_error_does_not_reveal_which_part_was_wrong(client: AsyncClient) -> None:
    """Missing and incorrect must be indistinguishable to the caller."""
    missing = await client.get("/api/v1/services")
    wrong = await client.get("/api/v1/services", headers={"X-Internal-Secret": "wrong"})
    assert missing.json() == wrong.json()


async def test_request_with_valid_secret_is_accepted(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/services", headers=auth_headers)
    assert response.status_code == 200


@pytest.mark.parametrize("path", ["/health", "/docs", "/openapi.json"])
async def test_public_endpoints_are_not_gated(client: AsyncClient, path: str) -> None:
    """Health and docs must stay reachable without the internal secret.

    Guards the choice of a router-level dependency over global middleware: the
    mock target endpoints added later authenticate differently and must not be
    caught by this header check.
    """
    response = await client.get(path)
    assert response.status_code == 200


async def test_secret_is_compared_in_constant_time() -> None:
    """A near-miss must be rejected the same way as a wholly wrong value.

    Weak assertion by nature — it documents intent and fails loudly if someone
    swaps compare_digest for ==, which would leak the secret byte by byte.
    """
    import inspect

    from services.fastapi_registry import security

    source = inspect.getsource(security.verify_internal_secret)
    assert "compare_digest" in source
    assert TEST_SECRET  # fixture sanity
