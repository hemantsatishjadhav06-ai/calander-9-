"""OpenDots-derived controls inside the existing tenant-scoped Studio."""

from django.urls import path

from . import opendots_views

urlpatterns = [
    path("coworkers/jobs/<uuid:job_id>/control/", opendots_views.job_control, name="coworker_job_control"),
]
