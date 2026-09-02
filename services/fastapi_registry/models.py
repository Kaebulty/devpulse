"""SQLAlchemy models for services_db."""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from services.fastapi_registry.database import Base


class ServiceModel(Base):
    """A registered microservice in the DevPulse registry.

    `environment` and `status` are stored as plain strings rather than native
    Postgres ENUM types, and validated by the Pydantic schemas at the API edge.
    Altering a Postgres enum requires bespoke migration work, and the health
    engine adds status values later in the sprint; keeping the column a string
    keeps those migrations trivial.
    """

    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    environment: Mapped[str] = mapped_column(String(20))
    health_check_url: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="UNKNOWN", server_default="UNKNOWN")

    # Written by the background health engine. Both nullable: a service that has never
    # been checked is distinct from one checked and found unresponsive.
    latency_ms: Mapped[int | None] = mapped_column(default=None)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    def __repr__(self) -> str:
        return f"<ServiceModel id={self.id} name={self.name!r} status={self.status!r}>"
