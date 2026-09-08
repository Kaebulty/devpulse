import httpx
import pytest
import respx
from django.contrib.auth import get_user_model
from django.urls import reverse

pytestmark = pytest.mark.django_db

User = get_user_model()

BASE_URL = "http://localhost:8001"


@pytest.fixture
def user():
    return User.objects.create_user(username="dev", password="correct-horse")


@pytest.fixture(autouse=True)
def registry_url(settings):
    settings.FASTAPI_REGISTRY_URL = BASE_URL


def _service_payload(**overrides):
    payload = {
        "id": 1,
        "name": "payments-api",
        "environment": "production",
        "health_check_url": "http://localhost:8001/mock/health",
        "status": "HEALTHY",
        "latency_ms": 42,
        "last_checked_at": "2026-09-06T12:00:00+00:00",
    }
    payload.update(overrides)
    return payload


def test_index_requires_login(client):
    response = client.get(reverse("dashboard-index"))
    assert response.status_code == 302
    assert reverse("login") in response.url


def test_service_list_requires_login(client):
    response = client.get(reverse("dashboard-services"))
    assert response.status_code == 302
    assert reverse("login") in response.url


@respx.mock
def test_index_shows_username_and_registered_services(client, user):
    respx.get(f"{BASE_URL}/api/v1/services").mock(
        return_value=httpx.Response(200, json=[_service_payload()])
    )
    client.force_login(user)

    response = client.get(reverse("dashboard-index"))

    assert response.status_code == 200
    assert b"dev" in response.content
    assert b"payments-api" in response.content
    assert b"HEALTHY" in response.content


@respx.mock
def test_index_shows_empty_state_with_no_services(client, user):
    respx.get(f"{BASE_URL}/api/v1/services").mock(return_value=httpx.Response(200, json=[]))
    client.force_login(user)

    response = client.get(reverse("dashboard-index"))

    assert response.status_code == 200
    assert b"No services registered yet." in response.content


@respx.mock
def test_index_shows_offline_banner_when_registry_is_unreachable(client, user):
    """The registry being briefly down is an expected state to render gracefully,
    not a 500 — this must never surface as an error page."""
    respx.get(f"{BASE_URL}/api/v1/services").mock(side_effect=httpx.ConnectError("refused"))
    client.force_login(user)

    response = client.get(reverse("dashboard-index"))

    assert response.status_code == 200
    assert b"Registry is unreachable" in response.content


@respx.mock
def test_service_list_fragment_polls_the_registry(client, user):
    respx.get(f"{BASE_URL}/api/v1/services").mock(
        return_value=httpx.Response(200, json=[_service_payload(status="DEGRADED")])
    )
    client.force_login(user)

    response = client.get(reverse("dashboard-services"))

    assert response.status_code == 200
    assert b"DEGRADED" in response.content
    # A polled fragment, not a full page.
    assert b"<html" not in response.content


@respx.mock
def test_index_container_is_a_live_region(client, user):
    """Screen readers must be told about the DOM swap every 15s poll causes."""
    respx.get(f"{BASE_URL}/api/v1/services").mock(return_value=httpx.Response(200, json=[]))
    client.force_login(user)

    response = client.get(reverse("dashboard-index"))

    assert b'aria-live="polite"' in response.content


@respx.mock
def test_never_checked_service_is_labelled_distinctly(client, user):
    respx.get(f"{BASE_URL}/api/v1/services").mock(
        return_value=httpx.Response(
            200, json=[_service_payload(status="UNKNOWN", latency_ms=None, last_checked_at=None)]
        )
    )
    client.force_login(user)

    response = client.get(reverse("dashboard-index"))

    assert b"never checked yet" in response.content


@respx.mock
def test_checked_service_shows_last_checked_time(client, user):
    respx.get(f"{BASE_URL}/api/v1/services").mock(
        return_value=httpx.Response(200, json=[_service_payload()])
    )
    client.force_login(user)

    response = client.get(reverse("dashboard-index"))

    assert b"last checked" in response.content
    assert b"never checked yet" not in response.content


@respx.mock
def test_admin_role_badge_renders(client, user):
    user.role = User.Role.ADMIN
    user.save()
    respx.get(f"{BASE_URL}/api/v1/services").mock(return_value=httpx.Response(200, json=[]))
    client.force_login(user)

    response = client.get(reverse("dashboard-index"))

    assert b"Admin" in response.content
