"""Site-wide routes that make SM Manager installable as an app.

The manifest and the service worker have to sit at the root: a service worker
only controls pages under the path it is served from.
"""

from django.urls import path

from . import views

urlpatterns = [
    path("manifest.webmanifest", views.manifest, name="pwa_manifest"),
    path("sw.js", views.service_worker, name="pwa_service_worker"),
    path("offline/", views.offline, name="pwa_offline"),
    path("app/", views.app_launch, name="app_launch"),
    path("app/<slug:target>/", views.app_launch, name="app_launch_target"),
]
