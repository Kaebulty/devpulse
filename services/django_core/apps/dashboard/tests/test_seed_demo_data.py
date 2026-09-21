import json

import httpx
import pytest
import respx
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.vault.models import ApiKey

pytestmark = pytest.mark.django_db

User = get_user_model()
BASE_URL = "http://localhost:8001"

SERVICE_NAMES = [
    "payments-api",
    "notifications-worker",
    "legacy-billing",
    "internal-metrics",
]


@pytest.fixture(autouse=True)
def registry_url(settings):
    settings.FASTAPI_REGISTRY_URL = BASE_URL


def _mock_create_service_success():
    def responder(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        return httpx.Response(
            201,
            json={
                "id": SERVICE_NAMES.index(payload["name"]) + 1,
                "name": payload["name"],
                "environment": payload["environment"],
                "health_check_url": payload["health_check_url"],
                "status": "UNKNOWN",
                "latency_ms": None,
                "last_checked_at": None,
            },
        )

    return respx.post(f"{BASE_URL}/api/v1/services").mock(side_effect=responder)


@respx.mock
def test_creates_demo_users_and_services():
    _mock_create_service_success()

    call_command("seed_demo_data")

    admin = User.objects.get(username="admin")
    developer = User.objects.get(username="developer")
    assert admin.role == User.Role.ADMIN
    assert developer.role == User.Role.DEVELOPER
    assert check_password("devpulse-demo", admin.password)

    assert ApiKey.objects.count() == len(SERVICE_NAMES)


@respx.mock
def test_service_health_check_urls_target_the_fastapi_mock_endpoint():
    route = _mock_create_service_success()

    call_command("seed_demo_data")

    sent_urls = [
        json.loads(call.request.content)["health_check_url"] for call in route.calls
    ]
    assert all(url.startswith(f"{BASE_URL}/mock/health") for url in sent_urls)


@respx.mock
def test_rerunning_skips_already_seeded_users_and_services():
    _mock_create_service_success()
    call_command("seed_demo_data")

    respx.routes.clear()
    respx.post(f"{BASE_URL}/api/v1/services").mock(return_value=httpx.Response(409))

    call_command("seed_demo_data")

    assert User.objects.count() == 2
    assert ApiKey.objects.count() == len(SERVICE_NAMES)


@respx.mock
def test_registry_unavailable_raises_a_helpful_command_error():
    respx.post(f"{BASE_URL}/api/v1/services").mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(CommandError, match="Could not reach the FastAPI registry"):
        call_command("seed_demo_data")
