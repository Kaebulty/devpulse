from django.test import Client

# No pytest.mark.django_db here, deliberately: it doubles as a regression guard.
# If the view ever touched the database, pytest-django would fail this test with
# "Database access not allowed" before the assertion even runs.


def test_health_returns_ok():
    response = Client().get("/health/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
