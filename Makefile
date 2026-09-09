.PHONY: dev-db dev dev-django dev-fastapi tailwind-build tailwind-watch migrate lint test clean

# Standalone Tailwind CLI (github.com/tailwindlabs/tailwindcss/releases) — no Node/npm
# needed, matching the rest of this repo's uv-only, single-toolchain philosophy.
# Pinned by exact version + checksum, since this downloads and executes a binary.
TAILWIND_VERSION := v4.3.3
TAILWIND_BIN := $(CURDIR)/.bin/tailwindcss
TAILWIND_RELEASE_URL := https://github.com/tailwindlabs/tailwindcss/releases/download/$(TAILWIND_VERSION)
TAILWIND_INPUT := tailwind/input.css
TAILWIND_OUTPUT := apps/dashboard/static/dashboard/css/output.css

$(TAILWIND_BIN):
	@mkdir -p $(CURDIR)/.bin
	@os=$$(uname -s); arch=$$(uname -m); \
	case "$$os-$$arch" in \
		Linux-x86_64) asset=tailwindcss-linux-x64 ;; \
		Linux-aarch64|Linux-arm64) asset=tailwindcss-linux-arm64 ;; \
		Darwin-x86_64) asset=tailwindcss-macos-x64 ;; \
		Darwin-arm64) asset=tailwindcss-macos-arm64 ;; \
		*) echo "Unsupported platform for the Tailwind CLI: $$os-$$arch" >&2; exit 1 ;; \
	esac; \
	echo "Downloading tailwindcss $(TAILWIND_VERSION) ($$asset)..."; \
	curl -fsSL -o $(TAILWIND_BIN) "$(TAILWIND_RELEASE_URL)/$$asset"; \
	curl -fsSL -o $(CURDIR)/.bin/sha256sums.txt "$(TAILWIND_RELEASE_URL)/sha256sums.txt"; \
	expected=$$(grep "$$asset$$" $(CURDIR)/.bin/sha256sums.txt | awk '{print $$1}'); \
	actual=$$(sha256sum $(TAILWIND_BIN) | awk '{print $$1}'); \
	if [ -z "$$expected" ] || [ "$$expected" != "$$actual" ]; then \
		echo "Checksum mismatch for $$asset — aborting." >&2; \
		rm -f $(TAILWIND_BIN); \
		exit 1; \
	fi; \
	chmod +x $(TAILWIND_BIN)

# One-shot minified build — what the Docker image also runs.
tailwind-build: $(TAILWIND_BIN)
	cd services/django_core && $(TAILWIND_BIN) -i $(TAILWIND_INPUT) -o $(TAILWIND_OUTPUT) --minify

# Rebuilds on template/CSS changes — the third parallel process in `make dev`.
tailwind-watch: $(TAILWIND_BIN)
	cd services/django_core && $(TAILWIND_BIN) -i $(TAILWIND_INPUT) -o $(TAILWIND_OUTPUT) --watch

# Start Postgres (both core_db and services_db) in Docker. Run this first.
#
# Deliberately does NOT run `docker compose up` when the container is already there.
# .env is gitignored, so independent checkouts generate independent passwords, and
# `up` reconciles the running container against *this* checkout's env — which
# recreates it. The named volume keeps the data, but the init script only runs on an
# empty volume, so the roles keep their original passwords while the container now
# advertises different ones: the second checkout gets auth failures against its own
# credentials, and anyone's `make dev` loses its connection.
#
# Three cases: healthy already (nothing to do), running but still initialising (wait,
# don't recreate), not running at all (cold start with --wait so migrate can't race it).
dev-db:
	@status=$$(docker inspect -f '{{.State.Health.Status}}' devpulse-db 2>/dev/null || true); \
	if [ "$$status" = "healthy" ]; then \
		echo "devpulse-db already healthy"; \
	elif [ -n "$$status" ]; then \
		echo "devpulse-db starting, waiting for health..."; \
		until [ "$$(docker inspect -f '{{.State.Health.Status}}' devpulse-db)" = "healthy" ]; do sleep 1; done; \
	else \
		docker compose up db -d --wait; \
	fi

# Run both services plus the Tailwind watcher natively via uv, in parallel. Ctrl-C
# stops all three.
dev: $(TAILWIND_BIN)
	@trap 'kill 0' EXIT; \
	$(MAKE) dev-django & \
	$(MAKE) dev-fastapi & \
	$(MAKE) tailwind-watch & \
	wait

dev-django:
	uv run python services/django_core/manage.py runserver 0.0.0.0:8000

dev-fastapi:
	uv run uvicorn services.fastapi_registry.main:app --reload --port 8001

# Run both services' migrations. Separate ORMs, separate commands.
migrate: dev-db
	uv run python services/django_core/manage.py migrate
	cd services/fastapi_registry && uv run alembic upgrade head

lint:
	uv run ruff check .

# Both suites in one pytest-django session. Depends on dev-db because the Django
# tests need a real Postgres to create their test database against; without it
# `make test` fails on a clean checkout with a psycopg OperationalError.
test: dev-db
	uv run pytest services

clean:
	docker compose down
