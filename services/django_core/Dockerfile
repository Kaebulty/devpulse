# syntax=docker/dockerfile:1
#
# Django gateway — multi-stage build.
# Build from the repository root, which is the context both services share:
#   docker build -f services/django_core/Dockerfile -t devpulse-django .

# ---------- builder ----------
# The uv image per handbook §3; uv is already on PATH at /usr/local/bin/uv.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_PYTHON_DOWNLOADS=0 \
    UV_LINK_MODE=copy

WORKDIR /app

# Dependencies first, as their own cached layer.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

# NOTE: no `collectstatic`. STATIC_ROOT is not configured in config/settings.py, so
# the command would fail, and with DEBUG=False Django does not serve static files
# anyway. This needs revisiting when the HTMX/Tailwind dashboard lands, which is
# where static handling actually becomes necessary.

# ---------- runtime ----------
# Same Debian release and Python minor as the builder, so the copied virtualenv
# lines up with the interpreter here.
FROM python:3.12-slim-bookworm

RUN useradd --create-home --uid 1000 devpulse

WORKDIR /app

COPY --from=builder --chown=devpulse:devpulse /app/.venv /app/.venv

COPY --chown=devpulse:devpulse services/__init__.py ./services/
COPY --chown=devpulse:devpulse services/django_core/ ./services/django_core/

# config.wsgi lives under services/django_core rather than the repo root, mirroring
# the `pythonpath` that pyproject.toml already sets for pytest.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/services/django_core \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER devpulse

EXPOSE 8000

# Migrations are NOT run here. Handbook §7 makes them a deliberate `make migrate`
# step, and an image that migrates on boot means every replica races to mutate the
# schema on deploy. Run them once, explicitly:
#   docker compose exec django python services/django_core/manage.py migrate

# Three workers is fine: unlike the FastAPI service, Django has no background loop,
# so there is nothing that must run exactly once.
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
