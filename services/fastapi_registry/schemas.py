"""Pydantic v2 schemas for request validation and response serialisation.

The enums live here rather than on the SQLAlchemy model deliberately: the database
stores plain strings, and validation happens at the API edge. That keeps migrations
free of Postgres ENUM alterations when new statuses are added.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class Environment(StrEnum):
    """Deployment environment a registered service runs in."""

    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"


class ServiceStatus(StrEnum):
    """Health state, as evaluated by the background health engine."""

    UNKNOWN = "UNKNOWN"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"


class ServiceCreate(BaseModel):
    """Payload for registering a service.

    `status` is intentionally absent: it is owned by the health engine, not the
    caller. A newly registered service starts UNKNOWN until first checked.
    """

    name: str = Field(min_length=1, max_length=100, examples=["payments-api"])
    environment: Environment
    health_check_url: HttpUrl = Field(examples=["http://localhost:8001/mock/health"])
    # Optional: a service can be registered without vault security (e.g. local/manual
    # testing). Deliberately absent from ServiceRead — write-only, never echoed back.
    auth_token: str | None = None


class ServiceUpdate(BaseModel):
    """Partial update of a registered service.

    Every field is optional, and absent is not the same as null: a field omitted
    from the request body is left untouched, while an explicit null clears it.
    Callers rely on `model_dump(exclude_unset=True)` to tell the two apart — which
    is the whole reason this is a PATCH rather than a PUT.
    """

    # Rotated by the vault. Write-only, exactly as on ServiceCreate.
    auth_token: str | None = None
    # Set to a mock target by Chaos Controls; null clears the simulation.
    simulation_url: HttpUrl | None = None


class ServiceRead(BaseModel):
    """A registered service as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    environment: Environment
    health_check_url: str
    status: ServiceStatus

    # Written by the background health engine. Null until the first check runs.
    # The dashboard renders these as a latency badge (handbook §4.4), so they have
    # to cross the API boundary — the gateway has no other route to them.
    latency_ms: int | None = None
    last_checked_at: datetime | None = None

    # Exposed so the dashboard can mark a service as currently simulated.
    # auth_token deliberately is not — that stays write-only.
    simulation_url: str | None = None
