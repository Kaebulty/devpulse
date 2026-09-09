from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("action", "actor", "service_id", "created_at")
    list_filter = ("action",)
    readonly_fields = ("actor", "action", "service_id", "metadata", "created_at")

    def has_add_permission(self, request):
        # Rows are only ever created via log_event(), never hand-typed.
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
