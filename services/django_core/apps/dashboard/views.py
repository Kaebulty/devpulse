from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.http import require_POST

from apps.accounts.rbac import admin_required
from apps.registry.client import RegistryClient, RegistryClientError, ServiceNotFound

# Chaos Controls never accepts a client-submitted URL (that would let the health
# loop be pointed anywhere — SSRF-shaped). An admin picks a preset key; the server
# resolves it to a real mock target on the registry itself, reusing the existing
# `/mock/health` endpoint (handbook §4.3). "clear" maps to None, which the registry
# treats as an explicit clear rather than "leave untouched" (see
# RegistryClient.set_simulation).
CHAOS_PRESETS = {
    "clear": None,
    "healthy": "/mock/health",
    "degraded": "/mock/health?delay=3",
    "unhealthy": "/mock/health?status=503",
}


@login_required
def index(request):
    """The dashboard shell. Renders the same fragment `service_list` polls for,
    so the first paint already shows real data instead of an empty flash.
    """
    context = _service_list_context()
    return render(request, "dashboard/index.html", context)


@login_required
def service_list(request):
    """HTMX fragment: the service table, polled every 15s from index.html."""
    context = _service_list_context()
    return render(request, "dashboard/_service_list.html", context)


@admin_required
@require_POST
def set_simulation(request, service_id):
    """Apply or clear a Chaos Controls preset on one service.

    Admin-only (enforced here, not just hidden in the template) and re-renders
    just that row for an HTMX row-swap, so applying a preset doesn't disrupt the
    list's own 15s poll.
    """
    preset = request.POST.get("simulation_preset")
    resolved_presets = _resolved_chaos_presets()
    if preset not in resolved_presets:
        return HttpResponseBadRequest("unknown simulation_preset")

    try:
        service = RegistryClient().set_simulation(service_id, resolved_presets[preset])
        error = False
    except ServiceNotFound:
        return HttpResponseBadRequest("no such service")
    except RegistryClientError:
        # Same "expected condition" treatment as the list view: show it inline on
        # the row rather than a 500, since the registry being briefly unreachable
        # isn't a bug.
        service = None
        error = True

    return render(
        request,
        "dashboard/_service_row.html",
        {
            "service": service,
            "simulation_error": error,
            "service_id": service_id,
            "chaos_presets": resolved_presets,
        },
    )


def _service_list_context() -> dict:
    try:
        services = RegistryClient().list_services()
        return {
            "services": services,
            "registry_error": False,
            "chaos_presets": _resolved_chaos_presets(),
        }
    except RegistryClientError:
        # A briefly unreachable/misconfigured registry is an expected condition to
        # show gracefully, not a 500 — the next 15s poll retries on its own.
        return {"services": [], "registry_error": True, "chaos_presets": {}}


def _resolved_chaos_presets() -> dict[str, str | None]:
    base = settings.FASTAPI_REGISTRY_URL.rstrip("/")
    return {key: f"{base}{path}" if path else None for key, path in CHAOS_PRESETS.items()}
