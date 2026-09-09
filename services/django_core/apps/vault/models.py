from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class ApiKey(models.Model):
    """A hashed credential issued to one FastAPI-registered service.

    `service_id` is a plain integer reference to FastAPI's ServiceModel.id, not a
    Django FK: services_db is a separate database with its own ORM (SQLAlchemy),
    and this app must not reach across that boundary. Only a hash of the raw
    token is ever stored here — Django's job is to verify a presented token, not
    to hand one back out, so it never needs the raw value again after issuing it.
    """

    # Not unique outright: rotation needs a retiring key and its replacement to
    # coexist. The constraint below keeps at most one *current* key per service
    # while allowing any number of retired ones, which is what makes the key
    # history auditable.
    service_id = models.PositiveIntegerField(db_index=True)
    key_hash = models.CharField(max_length=128)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="issued_keys"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # The instant this key stops working, not the instant someone pressed revoke.
    # Rotation sets it to a future time so the retiring key keeps verifying through
    # its grace window; revocation sets it to now, killing the key immediately.
    # Same idea as certificate and JWT signing-key rollover.
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["service_id"],
                condition=Q(revoked_at__isnull=True),
                name="unique_current_key_per_service",
            )
        ]

    @property
    def is_active(self) -> bool:
        """True while the key still verifies.

        A future `revoked_at` is a scheduled retirement, not a past event — the key
        works right up until that moment arrives.
        """
        return self.revoked_at is None or self.revoked_at > timezone.now()

    def __repr__(self) -> str:
        return f"<ApiKey service_id={self.service_id} active={self.is_active}>"
