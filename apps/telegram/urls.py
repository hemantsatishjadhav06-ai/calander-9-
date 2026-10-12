from django.urls import path

from . import views

app_name = "telegram"
urlpatterns = [
    path("", views.settings_page, name="settings"),
    path("connect/", views.connect, name="connect"),
    path("pair/", views.pair, name="pair"),
    path("disconnect/", views.disconnect, name="disconnect"),
    path("unpair/", views.unpair, name="unpair"),
    path("chat/<uuid:chat_id>/disconnect/", views.deactivate_chat, name="deactivate_chat"),
]
