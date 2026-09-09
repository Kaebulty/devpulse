import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.audit.views import AuditEventListView

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def admin_user():
    return User.objects.create_user(username="admin", password="pw", role=User.Role.ADMIN)


@pytest.fixture
def developer_user():
    return User.objects.create_user(username="dev", password="pw", role=User.Role.DEVELOPER)


def test_admin_can_view_the_audit_log(client, admin_user):
    # force_login itself fires user_logged_in (see test_signals.py), which is
    # sufficient real content here — no need to hand-craft an extra event.
    client.force_login(admin_user)

    response = client.get(reverse("audit-list"))

    assert response.status_code == 200
    actions = [event.action for event in response.context["events"]]
    assert AuditEvent.Action.LOGIN_SUCCEEDED in actions


def test_developer_is_rejected(client, developer_user):
    client.force_login(developer_user)

    response = client.get(reverse("audit-list"))

    assert response.status_code == 403


def test_anonymous_is_rejected(client):
    response = client.get(reverse("audit-list"))

    assert response.status_code == 403


def test_empty_state_renders(admin_user):
    # Any client-driven login (force_login included) fires user_logged_in and
    # would populate the log, so the empty branch is exercised by invoking the
    # view directly against a bare request instead of going through a session.
    request = RequestFactory().get(reverse("audit-list"))
    request.user = admin_user

    response = AuditEventListView.as_view()(request)
    response.render()

    assert response.status_code == 200
    assert b"No audit events yet" in response.content
