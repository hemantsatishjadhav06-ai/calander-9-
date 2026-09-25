"""Notification engine edges from the round-5 audit."""

import pytest

from apps.notifications.engine import BATCH_HEADINGS, _digest_heading, _webhook_signing_key, notify
from apps.notifications.models import Channel, EventType, Notification, NotificationDelivery, NotificationPreference


@pytest.mark.django_db
def test_a_long_title_is_cut_to_the_column(user):
    notification = notify(user=user, event_type=EventType.NEW_INBOX_MESSAGE, title="New comment from " + "x" * 300)
    assert notification is not None
    assert len(notification.title) == 255


def test_a_flushed_digest_of_an_unbatched_type_has_a_heading():
    """Switching digest mode off flushes every queued type, batched or not."""
    unbatched = next(e for e in EventType.values if e not in BATCH_HEADINGS)
    assert _digest_heading(unbatched, 3) == "3 new notifications"
    assert _digest_heading(unbatched, 1) == "1 new notification"


def test_webhook_signatures_never_use_secret_key_directly(settings):
    settings.SECRET_KEY = "django-secret"
    settings.WEBHOOK_SECRET = ""
    key = _webhook_signing_key()
    assert key != b"django-secret"
    assert len(key) == 32
    settings.WEBHOOK_SECRET = "dedicated"
    assert _webhook_signing_key() == b"dedicated"


@pytest.mark.django_db
def test_in_app_off_keeps_the_bell_quiet_but_still_emails(client, user):
    """The row exists (email hangs off it); the bell, drawer and badge skip it."""
    NotificationPreference.objects.create(
        user=user, event_type=EventType.POST_SUBMITTED, channel=Channel.IN_APP, is_enabled=False
    )
    NotificationPreference.objects.create(
        user=user, event_type=EventType.POST_SUBMITTED, channel=Channel.EMAIL, is_enabled=True
    )
    notification = notify(user=user, event_type=EventType.POST_SUBMITTED, title="Quiet please")
    assert notification is not None
    assert notification.shown_in_app is False
    assert NotificationDelivery.objects.filter(notification=notification, channel=Channel.EMAIL).exists()
    assert not NotificationDelivery.objects.filter(notification=notification, channel=Channel.IN_APP).exists()

    client.force_login(user)
    assert client.get("/notifications/unread-count/").json()["count"] == 0
    drawer = client.get("/notifications/drawer/", HTTP_HX_REQUEST="true")
    assert b"Quiet please" not in drawer.content

    loud = notify(user=user, event_type=EventType.POST_FAILED, title="Loud one")
    assert loud is not None and loud.shown_in_app is True
    assert client.get("/notifications/unread-count/").json()["count"] == 1
    assert Notification.objects.filter(user=user).count() == 2
