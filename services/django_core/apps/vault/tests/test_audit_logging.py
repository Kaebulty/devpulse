import secrets
from unittest.mock import patch

import httpx
import pytest
import respx
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password

from apps.audit.models import AuditEvent
from apps.registry.client import (
    DuplicateServiceName,
    Environment,
    RegistryClient,
    RegistryUnavailable,
)
from apps.vault.models import ApiKey
from apps.vault.services import create_service_with_key, revoke_key, rotate_key

pytestmark = pytest.mark.django_db

User = get_user_model()
BASE_URL = "http://registry.internal:8001"


@pytest.fixture
def admin_user():
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
        "simulation_url": None,
    }
    payload.update(overrides)
    return respx.post(f"{BASE_URL}/api/v1/services").mock(
        return_value=httpx.Response(201, json=payload)
    )


@respx.mock
def test_create_service_with_key_logs_an_event(admin_user, settings):
    settings.FASTAPI_REGISTRY_URL = BASE_URL
    _mock_create_service()

    service, _ = create_service_with_key(
        name="payments-api",
        environment=Environment.PRODUCTION,
        health_check_url="http://localhost:8001/mock/health",
        created_by=admin_user,
    )

    event = AuditEvent.objects.get(action=AuditEvent.Action.SERVICE_KEY_CREATED)
    assert event.actor == admin_user
    assert event.service_id == service.id


@respx.mock
def test_create_service_does_not_log_on_registry_failure(admin_user, settings):
    settings.FASTAPI_REGISTRY_URL = BASE_URL
    respx.post(f"{BASE_URL}/api/v1/services").mock(return_value=httpx.Response(409))

    with pytest.raises(DuplicateServiceName):
        create_service_with_key(
            name="payments-api",
            environment=Environment.PRODUCTION,
            health_check_url="http://localhost:8001/mock/health",
            created_by=admin_user,
        )

    assert not AuditEvent.objects.exists()


def test_rotate_key_logs_an_event(admin_user):
    raw = secrets.token_urlsafe(32)
    ApiKey.objects.create(service_id=1, key_hash=make_password(raw), created_by=admin_user)

    with patch.object(RegistryClient, "update_service_token"):
        rotate_key(1, created_by=admin_user)

    event = AuditEvent.objects.get(action=AuditEvent.Action.SERVICE_KEY_ROTATED)
    assert event.actor == admin_user
    assert event.service_id == 1


def test_rotate_key_does_not_log_when_the_fastapi_push_fails(admin_user):
    raw = secrets.token_urlsafe(32)
    ApiKey.objects.create(service_id=1, key_hash=make_password(raw), created_by=admin_user)

    with (
        patch.object(
            RegistryClient, "update_service_token", side_effect=RegistryUnavailable("down")
        ),
        pytest.raises(RegistryUnavailable),
    ):
        rotate_key(1, created_by=admin_user)

    assert not AuditEvent.objects.filter(action=AuditEvent.Action.SERVICE_KEY_ROTATED).exists()


def test_revoke_key_logs_an_event(admin_user):
    raw = secrets.token_urlsafe(32)
    ApiKey.objects.create(service_id=1, key_hash=make_password(raw), created_by=admin_user)

    revoke_key(1, actor=admin_user)

    event = AuditEvent.objects.get(action=AuditEvent.Action.SERVICE_KEY_REVOKED)
    assert event.actor == admin_user
    assert event.service_id == 1


def test_revoke_key_does_not_log_when_there_was_nothing_to_revoke(admin_user):
    revoke_key(999, actor=admin_user)

    assert not AuditEvent.objects.filter(action=AuditEvent.Action.SERVICE_KEY_REVOKED).exists()
