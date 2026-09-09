from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="dashboard-index"),
    path("services/", views.service_list, name="dashboard-services"),
]
