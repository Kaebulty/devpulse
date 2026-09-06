# syntax=docker/dockerfile:1
#
# FastAPI service registry — multi-stage build.
# Build from the repository root, which is the context both services share:
#   docker build -f services/fastapi_registry/Dockerfile -t devpulse-fastapi .

# ---------- builder ----------
# The uv image per handbook §3; uv is already on PATH at /usr/local/bin/uv.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

# Use the image's own Python rather than letting uv download one, and copy rather
# than hardlink (the cache mount is a different filesystem to /app).
ENV UV_PYTHON_DOWNLOADS=0 \
    UV_LINK_MODE=copy

WORKDIR /app

# Dependencies as their own layer. This is the slow step, and it is invalidated only
# when uv.lock or pyproject.toml change — not on every source edit. Bind-mounting
# them keeps them out of the layer itself.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

# The uv_build backend builds the root `devpulse` package from src/, and reads
# README.md because pyproject declares it.
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

# ---------- runtime ----------
# Same Debian release and Python minor as the builder, so the copied virtualenv
# lines up with the interpreter here.
FROM python:3.12-slim-bookworm

# Unprivileged: a container process that does not need root should not have it.
RUN useradd --create-home --uid 1000 devpulse

WORKDIR /app

# Only the virtualenv crosses over — no uv, no build tooling, no dev dependencies.
COPY --from=builder --chown=devpulse:devpulse /app/.venv /app/.venv

# `services` is imported from the working directory rather than installed, so the
# tree has to be present. Only this service's code is copied.
COPY --chown=devpulse:devpulse services/__init__.py ./services/
COPY --chown=devpulse:devpulse services/fastapi_registry/ ./services/fastapi_registry/

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER devpulse

EXPOSE 8001

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=2).status == 200 else 1)"

# --workers 1 is deliberate, not a default. The background health check loop runs
# once per worker (see services/fastapi_registry/health.py), so more than one worker
# means duplicate pings and racing writes to the same rows. Scaling out would need a
# Postgres advisory lock so only one worker runs a cycle.
CMD ["uvicorn", "services.fastapi_registry.main:app", \
     "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
