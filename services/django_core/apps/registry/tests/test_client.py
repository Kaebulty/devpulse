import json
from datetime import UTC, datetime

import httpx
import pytest
import respx

from apps.registry.client import (
    DuplicateServiceName,
    Environment,
    RegistryAuthError,
    RegistryClient,
    RegistryClientError,
    RegistryUnavailable,
    Service,
    ServiceCreateRequest,
    ServiceNotFound,
    ServiceStatus,
)

BASE_URL = "http://registry.internal:8001"


@pytest.fixture
def client():
    return RegistryClient(base_url=BASE_URL)


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


def _create_request(**overrides):
    fields = {
        "name": "payments-api",
        "environment": Environment.PRODUCTION,
        "health_check_url": "http://localhost:8001/mock/health",
        "auth_token": "raw-token",
    }
    fields.update(overrides)
    return ServiceCreateRequest(**fields)


@respx.mock
def test_list_services_returns_dtos(client):
    respx.get(f"{BASE_URL}/api/v1/services").mock(
        return_value=httpx.Response(200, json=[_service_payload()])
    )

    services = client.list_services()

    assert services == [
        Service(
            id=1,
            name="payments-api",
            environment=Environment.PRODUCTION,
            health_check_url="http://localhost:8001/mock/health",
            status=ServiceStatus.HEALTHY,
            latency_ms=42,
            last_checked_at=datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC),
        )
    ]


@respx.mock
def test_list_services_handles_unchecked_service(client):
    respx.get(f"{BASE_URL}/api/v1/services").mock(
        return_value=httpx.Response(
            200,
            json=[_service_payload(status="UNKNOWN", latency_ms=None, last_checked_at=None)],
        )
    )

    [service] = client.list_services()

    assert service.status == ServiceStatus.UNKNOWN
    assert service.latency_ms is None
    assert service.last_checked_at is None


@respx.mock
def test_create_service_returns_dto(client):
    respx.post(f"{BASE_URL}/api/v1/services").mock(
        return_value=httpx.Response(
            201, json=_service_payload(status="UNKNOWN", latency_ms=None, last_checked_at=None)
        )
    )

    service = client.create_service(_create_request())

    assert service.name == "payments-api"
    assert service.status == ServiceStatus.UNKNOWN


@respx.mock
def test_create_service_sends_auth_token(client):
    route = respx.post(f"{BASE_URL}/api/v1/services").mock(
        return_value=httpx.Response(201, json=_service_payload())
    )

    client.create_service(_create_request())

    assert json.loads(route.calls.last.request.content)["auth_token"] == "raw-token"


@respx.mock
def test_create_service_sends_internal_secret_header(client, settings):
    settings.INTERNAL_SECRET_TOKEN = "the-shared-secret"
    route = respx.post(f"{BASE_URL}/api/v1/services").mock(
        return_value=httpx.Response(201, json=_service_payload())
    )

    client.create_service(_create_request())

    assert route.calls.last.request.headers["X-Internal-Secret"] == "the-shared-secret"


@respx.mock
def test_create_service_duplicate_name_raises(client):
    respx.post(f"{BASE_URL}/api/v1/services").mock(return_value=httpx.Response(409))

    with pytest.raises(DuplicateServiceName):
        client.create_service(_create_request())


@respx.mock
def test_delete_service_not_found_raises(client):
    respx.delete(f"{BASE_URL}/api/v1/services/999").mock(return_value=httpx.Response(404))

    with pytest.raises(ServiceNotFound):
        client.delete_service(999)


@respx.mock
def test_delete_service_success_returns_none(client):
    respx.delete(f"{BASE_URL}/api/v1/services/1").mock(return_value=httpx.Response(204))

    assert client.delete_service(1) is None


@respx.mock
def test_timeout_raises_registry_unavailable(client):
    respx.get(f"{BASE_URL}/api/v1/services").mock(side_effect=httpx.TimeoutException("slow"))

    with pytest.raises(RegistryUnavailable):
        client.list_services()


@respx.mock
def test_connect_error_raises_registry_unavailable(client):
    respx.get(f"{BASE_URL}/api/v1/services").mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(RegistryUnavailable):
        client.list_services()


@respx.mock
def test_remote_protocol_error_raises_registry_unavailable(client):
    """Regression: FastAPI dying mid-response (plausible with --workers 1) used to
    propagate as a raw httpx.RemoteProtocolError instead of RegistryUnavailable."""
    respx.get(f"{BASE_URL}/api/v1/services").mock(
        side_effect=httpx.RemoteProtocolError("peer closed connection")
    )

    with pytest.raises(RegistryUnavailable):
        client.list_services()


@respx.mock
def test_server_error_raises_registry_unavailable(client):
    respx.get(f"{BASE_URL}/api/v1/services").mock(return_value=httpx.Response(500))

    with pytest.raises(RegistryUnavailable):
        client.list_services()


@respx.mock
def test_unauthorized_raises_registry_auth_error(client):
    respx.get(f"{BASE_URL}/api/v1/services").mock(return_value=httpx.Response(401))

    with pytest.raises(RegistryAuthError):
        client.list_services()


@respx.mock
def test_unexpected_status_raises_generic_client_error(client):
    respx.get(f"{BASE_URL}/api/v1/services").mock(return_value=httpx.Response(418))

    with pytest.raises(RegistryClientError):
        client.list_services()


def test_client_defaults_base_url_to_settings(settings):
    settings.FASTAPI_REGISTRY_URL = "http://from-settings:8001"
    client = RegistryClient()
    assert client._base_url == "http://from-settings:8001"


def test_create_request_to_payload_serializes_environment():
    request = _create_request(environment=Environment.STAGING)

    assert request.to_payload() == {
        "name": "payments-api",
        "environment": "staging",
        "health_check_url": "http://localhost:8001/mock/health",
        "auth_token": "raw-token",
    }


@respx.mock
def test_reuses_one_http_client_across_instances_and_calls():
    """Regression: _send() used to open+close a fresh httpx.Client per call, so
    concurrent RegistryClient() instances (e.g. two dashboard polls) never shared
    a connection pool. Import the module attribute directly rather than going
    through the public API, since "no new client got created" has no other
    externally-observable effect."""
    import apps.registry.client as client_module

    respx.get(f"{BASE_URL}/api/v1/services").mock(return_value=httpx.Response(200, json=[]))

    client_before = client_module._shared_client
    RegistryClient(base_url=BASE_URL).list_services()
    RegistryClient(base_url=BASE_URL).list_services()

    assert client_module._shared_client is client_before
