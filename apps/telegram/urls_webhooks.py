from django.urls import path

from . import webhooks

app_name = "telegram_webhooks"
urlpatterns = [path("<uuid:connection_id>/", webhooks.ingress, name="ingress")]
