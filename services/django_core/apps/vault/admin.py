from django.contrib import admin

from .models import ApiKey


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ("service_id", "created_by", "created_at", "revoked_at", "is_active")
    readonly_fields = ("service_id", "key_hash", "created_by", "created_at", "revoked_at")

    def has_add_permission(self, request):
        # Keys are only ever issued via create_service_with_key, never hand-typed.
        return False
