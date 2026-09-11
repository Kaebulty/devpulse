import json

import httpx
import pytest
import respx
from django.contrib.auth import get_user_model
from django.test import Client
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


@respx.mock
def test_admin_sees_simulation_dropdown(client, user):
    user.role = User.Role.ADMIN
    user.save()
    respx.get(f"{BASE_URL}/api/v1/services").mock(
        return_value=httpx.Response(200, json=[_service_payload()])
    )
    client.force_login(user)

    response = client.get(reverse("dashboard-index"))

    assert b'name="simulation_preset"' in response.content


@respx.mock
def test_developer_does_not_see_simulation_dropdown(client, user):
    """RBAC + Chaos Controls: the dropdown is admin-only. Developers get only the
    read-only status/latency badge, enforced here in the template render, not just
    hidden by CSS."""
    respx.get(f"{BASE_URL}/api/v1/services").mock(
        return_value=httpx.Response(200, json=[_service_payload()])
    )
    client.force_login(user)

    response = client.get(reverse("dashboard-index"))

    assert b'name="simulation_preset"' not in response.content


@respx.mock
def test_active_simulation_shows_badge_for_every_role(client, user):
    """mrustamov04's design explicitly calls for the UI to show simulated state
    rather than let it silently expire — visible to developers too, not just admins."""
    respx.get(f"{BASE_URL}/api/v1/services").mock(
        return_value=httpx.Response(
            200, json=[_service_payload(simulation_url=f"{BASE_URL}/mock/health?status=503")]
        )
    )
    client.force_login(user)

    response = client.get(reverse("dashboard-index"))

    assert b"Simulated" in response.content


def test_set_simulation_rejects_anonymous(client):
    """admin_required 403s anonymous the same as wrong-role, matching apps.vault's
    RoleRequiredMixin convention — no login redirect."""
    response = client.post(reverse("dashboard-set-simulation", args=[1]))
    assert response.status_code == 403


def test_set_simulation_rejects_missing_csrf_token(user):
    """Every other test in this file uses pytest-django's client fixture, which has
    enforce_csrf_checks=False by default — none of them would notice a real CSRF
    hole on this state-changing endpoint. This proves it's actually enforced."""
    user.role = User.Role.ADMIN
    user.save()
    strict_client = Client(enforce_csrf_checks=True)
    strict_client.force_login(user)

    response = strict_client.post(
        reverse("dashboard-set-simulation", args=[1]), {"simulation_preset": "healthy"}
    )

    assert response.status_code == 403


def test_set_simulation_requires_admin(client, user):
    """Enforced at the endpoint too, not just hidden in the template — a developer
    posting directly must still be rejected."""
    client.force_login(user)

    response = client.post(
        reverse("dashboard-set-simulation", args=[1]), {"simulation_preset": "unhealthy"}
    )

    assert response.status_code == 403


@respx.mock
def test_set_simulation_applies_preset_and_returns_the_row(client, user):
    user.role = User.Role.ADMIN
    user.save()
    respx.patch(f"{BASE_URL}/api/v1/services/1").mock(
        return_value=httpx.Response(
            200, json=_service_payload(simulation_url=f"{BASE_URL}/mock/health?status=503")
        )
    )
    client.force_login(user)

    response = client.post(
        reverse("dashboard-set-simulation", args=[1]), {"simulation_preset": "unhealthy"}
    )

    assert response.status_code == 200
    assert b"Simulated" in response.content
    body = json.loads(respx.calls.last.request.content)
    assert body == {"simulation_url": f"{BASE_URL}/mock/health?status=503"}


@respx.mock
def test_set_simulation_clear_sends_explicit_null(client, user):
    user.role = User.Role.ADMIN
    user.save()
    route = respx.patch(f"{BASE_URL}/api/v1/services/1").mock(
        return_value=httpx.Response(200, json=_service_payload(simulation_url=None))
    )
    client.force_login(user)

    response = client.post(
        reverse("dashboard-set-simulation", args=[1]), {"simulation_preset": "clear"}
    )

    assert response.status_code == 200
    assert b"Simulated" not in response.content
    assert json.loads(route.calls.last.request.content) == {"simulation_url": None}


def test_set_simulation_rejects_unknown_preset(client, user):
    user.role = User.Role.ADMIN
    user.save()
    client.force_login(user)

    response = client.post(
        reverse("dashboard-set-simulation", args=[1]), {"simulation_preset": "on-fire"}
    )

    assert response.status_code == 400


@respx.mock
def test_set_simulation_missing_service_returns_bad_request(client, user):
    user.role = User.Role.ADMIN
    user.save()
    respx.patch(f"{BASE_URL}/api/v1/services/999").mock(return_value=httpx.Response(404))
    client.force_login(user)

    response = client.post(
        reverse("dashboard-set-simulation", args=[999]), {"simulation_preset": "healthy"}
    )

    assert response.status_code == 400


@respx.mock
def test_set_simulation_registry_unreachable_renders_inline_error(client, user):
    """Same 'expected condition, not a 500' treatment as the list view."""
    user.role = User.Role.ADMIN
    user.save()
    respx.patch(f"{BASE_URL}/api/v1/services/1").mock(side_effect=httpx.ConnectError("refused"))
    client.force_login(user)

    response = client.post(
        reverse("dashboard-set-simulation", args=[1]), {"simulation_preset": "healthy"}
    )

    assert response.status_code == 200
    assert b"try again" in response.content
