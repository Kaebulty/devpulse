from django.urls import path

from .views import CreateServiceKeyView, RevokeServiceKeyView, VaultVerifyView

urlpatterns = [
    path("verify/", VaultVerifyView.as_view(), name="vault-verify"),
    path("services/", CreateServiceKeyView.as_view(), name="vault-create-service"),
    path(
        "services/<int:service_id>/revoke/",
        RevokeServiceKeyView.as_view(),
        name="vault-revoke-service",
    ),
]
