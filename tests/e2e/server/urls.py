"""The e2e server's URL conf: the harness views, then the app's own URL conf, unchanged.

``config.settings.e2e`` points ``ROOT_URLCONF`` here; ``config/urls.py`` never mentions the harness.
"""

from django.urls import path

from config import urls as app_urls

from . import views

urlpatterns = [
    path("__e2e__/ping", views.ping, name="e2e_ping"),
    path("__e2e__/fixture/<str:name>", views.run_fixture, name="e2e_fixture"),
    path("__e2e__/probe/<str:name>", views.run_probe, name="e2e_probe"),
    *app_urls.urlpatterns,
]
