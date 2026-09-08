"""Sync HTTP client for the internal trust boundary to services/fastapi_registry.

Django is WSGI, so this wraps httpx.Client, never AsyncClient, even though the FastAPI
side is async end-to-end — the two services don't share an event loop or a process.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

import httpx
from django.conf import settings


class Environment(StrEnum):
    """Mirrors services.fastapi_registry.schemas.Environment. Lowercase on the wire."""

    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"


class ServiceStatus(StrEnum):
    """Mirrors services.fastapi_registry.schemas.ServiceStatus. Uppercase on the wire."""

    UNKNOWN = "UNKNOWN"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"


@dataclass(frozen=True)
class Service:
    """A registered service, as returned by the FastAPI registry's ServiceRead."""

    id: int
    name: str
    environment: Environment
    health_check_url: str
    status: ServiceStatus
    latency_ms: int | None
    last_checked_at: datetime | None

    @classmethod
    def from_api(cls, data: dict) -> Service:
        last_checked_at = data.get("last_checked_at")
        return cls(
            id=data["id"],
            name=data["name"],
            environment=Environment(data["environment"]),
            health_check_url=data["health_check_url"],
            status=ServiceStatus(data["status"]),
            latency_ms=data.get("latency_ms"),
            last_checked_at=datetime.fromisoformat(last_checked_at) if last_checked_at else None,
        )


class RegistryClientError(Exception):
    """Base class for every error this client raises."""


class RegistryUnavailable(RegistryClientError):
    """The registry could not be reached, timed out, or returned a server error.

    Callers (views) should treat this as "show a degraded/offline state", not as a
    bug — FastAPI being briefly unreachable is an expected condition, not a crash.
    """


class RegistryAuthError(RegistryClientError):
    """The internal secret was rejected. A deployment misconfiguration, not transient."""


class ServiceNotFound(RegistryClientError):
    """No service exists with the given id."""


class DuplicateServiceName(RegistryClientError):
    """A service with this name is already registered.

    The registry enforces uniqueness itself (409), which is also why this client
    never blind-retries a POST: retrying a create on a network hiccup risks turning
    a real duplicate-name error into a swallowed one.
    """


class RegistryClient:
    """Client for the FastAPI service registry, across the X-Internal-Secret boundary."""

    def __init__(self, base_url: str | None = None, timeout: float = 5.0) -> None:
        self._base_url = (base_url or settings.FASTAPI_REGISTRY_URL).rstrip("/")
        self._timeout = timeout

    def list_services(self) -> list[Service]:
        response = self._send("GET", "/api/v1/services", expected={200})
        return [Service.from_api(item) for item in response.json()]

    def create_service(
        self, *, name: str, environment: Environment, health_check_url: str, auth_token: str
    ) -> Service:
        payload = {
            "name": name,
            "environment": environment.value,
            "health_check_url": health_check_url,
            "auth_token": auth_token,
        }
        response = self._send("POST", "/api/v1/services", json=payload, expected={201, 409})
        if response.status_code == 409:
            raise DuplicateServiceName(f"a service named {name!r} is already registered")
        return Service.from_api(response.json())

    def delete_service(self, service_id: int) -> None:
        response = self._send("DELETE", f"/api/v1/services/{service_id}", expected={204, 404})
        if response.status_code == 404:
            raise ServiceNotFound(f"no service with id {service_id}")

    def _send(
        self, method: str, path: str, *, expected: set[int], json: dict | None = None
    ) -> httpx.Response:
        """Send a request and enforce the boundary's universal error handling.

        `expected` are the status codes the calling method itself knows how to
        interpret (including its own "not found" / "conflict" cases) — anything
        else, including a 4xx this client wasn't told to expect, is a bug on one
        side of the boundary rather than a condition callers should branch on.
        """
        url = f"{self._base_url}{path}"
        headers = {"X-Internal-Secret": settings.INTERNAL_SECRET_TOKEN}
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.request(method, url, json=json, headers=headers)
        except httpx.TransportError as exc:
            raise RegistryUnavailable(f"{method} {path} failed: {exc}") from exc

        if response.status_code == 401:
            raise RegistryAuthError("registry rejected the internal secret")
        if response.status_code >= 500:
            raise RegistryUnavailable(f"registry returned {response.status_code}")
        if response.status_code not in expected:
            raise RegistryClientError(
                f"{method} {path} returned unexpected status {response.status_code}: "
                f"{response.text}"
            )
        return response
