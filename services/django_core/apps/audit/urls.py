from django.urls import path

from . import views

urlpatterns = [
    path("", views.AuditEventListView.as_view(), name="audit-list"),
]
