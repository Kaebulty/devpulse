.PHONY: dev-db dev dev-django dev-fastapi migrate lint test clean

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

# Run both services natively via uv, in parallel. Ctrl-C stops both.
dev:
	@trap 'kill 0' EXIT; \
	$(MAKE) dev-django & \
	$(MAKE) dev-fastapi & \
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
