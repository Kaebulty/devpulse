import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.audit.models import AuditEvent

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def user():
    return User.objects.create_user(username="dev", password="correct-horse")


def test_successful_login_logs_an_event(client, user):
    client.post(reverse("login"), {"username": "dev", "password": "correct-horse"})

    event = AuditEvent.objects.get(action=AuditEvent.Action.LOGIN_SUCCEEDED)
    assert event.actor == user


def test_failed_login_logs_an_event_with_no_actor(client, user):
    client.post(reverse("login"), {"username": "dev", "password": "wrong"})

    event = AuditEvent.objects.get(action=AuditEvent.Action.LOGIN_FAILED)
    assert event.actor is None
    assert event.metadata == {"username": "dev"}


def test_logout_logs_an_event(client, user):
    client.force_login(user)
    client.post(reverse("logout"))

    event = AuditEvent.objects.get(action=AuditEvent.Action.LOGOUT)
    assert event.actor == user
