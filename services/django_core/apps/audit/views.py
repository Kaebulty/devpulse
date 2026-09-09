from django.views.generic import ListView

from apps.accounts.models import User
from apps.accounts.rbac import RoleRequiredMixin

from .models import AuditEvent


class AuditEventListView(RoleRequiredMixin, ListView):
    model = AuditEvent
    template_name = "audit/list.html"
    context_object_name = "events"
    paginate_by = 50
    allowed_roles = (User.Role.ADMIN,)

    def get_queryset(self):
        return AuditEvent.objects.select_related("actor")
