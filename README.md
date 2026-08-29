# DevPulse

Internal developer portal for registering microservices, monitoring health, and managing
hashed API keys — Django gateway + FastAPI health engine.

| Service | Stack | Database |
| --- | --- | --- |
| `services/django_core` | Django 5.1 + DRF, Gunicorn (WSGI) | `core_db` |
| `services/fastapi_registry` | FastAPI + SQLAlchemy 2.0 async, Uvicorn (ASGI) | `services_db` |

Both databases live in a single PostgreSQL 16 container defined in `compose.yaml`.

## Local database

### 1. Create your `.env`

```bash
cp .env.example .env
```

Then generate a real value for each of the three `change-me` passwords —
`POSTGRES_PASSWORD`, `DJANGO_DB_PASSWORD`, `FASTAPI_DB_PASSWORD`:

```bash
openssl rand -hex 32
```

Hex is deliberate: base64 output contains `+`, `/`, and `=`, which have to be
percent-encoded inside a database connection URL and cause confusing failures when they
are not.

`.env` is gitignored and must never be committed. `compose.yaml` refuses to start with a
clear error if any required variable is missing, rather than silently coming up with a
blank password.

**Passwords are per-developer, not shared.** Each of us runs our own local container, and
the roles are created with whatever values are in *your* `.env`. Generate your own — there
is nothing to ask a teammate for. Only `.env.example`, which lists the variable names, is
committed.

### 2. Start the database

```bash
docker compose up db -d
docker compose ps          # wait for STATUS to read (healthy)
```

If port 5432 is already taken on your machine (a local Postgres install, for example),
set `POSTGRES_PORT` in your `.env` instead of editing `compose.yaml`. The container is
bound to `127.0.0.1` and is not reachable from the local network.

### 3. Verify both databases exist

```bash
docker compose exec db psql -U devpulse_user -d core_db -c "\l"
```

You should see `core_db` and `services_db`.

## Database roles

`docker/init-databases.sh` creates one least-privilege login role per service:

| Role | Owns | Can connect to |
| --- | --- | --- |
| `django_user` | `core_db` | `core_db` only |
| `fastapi_user` | `services_db` | `services_db` only |
| `devpulse_user` | — | both (superuser, for admin and tooling) |

`CONNECT` is revoked from `PUBLIC` on both databases, so a compromise of one service
cannot read the other's data. Point each application at its own role; keep
`devpulse_user` for administrative access.

Connect each service as its own role **from its first migration onward**. Postgres assigns
table ownership to whichever role runs `CREATE TABLE`, so migrating as `devpulse_user` and
switching later leaves the tables owned by the superuser and the scoped role locked out.

## Connecting a service

Each service reads its own credentials from `.env`. These variable names are the contract
between `compose.yaml` and the application config — don't hardcode values.

| | Django (`core_db`) | FastAPI (`services_db`) |
| --- | --- | --- |
| User | `DJANGO_DB_USER` | `FASTAPI_DB_USER` |
| Password | `DJANGO_DB_PASSWORD` | `FASTAPI_DB_PASSWORD` |
| Database | `CORE_DB_NAME` | `SERVICES_DB_NAME` |
| Host / port | `POSTGRES_HOST` / `POSTGRES_PORT` | `POSTGRES_HOST` / `POSTGRES_PORT` |

Django, in `settings.py`:

```python
import os

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["CORE_DB_NAME"],
        "USER": os.environ["DJANGO_DB_USER"],
        "PASSWORD": os.environ["DJANGO_DB_PASSWORD"],
        "HOST": os.environ["POSTGRES_HOST"],
        "PORT": os.environ["POSTGRES_PORT"],
    }
}
```

FastAPI builds an async DSN from the same parts, using `postgresql+asyncpg://` and the
`FASTAPI_DB_*` variables.

Use `POSTGRES_HOST=localhost` when running the app natively via `uv`. Once the services
themselves are containerised, it becomes `db` — the compose service name.

## Resetting the database

`docker/init-databases.sh` runs **only on first initialization** — that is, when the
`postgres_data` volume is empty. If you started the container before the script existed,
or you change the script, `services_db` and the roles will not be (re)created by a plain
restart. Wipe the volume and start over:

```bash
docker compose down -v
docker compose up db -d
```

This destroys all local database data.
