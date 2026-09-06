.PHONY: dev-db dev dev-django dev-fastapi migrate lint test clean

# Start Postgres (both core_db and services_db) in Docker. Run this first.
dev-db:
	docker compose up db -d --wait

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
