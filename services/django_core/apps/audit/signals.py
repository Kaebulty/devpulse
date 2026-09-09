"""Auth events are logged via Django's built-in auth signals rather than by
editing apps.accounts' views — DevPulseLoginView/LogoutView already fire these
on every real login/logout, so this needs no changes to that app at all.
"""

from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .models import AuditEvent
from .services import log_event


@receiver(user_logged_in)
def _log_login_succeeded(sender, request, user, **kwargs):
    log_event(actor=user, action=AuditEvent.Action.LOGIN_SUCCEEDED)


@receiver(user_logged_out)
def _log_logout(sender, request, user, **kwargs):
    # user is None if the session was already anonymous when logout was called.
    if user is not None:
        log_event(actor=user, action=AuditEvent.Action.LOGOUT)


@receiver(user_login_failed)
def _log_login_failed(sender, credentials, request=None, **kwargs):
    log_event(
        actor=None,
        action=AuditEvent.Action.LOGIN_FAILED,
        metadata={"username": credentials.get("username", "")},
    )
