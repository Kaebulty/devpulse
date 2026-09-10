from django.conf import settings
from django.db import models


class AuditEventQuerySet(models.QuerySet):
    """Blocks bulk mutation, since Model.delete()/save() overrides alone don't:
    QuerySet.delete()/.update() go straight to SQL without calling per-instance
    methods — a well-known Django gotcha that would otherwise leave a hole in
    the "no update/delete path" guarantee this model exists to provide.
    """

    def delete(self):
        raise ValueError("AuditEvent is append-only; rows cannot be deleted.")

    def update(self, **kwargs):
        raise ValueError("AuditEvent is append-only; existing rows cannot be modified.")


class AuditEvent(models.Model):
    """An append-only record of a security-sensitive action.

    No view exposes an edit or delete path, and save()/delete() (plus the
    queryset above) enforce that at the model layer too — "we didn't build a UI
    for it" isn't the same guarantee as "it can't happen", and an audit log is
    exactly the place that gap matters.

    `actor` uses SET_NULL rather than ApiKey.created_by's PROTECT: an audit trail
    should survive the actor being deleted later (e.g. an offboarded user), not
    block that deletion. `service_id` is a plain integer for the same reason
    ApiKey.service_id is — services_db is a separate database with its own ORM.
    """

    class Action(models.TextChoices):
        LOGIN_SUCCEEDED = "LOGIN_SUCCEEDED", "Login succeeded"
        LOGIN_FAILED = "LOGIN_FAILED", "Login failed"
        LOGOUT = "LOGOUT", "Logout"
        SERVICE_KEY_CREATED = "SERVICE_KEY_CREATED", "Service key created"
        SERVICE_KEY_ROTATED = "SERVICE_KEY_ROTATED", "Service key rotated"
        SERVICE_KEY_REVOKED = "SERVICE_KEY_REVOKED", "Service key revoked"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    action = models.CharField(max_length=32, choices=Action.choices)
    service_id = models.PositiveIntegerField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AuditEventQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("AuditEvent is append-only; existing rows cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("AuditEvent is append-only; rows cannot be deleted.")

    def __repr__(self) -> str:
        return f"<AuditEvent action={self.action} actor_id={self.actor_id}>"
