from django.conf import settings
from django.db import models


class ApiKey(models.Model):
    """A hashed credential issued to one FastAPI-registered service.

    `service_id` is a plain integer reference to FastAPI's ServiceModel.id, not a
    Django FK: services_db is a separate database with its own ORM (SQLAlchemy),
    and this app must not reach across that boundary. Only a hash of the raw
    token is ever stored here — Django's job is to verify a presented token, not
    to hand one back out, so it never needs the raw value again after issuing it.
    """

    service_id = models.PositiveIntegerField(unique=True)
    key_hash = models.CharField(max_length=128)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="issued_keys"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None

    def __repr__(self) -> str:
        return f"<ApiKey service_id={self.service_id} active={self.is_active}>"
