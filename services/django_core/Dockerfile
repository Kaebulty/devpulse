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

# App source is needed from here on: Tailwind's `@source` scans apps/**/templates
# for class names, and collectstatic's app-directories finder needs apps/*/static/.
COPY services/__init__.py ./services/
COPY services/django_core/ ./services/django_core/

# Compile Tailwind CSS with the same pinned, checksum-verified standalone CLI make
# uses locally — no Node/npm in the image. Verified against sha256sums.txt from the
# same GitHub release, same as the Makefile's local download.
#
# Two things this image's base doesn't give us, that the Makefile's host download
# didn't need to worry about: no curl/wget in this slim image (Python is already
# guaranteed present, so urllib does the fetch instead), and a build running on an
# arm64 host (e.g. Apple Silicon) needs the arm64 asset — TARGETARCH is set
# automatically by BuildKit and was previously ignored, so every build silently
# fetched the x64 binary regardless of the actual target platform. CI never caught
# this because GitHub's hosted runners are x64, where the hardcoded value happened
# to be correct by coincidence.
ARG TAILWIND_VERSION=v4.3.3
ARG TARGETARCH
RUN set -eu; \
    case "${TARGETARCH}" in \
      amd64) asset=tailwindcss-linux-x64 ;; \
      arm64) asset=tailwindcss-linux-arm64 ;; \
      *) echo "Unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    URL="https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/${asset}" \
      python3 -c "import os, urllib.request; urllib.request.urlretrieve(os.environ['URL'], '/tmp/tailwindcss')"; \
    URL="https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/sha256sums.txt" \
      python3 -c "import os, urllib.request; urllib.request.urlretrieve(os.environ['URL'], '/tmp/sha256sums.txt')"; \
    expected="$(grep "${asset}\$" /tmp/sha256sums.txt | awk '{print $1}')"; \
    actual="$(sha256sum /tmp/tailwindcss | awk '{print $1}')"; \
    [ -n "$expected" ] && [ "$expected" = "$actual" ]; \
    chmod +x /tmp/tailwindcss

RUN cd services/django_core && \
    /tmp/tailwindcss -i tailwind/input.css \
      -o apps/dashboard/static/dashboard/css/output.css --minify

# INTERNAL_SECRET_TOKEN only needs to be *set* for settings.py to import cleanly
# (see the pytest-django gotcha in CLAUDE.md) — collectstatic never uses its value.
RUN --mount=type=cache,target=/root/.cache/uv \
    DJANGO_SETTINGS_MODULE=config.settings \
    PYTHONPATH=/app/services/django_core \
    INTERNAL_SECRET_TOKEN=build-time-placeholder \
    uv run --no-sync python services/django_core/manage.py collectstatic --noinput

# ---------- runtime ----------
# Same Debian release and Python minor as the builder, so the copied virtualenv
# lines up with the interpreter here.
FROM python:3.12-slim-bookworm

RUN useradd --create-home --uid 1000 devpulse

WORKDIR /app

COPY --from=builder --chown=devpulse:devpulse /app/.venv /app/.venv

COPY --chown=devpulse:devpulse services/__init__.py ./services/
COPY --chown=devpulse:devpulse services/django_core/ ./services/django_core/

# The compiled+hashed static bundle whitenoise serves at runtime — collectstatic's
# manifest storage produces content-hashed filenames (e.g. output.<hash>.css) that
# {% static %} resolves through the manifest, not the raw uncompiled app static/
# dirs the line above already copied.
COPY --from=builder --chown=devpulse:devpulse \
    /app/services/django_core/staticfiles ./services/django_core/staticfiles

# config.wsgi lives under services/django_core rather than the repo root, mirroring
# the `pythonpath` that pyproject.toml already sets for pytest.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/services/django_core \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER devpulse

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/', timeout=2).status == 200 else 1)"

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
