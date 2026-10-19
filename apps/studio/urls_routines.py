"""URLs for the agency's routines (see views_routines.py). Included by apps/studio/urls.py."""

from django.urls import path

from . import views_routines

urlpatterns = [
    path("routines/", views_routines.routines_page, name="routines"),
    path("routines/new/", views_routines.routines_create, name="routines_create"),
    path("routines/<uuid:routine_id>/toggle/", views_routines.routines_toggle, name="routines_toggle"),
    path("routines/<uuid:routine_id>/run/", views_routines.routines_run_now, name="routines_run_now"),
    path("routines/<uuid:routine_id>/delete/", views_routines.routines_delete, name="routines_delete"),
]
