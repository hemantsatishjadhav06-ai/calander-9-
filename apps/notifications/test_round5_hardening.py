"""Notification engine edges from the round-5 audit."""

import pytest

from apps.notifications.engine import BATCH_HEADINGS, _digest_heading, _webhook_signing_key, notify
from apps.notifications.models import EventType


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
