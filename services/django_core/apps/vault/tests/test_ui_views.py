from datetime import timedelta

import httpx
import pytest
import respx
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.vault.models import ApiKey

pytestmark = pytest.mark.django_db

User = get_user_model()
BASE_URL = "http://registry.internal:8001"


@pytest.fixture
def admin_client(db):
    User.objects.create_user(username="admin", password="pw", role=User.Role.ADMIN)
    client = Client()
    client.login(username="admin", password="pw")
    return client


@pytest.fixture
def dev_client(db):
    User.objects.create_user(username="dev", password="pw", role=User.Role.DEVELOPER)
    client = Client()
    client.login(username="dev", password="pw")
    return client


def _revoke_url(service_id: int) -> str:
    return reverse("vault-ui-revoke", args=[service_id])


def _service_payload(**overrides):
    payload = {
        "id": 1,
        "name": "payments-api",
        "environment": "production",
        "health_check_url": "http://localhost:8001/mock/health",
        "status": "HEALTHY",
        "latency_ms": 10,
        "last_checked_at": None,
        "simulation_url": None,
    }
    payload.update(overrides)
    return payload


def _mock_list(services):
    return respx.get(f"{BASE_URL}/api/v1/services").mock(
        return_value=httpx.Response(200, json=services)
    )


def _mock_create(service_id=1, **overrides):
    return respx.post(f"{BASE_URL}/api/v1/services").mock(
        return_value=httpx.Response(201, json=_service_payload(id=service_id, **overrides))
    )


# --- manage page -------------------------------------------------------------


def test_manage_rejects_developer(dev_client):
    response = dev_client.get(reverse("vault-ui-manage"))
    assert response.status_code == 403


def test_manage_rejects_anonymous():
    response = Client().get(reverse("vault-ui-manage"))
    assert response.status_code == 403


@respx.mock
def test_manage_shows_no_key_for_unregistered_service(admin_client, settings):
    settings.FASTAPI_REGISTRY_URL = BASE_URL
    _mock_list([_service_payload()])

    response = admin_client.get(reverse("vault-ui-manage"))

    assert response.status_code == 200
    assert b"payments-api" in response.content
    assert b"No key" in response.content


@respx.mock
def test_manage_shows_active_key_status(admin_client, settings):
    settings.FASTAPI_REGISTRY_URL = BASE_URL
    _mock_list([_service_payload(id=5)])
    admin = User.objects.get(username="admin")
    ApiKey.objects.create(service_id=5, key_hash=make_password("x"), created_by=admin)

    response = admin_client.get(reverse("vault-ui-manage"))

    assert b"Active" in response.content
    assert b"Revoke" in response.content


@respx.mock
def test_manage_shows_revoked_key_status(admin_client, settings):
    settings.FASTAPI_REGISTRY_URL = BASE_URL
    _mock_list([_service_payload(id=5)])
    admin = User.objects.get(username="admin")
    ApiKey.objects.create(
        service_id=5,
        key_hash=make_password("x"),
        created_by=admin,
        revoked_at=timezone.now() - timedelta(days=1),
    )

    response = admin_client.get(reverse("vault-ui-manage"))

    assert b"Revoked" in response.content
    # A dead key gets no revoke button — nothing left to revoke.
    assert _revoke_url(5).encode() not in response.content


@respx.mock
def test_manage_shows_registry_error_banner(admin_client, settings):
    settings.FASTAPI_REGISTRY_URL = BASE_URL
    respx.get(f"{BASE_URL}/api/v1/services").mock(side_effect=httpx.ConnectError("refused"))

    response = admin_client.get(reverse("vault-ui-manage"))

    assert response.status_code == 200
    assert b"Registry is unreachable" in response.content


# --- create service ----------------------------------------------------------


def test_create_rejects_developer(dev_client):
    response = dev_client.post(reverse("vault-ui-create"), {"name": "x"})
    assert response.status_code == 403


def test_create_rejects_anonymous():
    response = Client().post(reverse("vault-ui-create"), {"name": "x"})
    assert response.status_code == 403


def test_create_rejects_missing_csrf_token():
    """The register-service form is real <form> + {% csrf_token %}, but every other
    test here uses the default Client() (enforce_csrf_checks=False) so none of them
    would notice if that protection broke. This proves it's actually enforced."""
    User.objects.create_user(username="admin2", password="pw", role=User.Role.ADMIN)
    client = Client(enforce_csrf_checks=True)
    client.login(username="admin2", password="pw")

    response = client.post(reverse("vault-ui-create"), {"name": "x"})

    assert response.status_code == 403


@respx.mock
def test_create_service_issues_key_and_shows_token_once(admin_client, settings):
    settings.FASTAPI_REGISTRY_URL = BASE_URL
    _mock_create(service_id=9)
    _mock_list([_service_payload(id=9)])

    response = admin_client.post(
        reverse("vault-ui-create"),
        {
            "name": "payments-api",
            "environment": "production",
            "health_check_url": "http://localhost:8001/mock/health",
        },
    )

    assert response.status_code == 200
    assert b"registered" in response.content
    assert ApiKey.objects.filter(service_id=9, revoked_at__isnull=True).exists()
    assert AuditEvent.objects.filter(
        action=AuditEvent.Action.SERVICE_KEY_CREATED, service_id=9
    ).exists()
    # The new row must appear in the same response, via the out-of-band swap.
    assert b'id="vault-service-list"' in response.content
    assert b"payments-api" in response.content


def test_create_service_requires_name_and_url(admin_client):
    response = admin_client.post(
        reverse("vault-ui-create"), {"name": "", "health_check_url": "", "environment": ""}
    )

    assert response.status_code == 200
    assert b"required" in response.content
    assert not ApiKey.objects.exists()


@respx.mock
def test_create_service_duplicate_name_shows_friendly_error(admin_client, settings):
    settings.FASTAPI_REGISTRY_URL = BASE_URL
    respx.post(f"{BASE_URL}/api/v1/services").mock(return_value=httpx.Response(409))
    _mock_list([])

    response = admin_client.post(
        reverse("vault-ui-create"),
        {
            "name": "payments-api",
            "environment": "production",
            "health_check_url": "http://localhost:8001/mock/health",
        },
    )

    assert response.status_code == 200
    assert b"already registered" in response.content
    assert not ApiKey.objects.exists()


@respx.mock
def test_create_service_registry_unreachable_shows_error(admin_client, settings):
    settings.FASTAPI_REGISTRY_URL = BASE_URL
    respx.post(f"{BASE_URL}/api/v1/services").mock(side_effect=httpx.ConnectError("refused"))
    _mock_list([])

    response = admin_client.post(
        reverse("vault-ui-create"),
        {
            "name": "payments-api",
            "environment": "production",
            "health_check_url": "http://localhost:8001/mock/health",
        },
    )

    assert response.status_code == 200
    assert b"try again" in response.content


# --- revoke --------------------------------------------------------------


def test_revoke_rejects_developer(dev_client):
    response = dev_client.post(_revoke_url(1))
    assert response.status_code == 403


def test_revoke_rejects_anonymous():
    response = Client().post(_revoke_url(1))
    assert response.status_code == 403


@respx.mock
def test_revoke_marks_key_revoked_and_updates_row(admin_client, settings):
    settings.FASTAPI_REGISTRY_URL = BASE_URL
    admin = User.objects.get(username="admin")
    ApiKey.objects.create(service_id=5, key_hash=make_password("x"), created_by=admin)
    _mock_list([_service_payload(id=5)])

    response = admin_client.post(_revoke_url(5))

    assert response.status_code == 200
    assert b"Revoked" in response.content
    assert not ApiKey.objects.get(service_id=5).is_active
    assert AuditEvent.objects.filter(
        action=AuditEvent.Action.SERVICE_KEY_REVOKED, service_id=5
    ).exists()


@respx.mock
def test_revoke_missing_service_renders_placeholder(admin_client, settings):
    """The service can vanish from the registry between page load and the click
    (e.g. deleted elsewhere) — revoking its key in Django still succeeds, but
    there's no row left in the registry's own list to redisplay."""
    settings.FASTAPI_REGISTRY_URL = BASE_URL
    admin = User.objects.get(username="admin")
    ApiKey.objects.create(service_id=5, key_hash=make_password("x"), created_by=admin)
    _mock_list([])

    response = admin_client.post(_revoke_url(5))

    assert response.status_code == 200
    assert b"no longer registered" in response.content
    assert not ApiKey.objects.get(service_id=5).is_active
