"""URLs for the blog's agency features (writing with the team, SEO, Search Console). Included by urls.py."""

from django.urls import path

from . import views, views_search_console

urlpatterns: list = []

# ---- SEO score, check-up and Google Search Console (workstream D1) ----
# The OAuth callback is the one fixed address outside /workspace/ (config/urls.py,
# name "blog_search_console_callback"), so Google needs a single redirect URI.
urlpatterns += [
    path("seo-score/", views.seo_score, name="seo_score"),
    path("<uuid:post_id>/seo-score/", views.seo_score, name="post_seo_score"),
    path("seo-checkup/", views.seo_checkup, name="seo_checkup"),
    path(
        "search-console/<uuid:site_id>/connect/",
        views_search_console.connect,
        name="search_console_connect",
    ),
    path(
        "search-console/<uuid:site_id>/property/",
        views_search_console.choose_property,
        name="search_console_property",
    ),
    path(
        "search-console/<uuid:site_id>/sync/",
        views_search_console.sync_now,
        name="search_console_sync",
    ),
    path(
        "search-console/<uuid:site_id>/disconnect/",
        views_search_console.disconnect,
        name="search_console_disconnect",
    ),
]
# ---- end workstream D1 ----
