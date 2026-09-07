from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.rbac import RoleRequiredMixin
from apps.registry.client import Environment

from .services import create_service_with_key, revoke_key, verify_token


class VaultVerifyView(APIView):
    """Called by an externally-monitored service to check its own bearer token.

    Deliberately outside Django's session/RBAC system: the caller is another
    service presenting a credential, not a logged-in Django user — the same
    reason FastAPI's own /mock/health is unauthenticated by the internal secret.
    Always responds 200 or 401, never 403/404, so a caller's check is a bare
    status-code comparison.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.removeprefix("Bearer ").strip()
        if token and verify_token(token):
            return Response({"valid": True}, status=200)
        return Response({"valid": False}, status=401)


class CreateServiceKeyView(RoleRequiredMixin, APIView):
    """Register a service with the FastAPI registry and issue it a vault key.

    Admin-only: this mints a credential, the same trust level as creating a
    user. Returns the raw token in the response body exactly once — it is
    never stored or retrievable again after this call.
    """

    allowed_roles = (User.Role.ADMIN,)

    def post(self, request):
        data = request.data
        service, raw_token = create_service_with_key(
            name=data["name"],
            environment=Environment(data["environment"]),
            health_check_url=data["health_check_url"],
            created_by=request.user,
        )
        return Response(
            {
                "service": {
                    "id": service.id,
                    "name": service.name,
                    "environment": service.environment.value,
                    "health_check_url": service.health_check_url,
                    "status": service.status.value,
                },
                "token": raw_token,
            },
            status=201,
        )


class RevokeServiceKeyView(RoleRequiredMixin, APIView):
    """Revoke a service's active key. Verification against it then 401s."""

    allowed_roles = (User.Role.ADMIN,)

    def post(self, request, service_id):
        revoke_key(service_id)
        return Response(status=204)
