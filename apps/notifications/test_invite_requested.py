"""The ``invite_requested`` event: reaches operators' bell and email, never their preference lists.

Only platform operators receive it (``apps.marketing.views.request_invite``), so
it is not something a person chooses to hear about: it stays out of the
preference matrix, and saving that matrix must not quietly switch it off.
"""

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.notifications.engine import DEFAULT_CHANNELS, notify
from apps.notifications.models import Channel, EventType, NotificationPreference


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
def test_it_shows_in_the_bell_and_sends_email(operator, mailoutbox):
    notice = notify(operator, EventType.INVITE_REQUESTED, "Invite request from Ana", "Ana at Northwind")

    assert notice is not None
    assert notice.shown_in_app is True
    assert [m.to for m in mailoutbox] == [["op@smbean.example"]]


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
    assert len(mailoutbox) == 1
