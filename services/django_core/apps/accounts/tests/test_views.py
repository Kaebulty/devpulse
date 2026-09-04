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


def test_login_with_valid_credentials_redirects_to_home(client, user):
    response = client.post(
        reverse("login"), {"username": "dev", "password": "correct-horse"}
    )
    assert response.status_code == 302
    assert response.url == reverse("home")


def test_login_with_invalid_credentials_does_not_authenticate(client, user):
    response = client.post(reverse("login"), {"username": "dev", "password": "wrong"})
    assert response.status_code == 200
    assert not response.wsgi_request.user.is_authenticated


def test_home_requires_login(client):
    response = client.get(reverse("home"))
    assert response.status_code == 302
    assert reverse("login") in response.url


def test_home_shows_username_when_logged_in(client, user):
    client.force_login(user)
    response = client.get(reverse("home"))
    assert response.status_code == 200
    assert b"dev" in response.content


def test_logout_redirects_to_login_and_clears_session(client, user):
    client.force_login(user)
    response = client.post(reverse("logout"))
    assert response.status_code == 302
    assert response.url == reverse("login")

    response = client.get(reverse("home"))
    assert response.status_code == 302


def test_logout_rejects_get(client, user):
    client.force_login(user)
    response = client.get(reverse("logout"))
    assert response.status_code == 405
