"""The ``invite_requested`` event: reaches operators' bell and email, never their preference lists.

Only platform operators receive it (``apps.marketing.views.request_invite``), so
it is not something a person chooses to hear about: it stays out of the
preference matrix, and saving that matrix must not quietly switch it off.

Strangers decide how many arrive, and every notification email to one person
counts against that person's allowance (``apps.common.mail``: 6 an hour, 20 a
day). So the bell has each request at once, while the email is one message a
day listing them (at ``DAILY_DIGEST_HOUR`` UTC), with no early send for a
burst: invite requests can spend at most one of an operator's emails a day,
never the ones their alerts and approvals need. Like the other non-critical
events, quiet hours keep them in the bell only.
"""

import datetime
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.notifications.engine import DAILY_DIGEST_HOUR, DEFAULT_CHANNELS, notify, send_batched_email_digests
from apps.notifications.models import (
    Channel,
    DeliveryStatus,
    EventType,
    NotificationDelivery,
    NotificationPreference,
    QuietHours,
)

#: The outbound-email budget as production configures it (config/settings/base.py).
PRODUCTION_EMAIL = {
    "EMAIL_BACKEND": "apps.common.mail.BudgetedEmailBackend",
    "EMAIL_INNER_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
    "EMAIL_SENDING_ENABLED": True,
    "EMAIL_DAILY_SEND_LIMIT": 2000,
    "EMAIL_RECIPIENT_HOURLY_LIMIT": 6,
    "EMAIL_RECIPIENT_DAILY_LIMIT": 20,
}


def at(hour, minute=0, day=17):
    return datetime.datetime(2026, 9, day, hour, minute, tzinfo=datetime.UTC)


@contextmanager
def frozen_now(moment):
    with patch("django.utils.timezone.now", return_value=moment):
        yield


def _queued_emails(user):
    return NotificationDelivery.objects.filter(
        notification__user=user,
        notification__event_type=EventType.INVITE_REQUESTED,
        channel=Channel.EMAIL,
        status=DeliveryStatus.PENDING,
        batch_queued_at__isnull=False,
    )


@pytest.fixture
def operator(db):
    return User.objects.create_user(
        email="op@smbean.example", password="pw", name="Op", is_staff=True, tos_accepted_at=timezone.now()
    )


def test_the_event_type_has_a_plain_label():
    assert EventType.INVITE_REQUESTED == "invite_requested"
    assert EventType.INVITE_REQUESTED.label == "Invite requested"


def test_it_defaults_to_in_app_and_email():
    assert DEFAULT_CHANNELS[EventType.INVITE_REQUESTED] == {Channel.IN_APP: True, Channel.EMAIL: True}


@pytest.mark.django_db
def test_it_shows_in_the_bell_at_once_and_its_email_waits_for_the_digest(operator, mailoutbox):
    notice = notify(operator, EventType.INVITE_REQUESTED, "Invite request from Ana", "Ana at Northwind")

    assert notice is not None
    assert notice.shown_in_app is True
    assert mailoutbox == []
    assert _queued_emails(operator).count() == 1


@pytest.mark.django_db
def test_it_is_not_listed_on_the_preferences_page(client, operator):
    client.force_login(operator)

    response = client.get("/notifications/preferences/")

    assert response.status_code == 200
    rows = [row["event_type"] for row in response.context["matrix"]]
    assert EventType.INVITE_REQUESTED not in rows
    assert EventType.POST_FAILED in rows
    assert "Invite requested" not in response.content.decode()


@pytest.mark.django_db
def test_it_is_not_offered_as_a_history_filter(client, operator):
    client.force_login(operator)

    response = client.get("/notifications/")

    assert response.status_code == 200
    assert EventType.INVITE_REQUESTED not in dict(response.context["event_types"])


@pytest.mark.django_db
def test_saving_preferences_does_not_switch_it_off(client, operator, mailoutbox):
    client.force_login(operator)

    response = client.post("/notifications/preferences/", {"quiet_hours_timezone": "UTC"})

    assert response.status_code == 302
    assert not NotificationPreference.objects.filter(user=operator, event_type=EventType.INVITE_REQUESTED).exists()
    notice = notify(operator, EventType.INVITE_REQUESTED, "Invite request from Ana")
    assert notice is not None and notice.shown_in_app is True
    assert _queued_emails(operator).count() == 1  # its email is still on, waiting for the digest


@pytest.mark.django_db
def test_the_daily_digest_lists_every_invite_request_in_one_email(operator, mailoutbox):
    with frozen_now(at(9)):
        notify(operator, EventType.INVITE_REQUESTED, "Invite request from Ana (Northwind)", "Ana at Northwind")
    with frozen_now(at(15)):
        notify(operator, EventType.INVITE_REQUESTED, "Invite request from Bo (Contoso)", "Bo at Contoso")
    with frozen_now(at(DAILY_DIGEST_HOUR - 1, day=18)):
        assert send_batched_email_digests() == 0
    assert mailoutbox == []

    with frozen_now(at(DAILY_DIGEST_HOUR, 1, day=18)):
        assert send_batched_email_digests() == 1

    assert len(mailoutbox) == 1
    digest = mailoutbox[0]
    assert digest.to == ["op@smbean.example"]
    assert digest.subject.startswith("2 invite requests")
    assert "Invite request from Ana (Northwind)" in digest.body
    assert "Invite request from Bo (Contoso)" in digest.body
    assert not _queued_emails(operator).exists()
    with frozen_now(at(DAILY_DIGEST_HOUR, 30, day=18)):
        assert send_batched_email_digests() == 0
    assert len(mailoutbox) == 1


@pytest.mark.django_db
def test_a_burst_does_not_send_the_digest_early(operator, mailoutbox):
    """Other batched events mail at once when ten are waiting; a burst of invite requests is exactly
    what this holds back."""
    with frozen_now(at(9)):
        for index in range(30):
            notify(operator, EventType.INVITE_REQUESTED, f"Invite request {index}")
    with frozen_now(at(10)):
        assert send_batched_email_digests() == 0

    assert mailoutbox == []
    assert _queued_emails(operator).count() == 30


@pytest.mark.django_db
def test_requests_all_day_spend_one_of_the_operators_emails_and_never_their_alerts(operator, settings, mailoutbox):
    """Six requests an hour, every hour, each one past the short batching window, with the sweep
    running between them: the operator still gets every alert, and one invite email a day."""
    for name, value in PRODUCTION_EMAIL.items():
        setattr(settings, name, value)

    for hour in range(DAILY_DIGEST_HOUR + 1, 24):
        for minute in range(0, 60, 10):
            with frozen_now(at(hour, minute)):
                notify(operator, EventType.INVITE_REQUESTED, f"Invite request {hour}:{minute:02}")
            with frozen_now(at(hour, minute + 7)):
                send_batched_email_digests()
        with frozen_now(at(hour, 59)):
            notify(operator, EventType.AGENCY_ALERT, f"Alert at {hour}")

    alerts = [m for m in mailoutbox if m.subject.startswith("Alert at")]
    assert len(alerts) == 24 - (DAILY_DIGEST_HOUR + 1)
    assert not [m for m in mailoutbox if "invite request" in m.subject.lower()]

    with frozen_now(at(DAILY_DIGEST_HOUR, 1, day=18)):
        assert send_batched_email_digests() == 1
    invites = [m for m in mailoutbox if "invite request" in m.subject.lower()]
    assert len(invites) == 1


@pytest.mark.django_db
def test_quiet_hours_keep_an_invite_request_in_the_bell_only(operator, mailoutbox):
    QuietHours.objects.create(
        user=operator, is_enabled=True, start_time=datetime.time(22), end_time=datetime.time(7), timezone="UTC"
    )
    with frozen_now(at(23)):
        notice = notify(operator, EventType.INVITE_REQUESTED, "Invite request from Ana")

    assert notice is not None and notice.shown_in_app is True
    assert not NotificationDelivery.objects.filter(notification=notice, channel=Channel.EMAIL).exists()
    with frozen_now(at(DAILY_DIGEST_HOUR, 1, day=18)):
        assert send_batched_email_digests() == 0
    assert mailoutbox == []
