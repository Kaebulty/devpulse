import pytest
from django.contrib.auth import get_user_model

pytestmark = pytest.mark.django_db

User = get_user_model()


def test_default_role_is_developer():
    user = User.objects.create_user(username="dev", password="pw")
    assert user.role == User.Role.DEVELOPER
    assert user.is_admin is False


def test_admin_role_sets_is_admin():
    user = User.objects.create_user(username="boss", password="pw", role=User.Role.ADMIN)
    assert user.is_admin is True
