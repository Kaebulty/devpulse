"""Shared fixtures.

The suite runs against SQLite in-memory rather than Postgres so it needs no
container and stays fast in CI. The models use no Postgres-specific types, so the
schema is portable; anything that later depends on Postgres behaviour belongs in a
separate integration suite.
"""

import os
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_SECRET = "test-internal-secret"

# Settings are read at import time, so the environment must be primed before any
# application module loads.
os.environ.setdefault("FASTAPI_DB_PASSWORD", "test-password")
os.environ.setdefault("INTERNAL_SECRET_TOKEN", TEST_SECRET)

from services.fastapi_registry.config import get_settings  # noqa: E402
from services.fastapi_registry.database import Base, get_session  # noqa: E402
from services.fastapi_registry.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _override_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the internal secret regardless of the developer's local .env."""
    monkeypatch.setenv("INTERNAL_SECRET_TOKEN", TEST_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    """A session backed by a fresh in-memory database per test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s

    await engine.dispose()


@pytest.fixture
async def client(session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """An HTTP client wired to the app, with the database dependency overridden."""

    async def _get_session() -> AsyncGenerator[AsyncSession, None]:
        yield session

    app.dependency_overrides[get_session] = _get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Headers carrying a valid internal secret."""
    return {"X-Internal-Secret": TEST_SECRET}
