import pytest
from django.contrib.auth import get_user_model

from apps.audit.models import AuditEvent

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def user():
    return User.objects.create_user(username="dev", password="pw")


def test_create_succeeds(user):
    event = AuditEvent.objects.create(actor=user, action=AuditEvent.Action.LOGIN_SUCCEEDED)
    assert event.pk is not None


def test_resaving_an_existing_row_raises(user):
    event = AuditEvent.objects.create(actor=user, action=AuditEvent.Action.LOGIN_SUCCEEDED)

    event.action = AuditEvent.Action.LOGOUT
    with pytest.raises(ValueError):
        event.save()


def test_deleting_a_row_raises(user):
    event = AuditEvent.objects.create(actor=user, action=AuditEvent.Action.LOGIN_SUCCEEDED)

    with pytest.raises(ValueError):
        event.delete()

    assert AuditEvent.objects.filter(pk=event.pk).exists()


def test_bulk_queryset_delete_raises(user):
    AuditEvent.objects.create(actor=user, action=AuditEvent.Action.LOGIN_SUCCEEDED)

    with pytest.raises(ValueError):
        AuditEvent.objects.all().delete()

    assert AuditEvent.objects.count() == 1


def test_bulk_queryset_update_raises(user):
    AuditEvent.objects.create(actor=user, action=AuditEvent.Action.LOGIN_SUCCEEDED)

    with pytest.raises(ValueError):
        AuditEvent.objects.all().update(action=AuditEvent.Action.LOGOUT)

    assert AuditEvent.objects.get().action == AuditEvent.Action.LOGIN_SUCCEEDED


def test_actor_deletion_nulls_the_fk_instead_of_cascading(user):
    event = AuditEvent.objects.create(actor=user, action=AuditEvent.Action.LOGIN_SUCCEEDED)

    user.delete()

    event.refresh_from_db()
    assert event.actor is None
