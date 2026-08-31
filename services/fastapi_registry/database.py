"""Async SQLAlchemy 2.0 engine, session factory, and declarative base."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from services.fastapi_registry.config import get_settings


class Base(DeclarativeBase):
    """Declarative base. Alembic autogenerate reads Base.metadata."""


engine = create_async_engine(
    get_settings().database_url,
    echo=False,
    pool_pre_ping=True,
)

# expire_on_commit=False so response serialisation can still read attributes
# after the session commits, without triggering a second round trip.
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a session that is always closed."""
    async with SessionLocal() as session:
        yield session
