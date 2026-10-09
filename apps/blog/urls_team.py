"""URLs for the blog's agency features (writing with the team, SEO, Search Console). Included by urls.py."""

from django.urls import path

from . import views_team

urlpatterns: list = []

# --- Writing with the SEO team: new articles, revisions, posts from an article (views_team.py) ---
urlpatterns += [
    path("write/", views_team.write, name="write"),
    path("team/<uuid:job_id>/", views_team.team_job, name="team_job"),
    path("team/<uuid:job_id>/retry/", views_team.team_retry, name="team_retry"),
    path("<uuid:post_id>/team/", views_team.team_panel, name="team_panel"),
    path("<uuid:post_id>/team/revise/", views_team.team_revise, name="team_revise"),
    path("<uuid:post_id>/team/social/", views_team.team_repurpose, name="team_repurpose"),
]
# --- end: writing with the SEO team ---
