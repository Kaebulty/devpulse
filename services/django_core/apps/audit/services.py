"""Single write path for audit events — see .models.AuditEvent for why this
matters more here than it does elsewhere: kept separate from views/signals so
every caller (vault, accounts' signals, later Chaos Controls) goes through one
place rather than constructing AuditEvent rows by hand.
"""

from __future__ import annotations

from .models import AuditEvent


def log_event(
    *,
    actor,
    action: str,
    service_id: int | None = None,
    metadata: dict | None = None,
) -> AuditEvent:
    return AuditEvent.objects.create(
        actor=actor,
        action=action,
        service_id=service_id,
        metadata=metadata or {},
    )
