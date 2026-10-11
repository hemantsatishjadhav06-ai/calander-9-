"""URLs for the agency's autopilot pages (see views_autopilot.py). Included by apps/studio/urls.py."""

from django.urls import path

from . import views_autopilot

urlpatterns = [
    path("autopilot/", views_autopilot.settings_page, name="autopilot"),
    path("autopilot/plan/", views_autopilot.plan_now, name="autopilot_plan"),
    path("autopilot/report/", views_autopilot.report_now, name="autopilot_report"),
]
