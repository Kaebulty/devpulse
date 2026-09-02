"""Dynamic mock target endpoints."""

import time

import pytest
from httpx import AsyncClient


async def test_defaults_to_immediate_ok(client: AsyncClient) -> None:
    response = await client.get("/mock/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_is_reachable_without_the_internal_secret(client: AsyncClient) -> None:
    """The mock stands in for an external service, so the gateway secret must not gate it.

    If this ever fails, the fault-simulation demo is broken: the health engine would be
    unable to reach its own test target.
    """
    response = await client.get("/mock/health")
    assert response.status_code != 401


@pytest.mark.parametrize("code", [200, 204, 301, 404, 500, 503])
async def test_returns_the_requested_status(client: AsyncClient, code: int) -> None:
    response = await client.get("/mock/health", params={"status": code})
    assert response.status_code == code


async def test_delay_actually_delays(client: AsyncClient) -> None:
    start = time.perf_counter()
    response = await client.get("/mock/health", params={"delay": 0.25})
    elapsed = time.perf_counter() - start

    assert response.status_code == 200
    assert elapsed >= 0.25


async def test_delay_does_not_block_the_event_loop(client: AsyncClient) -> None:
    """Two concurrent slow requests should overlap, not queue.

    This is what distinguishes `await asyncio.sleep` from `time.sleep`: with a blocking
    sleep the two would run back to back and take twice as long.
    """
    import asyncio

    start = time.perf_counter()
    await asyncio.gather(
        client.get("/mock/health", params={"delay": 0.3}),
        client.get("/mock/health", params={"delay": 0.3}),
    )
    elapsed = time.perf_counter() - start

    assert elapsed < 0.55, f"requests appear to have serialised ({elapsed:.2f}s)"


@pytest.mark.parametrize(
    ("params", "reason"),
    [
        ({"delay": -1}, "negative delay"),
        ({"delay": 31}, "delay above the 30s ceiling"),
        ({"status": 99}, "status below 100"),
        ({"status": 600}, "status above 599"),
    ],
)
async def test_out_of_range_parameters_are_rejected(
    client: AsyncClient, params: dict[str, object], reason: str
) -> None:
    response = await client.get("/mock/health", params=params)
    assert response.status_code == 422, reason
