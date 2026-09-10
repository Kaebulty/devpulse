import json
import secrets
from datetime import timedelta
from unittest.mock import patch

import httpx
import pytest
import respx
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.db.utils import IntegrityError
from django.utils import timezone

from apps.registry.client import (
    DuplicateServiceName,
    Environment,
    RegistryClient,
    RegistryUnavailable,
)
from apps.vault.models import ApiKey
from apps.vault.services import (
    create_service_with_key,
    revoke_key,
    rotate_key,
    verify_token,
)

pytestmark = pytest.mark.django_db

User = get_user_model()
BASE_URL = "http://registry.internal:8001"


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(username="admin", password="pw", role=User.Role.ADMIN)


def _mock_create_service(**overrides):
    payload = {
        "id": 7,
        "name": "payments-api",
        "environment": "production",
        "health_check_url": "http://localhost:8001/mock/health",
        "status": "UNKNOWN",
        "latency_ms": None,
        "last_checked_at": None,
    }
    payload.update(overrides)
    return respx.post(f"{BASE_URL}/api/v1/services").mock(
        return_value=httpx.Response(201, json=payload)
    )


@respx.mock
def test_create_service_with_key_persists_hash_and_forwards_token(admin_user, settings):
    settings.FASTAPI_REGISTRY_URL = BASE_URL
    route = _mock_create_service()

    service, raw_token = create_service_with_key(
        name="payments-api",
        environment=Environment.PRODUCTION,
        health_check_url="http://localhost:8001/mock/health",
        created_by=admin_user,
    )

    assert service.id == 7
    assert raw_token  # non-empty, shown to the caller exactly once

    sent_payload = json.loads(route.calls.last.request.content)
    assert sent_payload["auth_token"] == raw_token

    key = ApiKey.objects.get(service_id=7)
    assert key.created_by == admin_user
    assert key.is_active
    assert check_password(raw_token, key.key_hash)


@respx.mock
def test_create_service_with_key_does_not_write_on_registry_failure(admin_user, settings):
    settings.FASTAPI_REGISTRY_URL = BASE_URL
    respx.post(f"{BASE_URL}/api/v1/services").mock(return_value=httpx.Response(409))

    with pytest.raises(DuplicateServiceName):
        create_service_with_key(
            name="payments-api",
            environment=Environment.PRODUCTION,
            health_check_url="http://localhost:8001/mock/health",
            created_by=admin_user,
        )

    assert not ApiKey.objects.exists()


def test_verify_token_true_for_active_key(admin_user):
    _, raw_token = _create_key(admin_user, service_id=1)

    assert verify_token(raw_token) is True


def test_verify_token_false_for_garbage():
    assert verify_token("not-a-real-token") is False


def test_verify_token_false_after_revoke(admin_user):
    _, raw_token = _create_key(admin_user, service_id=2)
    revoke_key(service_id=2, actor=admin_user)

    assert verify_token(raw_token) is False


def test_revoke_key_sets_revoked_at(admin_user):
    key, _ = _create_key(admin_user, service_id=3)

    revoke_key(service_id=3, actor=admin_user)

    key.refresh_from_db()
    assert key.revoked_at is not None
    assert key.is_active is False


def _create_key(created_by, *, service_id: int) -> tuple[ApiKey, str]:
    raw_token = secrets.token_urlsafe(32)
    key = ApiKey.objects.create(
        service_id=service_id, key_hash=make_password(raw_token), created_by=created_by
    )
    return key, raw_token


# --- rotation ---------------------------------------------------------------------


@pytest.fixture
def issued(admin_user):
    """A service with one current key, and the raw token it was issued."""
    raw = secrets.token_urlsafe(32)
    ApiKey.objects.create(service_id=1, key_hash=make_password(raw), created_by=admin_user)
    return raw


@pytest.mark.django_db
def test_rotation_keeps_the_old_token_valid_during_the_grace_window(
    issued, admin_user, settings
):
    """The core guarantee: both tokens verify during the overlap.

    This is the whole reason rotation is not an instant swap — it is what stops the
    service failing a health check between Django rotating and FastAPI picking up
    the new token.
    """
    settings.VAULT_KEY_ROTATION_GRACE_SECONDS = 300

    with patch.object(RegistryClient, "update_service_token") as push:
        new = rotate_key(1, created_by=admin_user)

    push.assert_called_once_with(1, new)
    assert verify_token(issued) is True, "old token must still verify during grace"
    assert verify_token(new) is True, "new token must verify immediately"


@pytest.mark.django_db
def test_old_token_stops_verifying_once_the_window_elapses(issued, admin_user, settings):
    settings.VAULT_KEY_ROTATION_GRACE_SECONDS = 300

    with patch.object(RegistryClient, "update_service_token"):
        new = rotate_key(1, created_by=admin_user)

    # Move the retirement into the past rather than mocking the clock.
    retired = ApiKey.objects.get(service_id=1, revoked_at__isnull=False)
    retired.revoked_at = timezone.now() - timedelta(seconds=1)
    retired.save()

    assert verify_token(issued) is False
    assert verify_token(new) is True


@pytest.mark.django_db
def test_a_failed_push_to_fastapi_leaves_the_old_key_working(issued, admin_user):
    """The failure mode the overlap design exists to prevent.

    With an instant swap this would leave the service with no valid key anywhere,
    needing manual repair. Here the old key carries it until a retry succeeds.
    """
    with patch.object(
        RegistryClient, "update_service_token", side_effect=RegistryUnavailable("down")
    ), pytest.raises(RegistryUnavailable):
        rotate_key(1, created_by=admin_user)

    assert verify_token(issued) is True, "old key must survive a failed push"


@pytest.mark.django_db
def test_only_one_current_key_per_service_is_allowed(issued, admin_user):
    """The partial unique index must actually bite."""
    with pytest.raises(IntegrityError):
        ApiKey.objects.create(
            service_id=1, key_hash=make_password("another"), created_by=admin_user
        )


@pytest.mark.django_db
def test_rotation_permits_many_retired_keys_for_one_service(issued, admin_user):
    """Retired keys accumulate as an audit trail; only the current one is constrained."""
    with patch.object(RegistryClient, "update_service_token"):
        rotate_key(1, created_by=admin_user)
        rotate_key(1, created_by=admin_user)

    assert ApiKey.objects.filter(service_id=1).count() == 3
    assert ApiKey.objects.filter(service_id=1, revoked_at__isnull=True).count() == 1


@pytest.mark.django_db
def test_rotating_a_service_with_no_key_raises(admin_user):
    with pytest.raises(ValueError, match="no current key"):
        rotate_key(999, created_by=admin_user)


@pytest.mark.django_db
def test_revoke_still_kills_instantly(issued, admin_user):
    """Regression on the revoked_at semantics change.

    revoked_at now means "stops working at", so revocation sets it to now — a key
    revoked this instant must not benefit from any grace.
    """
    revoke_key(1, actor=admin_user)
    assert verify_token(issued) is False


@pytest.mark.django_db
def test_revoke_during_the_grace_window_kills_the_retiring_key_too(issued, admin_user):
    """Revoke must clear *every* currently-valid key, not just the newest.

    After a rotation the retiring key has a future `revoked_at` and still verifies.
    Filtering on `revoked_at IS NULL` alone left it alive, so revoking a
    just-rotated service didn't actually stop its credentials working — which is
    the one thing revoke exists to do. Caught in review by Kaebulty; the original
    test above missed it because it only revoked a service that had never rotated.
    """
    with patch.object(RegistryClient, "update_service_token"):
        new = rotate_key(1, created_by=admin_user)

    assert verify_token(issued) and verify_token(new), "both live mid-grace"

    revoke_key(1, actor=admin_user)

    assert verify_token(new) is False
    assert verify_token(issued) is False, "the retiring key must die as well"
