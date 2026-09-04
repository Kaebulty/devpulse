import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory
from django.views import View

from apps.accounts.rbac import RoleRequiredMixin, admin_required, role_required

pytestmark = pytest.mark.django_db

User = get_user_model()


@role_required(User.Role.ADMIN)
def admin_only_view(request):
    return HttpResponse("ok")


class AdminOnlyView(RoleRequiredMixin, View):
    allowed_roles = (User.Role.ADMIN,)

    def get(self, request):
        return HttpResponse("ok")


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(username="boss", password="pw", role=User.Role.ADMIN)


@pytest.fixture
def dev_user(db):
    return User.objects.create_user(username="dev", password="pw", role=User.Role.DEVELOPER)


def test_decorator_blocks_anonymous(rf):
    request = rf.get("/")
    request.user = AnonymousUser()
    with pytest.raises(PermissionDenied):
        admin_only_view(request)


def test_decorator_blocks_wrong_role(rf, dev_user):
    request = rf.get("/")
    request.user = dev_user
    with pytest.raises(PermissionDenied):
        admin_only_view(request)


def test_decorator_allows_matching_role(rf, admin_user):
    request = rf.get("/")
    request.user = admin_user
    response = admin_only_view(request)
    assert response.status_code == 200


def test_mixin_blocks_anonymous(rf):
    request = rf.get("/")
    request.user = AnonymousUser()
    with pytest.raises(PermissionDenied):
        AdminOnlyView.as_view()(request)


def test_mixin_blocks_wrong_role(rf, dev_user):
    request = rf.get("/")
    request.user = dev_user
    with pytest.raises(PermissionDenied):
        AdminOnlyView.as_view()(request)


def test_mixin_allows_matching_role(rf, admin_user):
    request = rf.get("/")
    request.user = admin_user
    response = AdminOnlyView.as_view()(request)
    assert response.status_code == 200


def test_admin_required_is_role_required_for_admin(rf, admin_user):
    request = rf.get("/")
    request.user = admin_user
    assert admin_required(lambda r: HttpResponse("ok"))(request).status_code == 200
