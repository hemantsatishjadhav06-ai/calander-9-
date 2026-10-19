from django.urls import path

from . import views

app_name = "telegram"
urlpatterns = [
    path("", views.settings_page, name="settings"),
    path("connect/", views.connect, name="connect"),
    path("webhook/retry/", views.refresh_webhook, name="refresh_webhook"),
    path("approvals/", views.toggle_approvals, name="toggle_approvals"),
    path("test/", views.test_message, name="test_message"),
    path("create-bot/", views.managed_create, name="managed_create"),
    path("pair/", views.pair, name="pair"),
    path("channel/connect/", views.connect_channel, name="connect_channel"),
    path("channel/<uuid:channel_id>/disconnect/", views.disconnect_channel, name="disconnect_channel"),
    path("disconnect/", views.disconnect, name="disconnect"),
    path("unpair/", views.unpair, name="unpair"),
    path("chat/<uuid:chat_id>/disconnect/", views.deactivate_chat, name="deactivate_chat"),
]
