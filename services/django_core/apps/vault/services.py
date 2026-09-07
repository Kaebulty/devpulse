"""Business logic for issuing, verifying, and revoking service credentials.

Kept separate from views.py so the DRF views stay thin request/response
adapters — this module is what the (future) HTMX dashboard will also call
directly once it exists.
"""

from __future__ import annotations

import secrets

from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone

from apps.registry.client import Environment, RegistryClient, Service

from .models import ApiKey


def create_service_with_key(
    *, name: str, environment: Environment, health_check_url: str, created_by
) -> tuple[Service, str]:
    """Register a service with FastAPI and issue it a vault key.

    FastAPI is called first: if it rejects the create (e.g. a duplicate name),
    nothing is written to Django's vault for a service that doesn't exist. The
    raw token is returned once, for display to the admin — it is never stored
    or retrievable again after this call returns.
    """
    raw_token = secrets.token_urlsafe(32)
    service = RegistryClient().create_service(
        name=name,
        environment=environment,
        health_check_url=health_check_url,
        auth_token=raw_token,
    )
    ApiKey.objects.create(
        service_id=service.id, key_hash=make_password(raw_token), created_by=created_by
    )
    return service, raw_token


def verify_token(raw_token: str) -> bool:
    """Check whether `raw_token` matches any currently active key.

    A linear scan + check_password over active keys, not an indexed key-id/
    secret split (as e.g. Stripe/GitHub tokens use): this is called at most
    once per service per ~60s health-check cycle, so it's negligible at this
    scale — an indexed design would be solving a problem this app doesn't have.
    """
    return any(
        check_password(raw_token, key.key_hash)
        for key in ApiKey.objects.filter(revoked_at__isnull=True)
    )


def revoke_key(service_id: int) -> None:
    ApiKey.objects.filter(service_id=service_id, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )
