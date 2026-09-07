from django.http import JsonResponse


def health(request):
    """Liveness probe.

    Deliberately unauthenticated and free of database access, mirroring
    services/fastapi_registry's /health: it answers "is this process up",
    which container orchestrators need before the database is necessarily
    reachable.
    """
    return JsonResponse({"status": "ok"})
