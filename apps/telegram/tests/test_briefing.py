"""The morning briefing: code-built lines, once a day, to everyone who approves, muted or not."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.approvals.test_gate import _pending
from apps.notifications.models import Notification
from apps.studio import briefing, trust
from apps.studio.models import StudioBrief
from apps.telegram.models import TelegramDelivery, TelegramUserLink
from apps.telegram.tests.test_inbox import agency, daytime  # noqa: F401

pytestmark = pytest.mark.django_db


def test_build_is_plain_words_from_the_dashboard_queries(agency):  # noqa: F811
    data = briefing.build(agency.ws)
    assert data["lines"][0].startswith("Good morning")
    assert "Nothing is waiting for your approval." in data["lines"]
    assert "Nothing is scheduled to go out today." in data["lines"]
    assert data["waiting"] == [] and data["counts"]["made"] == 0
    assert data["links"]["approvals"] == "http://localhost:8000/" + data["links"]["approvals"].split("/", 3)[3]
    assert "tab=approvals" in data["links"]["approvals"] and data["links"]["home"].endswith("/")
    StudioBrief.objects.create(
        workspace=agency.ws,
        author=agency.users["lead"],
        idea="Site visit post",
        status="ready",
        stage="done",
        finished_at=timezone.now(),
    )
    data = briefing.build(agency.ws)
    assert any(line.startswith("Waiting for you: 1 post") and "Site visit post" in line for line in data["lines"])
    assert "Made since yesterday: 1 draft." in data["lines"]
    assert len(data["waiting"]) == 1 and data["text"] == "\n".join(data["lines"])


def test_send_daily_tells_everyone_once_a_day_including_muted_people(agency):  # noqa: F811
    TelegramUserLink.objects.filter(pk=agency.links["approver"].pk).update(notify_needs_you=False)
    assert briefing.send_daily(agency.ws) == 3
    notes = Notification.objects.filter(event_type="daily_briefing")
    assert {note.user for note in notes} == {agency.users["lead"], agency.users["backup"], agency.users["approver"]}
    assert all(note.data["workspace_id"] == str(agency.ws.pk) and note.data["day"] for note in notes)
    rows = list(TelegramDelivery.objects.select_related("chat"))
    assert {row.chat.private_user_id for row in rows} == set(notes.values_list("user", flat=True))
    labels = [button["text"] for line in rows[0].payload["reply_markup"]["inline_keyboard"] for button in line]
    assert labels == ["Open approvals", "Open Home"]
    assert "Good morning" in rows[0].payload["text"]
    briefing.send_daily(agency.ws)
    assert Notification.objects.filter(event_type="daily_briefing").count() == 3
    assert TelegramDelivery.objects.count() == 3


def test_send_daily_brings_the_first_waiting_post_as_its_card(agency):  # noqa: F811
    post = _pending(agency.ws, agency.users["editor"], agency.account, when=timezone.now() + timedelta(days=2))
    brief = StudioBrief.objects.create(
        workspace=agency.ws,
        author=agency.users["lead"],
        idea="Waiting draft",
        post=post,
        status="ready",
        stage="done",
        finished_at=timezone.now(),
    )
    brief.trust_snapshot = trust.capture(brief)
    brief.save(update_fields=["trust_snapshot"])
    briefing.send_daily(agency.ws)
    lead_rows = TelegramDelivery.objects.filter(chat__private_user=agency.users["lead"])
    assert lead_rows.count() == 2
    card = lead_rows.get(source_key__contains="first-post")
    labels = [button["text"] for line in card.payload["reply_markup"]["inline_keyboard"] for button in line]
    assert "Approve only" in labels and "Nothing publishes without your approval" in card.payload["text"]
    assert post.platform_posts.get().status == "pending_review"
