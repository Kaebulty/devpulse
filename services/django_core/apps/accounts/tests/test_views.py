import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def user():
    return User.objects.create_user(username="dev", password="correct-horse")


def test_login_page_renders(client):
    response = client.get(reverse("login"))
    assert response.status_code == 200


def test_login_with_valid_credentials_redirects_to_dashboard(client, user):
    response = client.post(
        reverse("login"), {"username": "dev", "password": "correct-horse"}
    )
    assert response.status_code == 302
    assert response.url == reverse("dashboard-index")


def test_login_with_invalid_credentials_does_not_authenticate(client, user):
    response = client.post(reverse("login"), {"username": "dev", "password": "wrong"})
    assert response.status_code == 200
    assert not response.wsgi_request.user.is_authenticated


def test_logout_redirects_to_login_and_clears_session(client, user):
    client.force_login(user)
    response = client.post(reverse("logout"))
    assert response.status_code == 302
    assert response.url == reverse("login")

    response = client.get(reverse("dashboard-index"))
    assert response.status_code == 302


def test_logout_rejects_get(client, user):
    client.force_login(user)
    response = client.get(reverse("logout"))
    assert response.status_code == 405
