from django.urls import path

from apps.calendar import views as calendar_views

from . import views

app_name = "approvals"

urlpatterns = [
    # The Approvals screen: the Calendar list's Approvals tab on a page of its own (spec D3).
    path("approvals/", calendar_views.approvals_index, name="index"),
    path("approvals/<uuid:post_id>/approve/", views.approve, name="approve"),
    path("approvals/<uuid:post_id>/request-changes/", views.request_changes_view, name="request_changes"),
    path("approvals/<uuid:post_id>/reject/", views.reject, name="reject"),
    path("approvals/<uuid:post_id>/resume/", views.resume, name="resume"),
    path("approvals/bulk/", views.bulk_action, name="bulk_action"),
    path("approvals/<uuid:post_id>/comments/", views.add_comment, name="add_comment"),
    path("approvals/<uuid:post_id>/comments/<uuid:comment_id>/edit/", views.edit_comment, name="edit_comment"),
    path("approvals/<uuid:post_id>/comments/<uuid:comment_id>/delete/", views.delete_comment, name="delete_comment"),
    path(
        "approvals/<uuid:post_id>/comments/<uuid:comment_id>/attachment/",
        views.comment_attachment,
        name="comment_attachment",
    ),
    path("approvals/<uuid:post_id>/versions/", views.version_diff, name="version_diff"),
]
