from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.registry.client import RegistryClient, RegistryClientError


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


def _service_list_context() -> dict:
    try:
        return {"services": RegistryClient().list_services(), "registry_error": False}
    except RegistryClientError:
        # A briefly unreachable/misconfigured registry is an expected condition to
        # show gracefully, not a 500 — the next 15s poll retries on its own.
        return {"services": [], "registry_error": True}
