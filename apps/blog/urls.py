from django.urls import path

from . import views

app_name = "blog"

urlpatterns = [
    path("", views.post_list, name="list"),
    path("new/", views.post_create, name="create"),
    path("<uuid:post_id>/", views.post_detail, name="detail"),
    path("<uuid:post_id>/edit/", views.post_edit, name="edit"),
    path("<uuid:post_id>/preview/", views.post_preview, name="preview"),
    path("<uuid:post_id>/status/", views.post_status, name="status"),
    path("<uuid:post_id>/submit/", views.post_submit, name="submit"),
    path("<uuid:post_id>/approve/", views.post_approve, name="approve"),
    path("<uuid:post_id>/request-changes/", views.post_request_changes, name="request_changes"),
    path("<uuid:post_id>/publish/", views.post_publish, name="publish"),
    path("<uuid:post_id>/social-drafts/", views.post_social_drafts, name="social_drafts"),
]
