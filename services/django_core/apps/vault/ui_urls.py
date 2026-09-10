from django.urls import path

from . import ui_views

urlpatterns = [
    path("", ui_views.manage, name="vault-ui-manage"),
    path("services/", ui_views.create_service, name="vault-ui-create"),
    path(
        "services/<int:service_id>/revoke/",
        ui_views.revoke_service,
        name="vault-ui-revoke",
    ),
]
