from django.urls import path

from . import views, views_team

app_name = "client_portal"

urlpatterns = [
    path("expired/", views.magic_link_expired, name="magic_link_expired"),
    path("", views.portal_dashboard, name="dashboard"),
    path("approvals/", views.portal_approval_queue, name="approval_queue"),
    path("approvals/<uuid:post_id>/approve/", views.portal_approve, name="approve"),
    path("approvals/<uuid:post_id>/request-changes/", views.portal_request_changes, name="request_changes"),
    path("approvals/<uuid:post_id>/reject/", views.portal_reject, name="reject"),
    path("approvals/<uuid:post_id>/hold/", views.portal_request_hold, name="request_hold"),
    path("published/", views.portal_published, name="published"),
    path("activity/", views.portal_activity, name="activity"),
    path("reports/", views.portal_reports, name="reports"),
    # Talk to the team (views_team.py)
    path("team/", views_team.portal_team, name="team"),
    path("team/send/", views_team.portal_team_send, name="team_send"),
    path("team/unread/", views_team.portal_team_unread, name="team_unread"),
    path("team/<uuid:conversation_id>/messages/", views_team.portal_team_messages, name="team_messages"),
    path("approvals/<uuid:post_id>/ask/", views_team.portal_post_ask, name="post_ask"),
    path("approvals/<uuid:post_id>/thread/", views_team.portal_post_thread, name="post_thread"),
    # Magic link entry must be last (catches any token string)
    path("<str:token>/", views.magic_link_entry, name="magic_link_entry"),
]
