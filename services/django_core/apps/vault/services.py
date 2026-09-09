"""Business logic for issuing, verifying, and revoking service credentials.

Kept separate from views.py so the DRF views stay thin request/response
adapters — this module is what the (future) HTMX dashboard will also call
directly once it exists.
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import log_event
from apps.registry.client import Environment, RegistryClient, Service, ServiceCreateRequest

from .models import ApiKey


def _still_valid() -> Q:
    """Keys that currently verify.

    `revoked_at` is when a key stops working, so a future value is still valid —
    that is what gives a rotated-out key its grace window. Shared deliberately:
    `verify_token` and `revoke_key` must agree on what "valid" means, and when they
    disagreed, revoking a service mid-rotation left the retiring key alive.
    """
    return Q(revoked_at__isnull=True) | Q(revoked_at__gt=timezone.now())


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
        ServiceCreateRequest(
            name=name,
            environment=environment,
            health_check_url=health_check_url,
            auth_token=raw_token,
        )
    )
    ApiKey.objects.create(
        service_id=service.id, key_hash=make_password(raw_token), created_by=created_by
    )
    log_event(
        actor=created_by, action=AuditEvent.Action.SERVICE_KEY_CREATED, service_id=service.id
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
        check_password(raw_token, key.key_hash) for key in ApiKey.objects.filter(_still_valid())
    )


def rotate_key(service_id: int, created_by) -> str:
    """Replace a service's key, keeping the old one valid for a grace window.

    Rotation spans two systems with no shared transaction, so every ordering has a
    moment where Django and FastAPI disagree about the current token. An overlap
    window makes that harmless: both keys verify during it, so it does not matter
    which side is updated first, and a failure pushing the new token to FastAPI
    leaves the service still passing health checks on the old one.

    Returns the new raw token once. It is never stored and cannot be retrieved
    again, the same contract as `create_service_with_key`.
    """
    grace = timedelta(seconds=settings.VAULT_KEY_ROTATION_GRACE_SECONDS)
    raw_token = secrets.token_urlsafe(32)

    with transaction.atomic():
        # Retire the current key *first*. The partial unique index permits only one
        # row per service with a NULL revoked_at, so the replacement cannot be
        # inserted while the old one is still NULL. Atomic, so the two are never
        # both current even momentarily.
        retired = ApiKey.objects.filter(
            service_id=service_id, revoked_at__isnull=True
        ).update(revoked_at=timezone.now() + grace)

        if not retired:
            raise ValueError(f"service {service_id} has no current key to rotate")

        ApiKey.objects.create(
            service_id=service_id,
            key_hash=make_password(raw_token),
            created_by=created_by,
        )

    # Deliberately outside the transaction and last. If this raises, Django has
    # already rotated but the retired key verifies for the whole grace window, so
    # the service keeps passing health checks and the caller can simply retry.
    # Doing it before the commit would instead leave FastAPI presenting a token
    # Django has never seen.
    RegistryClient().update_service_token(service_id, raw_token)

    # Only logged once the push succeeds too: a rotation that raised above is
    # incomplete and safely retryable (the old key still verifies), not an event
    # that actually happened from the caller's perspective.
    log_event(
        actor=created_by, action=AuditEvent.Action.SERVICE_KEY_ROTATED, service_id=service_id
    )

    return raw_token


def revoke_key(service_id: int, actor) -> None:
    """Kill every key that currently verifies for this service, immediately.

    Uses the same predicate as `verify_token`, not just `revoked_at IS NULL`: after a
    rotation the retiring key has a *future* `revoked_at` and still verifies, so
    filtering on NULL alone would leave it alive — and revoke exists precisely to
    stop a service's credentials working right now.
    """
    revoked = ApiKey.objects.filter(_still_valid(), service_id=service_id).update(
        revoked_at=timezone.now()
    )
    # Only logged if a key was actually killed — a no-op revoke (nothing was active)
    # isn't a security event worth recording as one.
    if revoked:
        log_event(
            actor=actor, action=AuditEvent.Action.SERVICE_KEY_REVOKED, service_id=service_id
        )
