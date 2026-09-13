"""Populate a fresh local environment with demo data.

Nothing here fakes a status or a latency number: every service is registered for
real with FastAPI and pointed at its `/mock/health` endpoint (the same mechanism
Chaos Controls uses), so the next real health-check cycle (~60s, see
`health_check_interval_seconds`) genuinely measures each one into the state its
mock URL is rigged to produce. Requires both services running (`make dev` or
`make dev-fastapi`) — this is dev/demo tooling, not something CI or production
runs.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.registry.client import DuplicateServiceName, Environment, RegistryUnavailable
from apps.vault.services import create_service_with_key

User = get_user_model()

DEMO_PASSWORD = "devpulse-demo"  # local/demo-only fixture data, never used in prod

DEMO_USERS = [
    {"username": "admin", "role": User.Role.ADMIN},
    {"username": "developer", "role": User.Role.DEVELOPER},
]

# Each health_check_url targets FastAPI's own /mock/health (handbook §4.3's offline
# fault-simulation endpoint), with query params chosen against the health engine's
# real thresholds (degraded >=500ms, unhealthy >=2000ms or a non-2xx) so the next
# real check cycle classifies each service into the state its name suggests.
DEMO_SERVICES = [
    {
        "name": "payments-api",
        "environment": Environment.PRODUCTION,
        "health_check_url": "/mock/health",
    },
    {
        "name": "notifications-worker",
        "environment": Environment.PRODUCTION,
        "health_check_url": "/mock/health?delay=0.8",
    },
    {
        "name": "legacy-billing",
        "environment": Environment.STAGING,
        "health_check_url": "/mock/health?status=503",
    },
    {
        "name": "internal-metrics",
        "environment": Environment.DEVELOPMENT,
        "health_check_url": "/mock/health?delay=0.05",
    },
]


class Command(BaseCommand):
    help = (
        "Seed demo users and services so the dashboard has real data on first load. "
        "Idempotent: already-seeded users/services are skipped, not duplicated."
    )

    def handle(self, *args, **options):
        admin_user = self._seed_users()
        self._seed_services(admin_user)

    def _seed_users(self) -> User:
        admin_user = None
        for spec in DEMO_USERS:
            user, created = User.objects.get_or_create(
                username=spec["username"], defaults={"role": spec["role"]}
            )
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save(update_fields=["password"])
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Created user {spec['username']!r} "
                        f"(role={spec['role']}, password={DEMO_PASSWORD!r})"
                    )
                )
            else:
                self.stdout.write(f"User {spec['username']!r} already exists, skipping")
            if spec["role"] == User.Role.ADMIN:
                admin_user = user
        return admin_user

    def _seed_services(self, admin_user: User) -> None:
        base_url = settings.FASTAPI_REGISTRY_URL.rstrip("/")
        for spec in DEMO_SERVICES:
            try:
                create_service_with_key(
                    name=spec["name"],
                    environment=spec["environment"],
                    health_check_url=f"{base_url}{spec['health_check_url']}",
                    created_by=admin_user,
                )
            except DuplicateServiceName:
                self.stdout.write(f"Service {spec['name']!r} already registered, skipping")
                continue
            except RegistryUnavailable as exc:
                raise CommandError(
                    "Could not reach the FastAPI registry "
                    f"({settings.FASTAPI_REGISTRY_URL}). Is it running? "
                    "Start it with `make dev` or `make dev-fastapi` first."
                ) from exc
            self.stdout.write(self.style.SUCCESS(f"Registered service {spec['name']!r}"))
