"""Runtime configuration, read from the shared .env at the repo root.

The DSN is composed from the individual POSTGRES_* parts rather than stored as a
second, complete URL. Keeping one source of truth for the password avoids the two
copies drifting apart, and keeps the credential out of any tracked file.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root, resolved from this file rather than the working directory: Alembic is
# invoked from services/fastapi_registry (handbook §7) while Uvicorn is invoked from
# the root, and both must find the same .env.
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Settings for the FastAPI registry service."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        # The .env is shared with Django, so ignore variables that aren't ours.
        extra="ignore",
    )

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    services_db_name: str = "services_db"
    fastapi_db_user: str = "fastapi_user"
    fastapi_db_password: str

    # Shared secret proving an inbound request came from the Django gateway.
    internal_secret_token: str

    @property
    def database_url(self) -> str:
        """Async SQLAlchemy DSN for services_db."""
        return (
            f"postgresql+asyncpg://{self.fastapi_db_user}:{self.fastapi_db_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.services_db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    """Return the settings singleton.

    Cached so the .env is parsed once per process, and so tests can clear the cache
    to inject their own values.
    """
    return Settings()
