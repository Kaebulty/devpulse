#!/bin/bash
# Provisions services_db alongside POSTGRES_DB (core_db), plus one least-privilege
# login role per service. Each role owns exactly one database and cannot connect to
# the other — the data-tier analogue of the handbook §8 security-group tiering.
#
# POSTGRES_USER remains a superuser and can still reach both databases, so existing
# tooling and migrations keep working while each service migrates to its scoped role.
#
# IMPORTANT: Postgres runs /docker-entrypoint-initdb.d/* ONLY on first init, i.e. when
# the postgres_data volume is empty. If the container was started before this script
# existed, services_db and the roles will be missing.
# Fix: docker compose down -v && docker compose up db -d
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
	-- CREATEDB on django_user only: pytest-django spins up and tears down its own
	-- "test_core_db" per run. fastapi_user doesn't need it — that suite runs against
	-- an in-memory SQLite fixture (services/fastapi_registry/tests/conftest.py), never
	-- a real services_db.
	CREATE ROLE "${DJANGO_DB_USER}"  LOGIN CREATEDB PASSWORD '${DJANGO_DB_PASSWORD}';
	CREATE ROLE "${FASTAPI_DB_USER}" LOGIN PASSWORD '${FASTAPI_DB_PASSWORD}';

	-- core_db already exists (created by POSTGRES_DB); hand it to the Django role.
	ALTER DATABASE "${POSTGRES_DB}" OWNER TO "${DJANGO_DB_USER}";
	CREATE DATABASE "${SERVICES_DB_NAME}" OWNER "${FASTAPI_DB_USER}";

	-- Deny by default, then grant each role only its own database.
	REVOKE CONNECT ON DATABASE "${POSTGRES_DB}"      FROM PUBLIC;
	REVOKE CONNECT ON DATABASE "${SERVICES_DB_NAME}" FROM PUBLIC;
	GRANT  CONNECT ON DATABASE "${POSTGRES_DB}"      TO "${DJANGO_DB_USER}";
	GRANT  CONNECT ON DATABASE "${SERVICES_DB_NAME}" TO "${FASTAPI_DB_USER}";
EOSQL

echo "init-databases: created ${SERVICES_DB_NAME}, roles ${DJANGO_DB_USER} / ${FASTAPI_DB_USER}"
