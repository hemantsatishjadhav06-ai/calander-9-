"""URLs for the team thread and the inbox's "Draft replies with the team" (views_chat.py). Included by apps/studio/urls.py."""

from django.urls import path

from . import views_chat

urlpatterns = [
    path("thread/", views_chat.thread_page, name="thread"),
    path("thread/send/", views_chat.thread_start, name="thread_start"),
    path("thread/<uuid:conversation_id>/messages/", views_chat.thread_messages, name="thread_messages"),
    path("thread/<uuid:conversation_id>/send/", views_chat.thread_send, name="thread_send"),
    path("<uuid:brief_id>/thread/send/", views_chat.brief_thread_send, name="brief_thread_send"),
    path("blog/<uuid:blog_post_id>/thread/send/", views_chat.blog_thread_send, name="blog_thread_send"),
    path("inbox/draft/", views_chat.inbox_draft, name="inbox_draft"),
]
