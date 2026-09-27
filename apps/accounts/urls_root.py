from django.urls import path

from . import views

urlpatterns = [
    # Public landing for anonymous visitors; the authenticated dashboard for
    # logged-in users. Name stays "dashboard" so redirect("dashboard") resolves.
    path("", views.home, name="dashboard"),
]
