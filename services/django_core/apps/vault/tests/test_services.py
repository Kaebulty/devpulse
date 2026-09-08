import json
import secrets

import httpx
import pytest
import respx
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password

from apps.registry.client import DuplicateServiceName, Environment
from apps.vault.models import ApiKey
from apps.vault.services import create_service_with_key, revoke_key, verify_token

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
    revoke_key(service_id=2)

    assert verify_token(raw_token) is False


def test_revoke_key_sets_revoked_at(admin_user):
    key, _ = _create_key(admin_user, service_id=3)

    revoke_key(service_id=3)

    key.refresh_from_db()
    assert key.revoked_at is not None
    assert key.is_active is False


def _create_key(created_by, *, service_id: int) -> tuple[ApiKey, str]:
    raw_token = secrets.token_urlsafe(32)
    key = ApiKey.objects.create(
        service_id=service_id, key_hash=make_password(raw_token), created_by=created_by
    )
    return key, raw_token
