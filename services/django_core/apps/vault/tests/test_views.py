import httpx
import pytest
import respx
from django.contrib.auth import get_user_model
from django.test import Client

pytestmark = pytest.mark.django_db

User = get_user_model()
BASE_URL = "http://registry.internal:8001"

CREATE_URL = "/api/v1/vault/services/"
VERIFY_URL = "/api/v1/vault/verify/"


def _revoke_url(service_id: int) -> str:
    return f"/api/v1/vault/services/{service_id}/revoke/"


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


def _mock_create_service(service_id=7):
    return respx.post(f"{BASE_URL}/api/v1/services").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": service_id,
                "name": "payments-api",
                "environment": "production",
                "health_check_url": "http://localhost:8001/mock/health",
                "status": "UNKNOWN",
                "latency_ms": None,
                "last_checked_at": None,
            },
        )
    )


def test_create_service_rejects_developer(dev_client):
    response = dev_client.post(CREATE_URL, data={}, content_type="application/json")

    assert response.status_code == 403


def test_create_service_rejects_anonymous():
    response = Client().post(CREATE_URL, data={}, content_type="application/json")

    assert response.status_code == 403


@respx.mock
def test_create_service_issues_key_for_admin(admin_client, settings):
    settings.FASTAPI_REGISTRY_URL = BASE_URL
    _mock_create_service()

    response = admin_client.post(
        CREATE_URL,
        data={
            "name": "payments-api",
            "environment": "production",
            "health_check_url": "http://localhost:8001/mock/health",
        },
        content_type="application/json",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["service"]["id"] == 7
    assert body["token"]


@respx.mock
def test_verify_valid_and_revoked_token(admin_client, settings):
    settings.FASTAPI_REGISTRY_URL = BASE_URL
    _mock_create_service()

    create_response = admin_client.post(
        CREATE_URL,
        data={
            "name": "payments-api",
            "environment": "production",
            "health_check_url": "http://localhost:8001/mock/health",
        },
        content_type="application/json",
    )
    token = create_response.json()["token"]

    valid_response = Client().post(
        VERIFY_URL, HTTP_AUTHORIZATION=f"Bearer {token}", content_type="application/json"
    )
    assert valid_response.status_code == 200
    assert valid_response.json() == {"valid": True}

    admin_client.post(_revoke_url(7), content_type="application/json")

    revoked_response = Client().post(
        VERIFY_URL, HTTP_AUTHORIZATION=f"Bearer {token}", content_type="application/json"
    )
    assert revoked_response.status_code == 401
    assert revoked_response.json() == {"valid": False}


def test_verify_rejects_garbage_token():
    response = Client().post(
        VERIFY_URL, HTTP_AUTHORIZATION="Bearer garbage", content_type="application/json"
    )

    assert response.status_code == 401


def test_revoke_rejects_developer(dev_client):
    response = dev_client.post(_revoke_url(1), content_type="application/json")

    assert response.status_code == 403
