"""HTMX/Tailwind UI for registering and revoking services.

Separate from views.py's DRF APIViews (JSON API consumers, admin_required via
RoleRequiredMixin) — these are the "future HTMX dashboard" services.py's own
docstring already anticipated, calling create_service_with_key/revoke_key
directly rather than proxying through the JSON endpoints.
"""

from django.shortcuts import render
from django.views.decorators.http import require_POST

from apps.accounts.rbac import admin_required
from apps.registry.client import (
    DuplicateServiceName,
    Environment,
    RegistryClient,
    RegistryClientError,
)

from .models import ApiKey
from .services import create_service_with_key, revoke_key


@admin_required
def manage(request):
    """The vault page: register-service form + every service's key status."""
    context = _vault_list_context()
    context["environments"] = list(Environment)
    return render(request, "vault/manage.html", context)


@admin_required
@require_POST
def create_service(request):
    """Register a service and issue it a key, returning the raw token once.

    Always 200, success or failure: consistent with the rest of this app's
    "expected condition, not a 500" handling (dashboard's registry-error
    banner, Chaos Controls' inline row error) — a duplicate name or an
    unreachable registry renders inline rather than crashing.
    """
    name = request.POST.get("name", "").strip()
    health_check_url = request.POST.get("health_check_url", "").strip()
    environment_raw = request.POST.get("environment", "")

    token = None
    service = None
    error = None

    if not name or not health_check_url:
        error = "Name and health check URL are required."
    else:
        try:
            environment = Environment(environment_raw)
        except ValueError:
            error = "Choose a valid environment."
        else:
            try:
                service, token = create_service_with_key(
                    name=name,
                    environment=environment,
                    health_check_url=health_check_url,
                    created_by=request.user,
                )
            except DuplicateServiceName:
                error = f'A service named "{name}" is already registered.'
            except RegistryClientError:
                error = "Couldn't reach the registry — try again."

    context = _vault_list_context()
    context.update({"token": token, "service": service, "error": error})
    return render(request, "vault/_create_response.html", context)


@admin_required
@require_POST
def revoke_service(request, service_id):
    """Revoke a service's active key and re-render just that row."""
    revoke_key(service_id, actor=request.user)

    rows = _vault_list_context()["rows"]
    row = next((r for r in rows if r["service"].id == service_id), None)
    return render(request, "vault/_service_row.html", {"row": row, "service_id": service_id})


def _vault_list_context() -> dict:
    try:
        services = RegistryClient().list_services()
        registry_error = False
    except RegistryClientError:
        services = []
        registry_error = True

    keys_by_service: dict[int, list[ApiKey]] = {}
    if services:
        for key in ApiKey.objects.filter(service_id__in=[s.id for s in services]):
            keys_by_service.setdefault(key.service_id, []).append(key)

    rows = [
        {"service": service, "key_status": _key_status(keys_by_service.get(service.id, []))}
        for service in services
    ]
    return {"rows": rows, "registry_error": registry_error}


def _key_status(keys: list[ApiKey]) -> str:
    if any(key.is_active for key in keys):
        return "active"
    if keys:
        return "revoked"
    return "none"
