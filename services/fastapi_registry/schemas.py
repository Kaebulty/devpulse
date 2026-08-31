"""Pydantic v2 schemas for request validation and response serialisation.

The enums live here rather than on the SQLAlchemy model deliberately: the database
stores plain strings, and validation happens at the API edge. That keeps migrations
free of Postgres ENUM alterations when new statuses are added.
"""

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


class ServiceRead(BaseModel):
    """A registered service as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    environment: Environment
    health_check_url: str
    status: ServiceStatus
