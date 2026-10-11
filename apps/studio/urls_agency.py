"""URLs for the agency's team roster and job pages (views_agency.py). Included by apps/studio/urls.py."""

from django.urls import path

from . import views_agency

urlpatterns = [
    path("team/", views_agency.team_roster, name="team"),
    path("jobs/<uuid:job_id>/", views_agency.job_detail, name="job"),
    path("jobs/<uuid:job_id>/progress/", views_agency.job_progress, name="job_progress"),
    path("jobs/<uuid:job_id>/retry/", views_agency.job_retry, name="job_retry"),
    path("jobs/<uuid:job_id>/cancel/", views_agency.job_cancel, name="job_cancel"),
    path("busy.txt", views_agency.health, name="busy"),
]
