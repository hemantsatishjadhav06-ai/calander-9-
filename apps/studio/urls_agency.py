"""URLs for Activity (the team at work, live: views_live.py) and job pages (views_agency.py).

Included by apps/studio/urls.py. ``studio:team`` names Activity at ``activity/`` (spec D4);
``team/``, its old address, answers a 301 there after the page's own checks. The board's refresh
stays at ``team/board/``, where open tabs poll it.
"""

from django.urls import path

from . import views_agency, views_live

urlpatterns = [
    path("activity/", views_agency.team_roster, name="team"),
    path("team/", views_agency.team_legacy, name="team_legacy"),
    path("team/board/", views_live.team_board, name="team_board"),
    path("jobs/<uuid:job_id>/", views_agency.job_detail, name="job"),
    path("jobs/<uuid:job_id>/progress/", views_agency.job_progress, name="job_progress"),
    path("jobs/<uuid:job_id>/retry/", views_agency.job_retry, name="job_retry"),
    path("jobs/<uuid:job_id>/cancel/", views_agency.job_cancel, name="job_cancel"),
    path("busy.txt", views_agency.health, name="busy"),
]
