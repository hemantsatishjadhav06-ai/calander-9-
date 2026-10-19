"""The manager inbox: who gets told, how often, when, and never across workspaces or to clients."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.approvals.test_gate import _pending, _world
from apps.composer.models import PostMedia
from apps.media_library.models import MediaAsset
from apps.members.models import CustomRole, OrgMembership, WorkspaceMembership
from apps.studio import guards
from apps.studio.models import AgencySettings
from apps.telegram import inbox, outbox
from apps.telegram.models import TelegramAction, TelegramChat, TelegramConnection, TelegramDelivery, TelegramUserLink
from apps.workspaces.models import Workspace

pytestmark = pytest.mark.django_db
IST = ZoneInfo("Asia/Kolkata")
NOON = datetime(2026, 10, 19, 12, 0, tzinfo=IST)


@pytest.fixture(autouse=True)
def daytime(monkeypatch):
    """Quiet hours are real; tests pin the clock to midday unless they test the clock itself."""
    monkeypatch.setattr(timezone, "now", lambda: NOON)


def _person(email, name):
    return User.objects.create_user(email=email, password="not-used", name=name, tos_accepted_at=timezone.now())


@pytest.fixture
def agency(db, monkeypatch):
    """A workspace with a lead, a backup, a third approver, an editor and a client, all paired."""
    from apps.telegram import tasks

    monkeypatch.setattr(tasks, "send_delivery", lambda *a, **k: None)
    ws, lead, editor, client, account = _world()
    org = ws.organization
    backup, approver = _person("backup@example.com", "Backup"), _person("approver2@example.com", "Approver")
    for user in (backup, approver):
        OrgMembership.objects.create(organization=org, user=user, org_role="member")
        WorkspaceMembership.objects.create(workspace=ws, user=user, workspace_role="manager")
    AgencySettings.objects.create(workspace=ws, lead=lead, backup=backup)
    connection = TelegramConnection.objects.create(
        workspace=ws,
        token="123456:" + "f" * 32,
        webhook_secret="inbox-secret",
        bot_id=123456,
        bot_username="inbox_bot",
        is_active=True,
        approvals_enabled=True,
        webhook_status="active",
    )
    users = {"lead": lead, "backup": backup, "approver": approver, "editor": editor, "client": client}
    links = {
        key: TelegramUserLink.objects.create(connection=connection, user=user, telegram_user_id=1000 + index)
        for index, (key, user) in enumerate(users.items())
    }
    return SimpleNamespace(org=org, ws=ws, users=users, links=links, connection=connection, account=account)


def _ids(rows):
    return [user.pk for user, _ in rows]


def _private_chat(agency, key):
    return TelegramChat.objects.get(connection=agency.connection, audience="private", private_user=agency.users[key])


def test_approvers_are_lead_backup_then_paired_internal_approvers(agency):
    users = agency.users
    assert _ids(inbox.approvers(agency.ws)) == [users["lead"].pk, users["backup"].pk, users["approver"].pk]
    TelegramUserLink.objects.filter(pk=agency.links["approver"].pk).update(is_active=False)
    assert _ids(inbox.approvers(agency.ws)) == [users["lead"].pk, users["backup"].pk]
    # /mute removes a person from "needs you" messages; the briefing still includes them.
    TelegramUserLink.objects.filter(pk=agency.links["backup"].pk).update(notify_needs_you=False)
    assert _ids(inbox.approvers(agency.ws)) == [users["lead"].pk]
    assert _ids(inbox.approvers(agency.ws, include_muted=True)) == [users["lead"].pk, users["backup"].pk]
    # No active connection, nobody to tell.
    TelegramConnection.objects.filter(pk=agency.connection.pk).update(is_active=False)
    assert inbox.approvers(agency.ws) == [] and inbox.tell(agency.ws, "x", source_key="k", event="test") == 0


def test_clients_and_non_approvers_never_qualify_whatever_their_role_says(agency):
    role = CustomRole.objects.create(
        organization=agency.org,
        name="VIP client",
        permissions={"client_facing": True, "approve_posts": True, "create_posts": True},
    )
    WorkspaceMembership.objects.filter(user=agency.users["client"], workspace=agency.ws).update(custom_role=role)
    AgencySettings.objects.filter(workspace=agency.ws).update(lead=agency.users["client"])
    told = inbox.tell(agency.ws, "The team needs you.", source_key="unit:clients", event="test")
    assert told == 3
    recipients = set(TelegramDelivery.objects.values_list("chat__private_user_id", flat=True))
    assert recipients == {agency.users["lead"].pk, agency.users["backup"].pk, agency.users["approver"].pk}
    assert not TelegramChat.objects.filter(private_user__in=[agency.users["client"], agency.users["editor"]]).exists()


def test_tell_reaches_each_approver_once_in_their_own_chat_and_dedupes(agency):
    assert inbox.tell(agency.ws, "The team needs you.", source_key="unit:1", event="test") == 3
    rows = list(TelegramDelivery.objects.select_related("chat"))
    assert len(rows) == 3
    assert all(row.chat.audience == "private" and row.chat.chat_type == "private" for row in rows)
    assert {row.chat.private_user_id for row in rows} == {
        agency.users["lead"].pk,
        agency.users["backup"].pk,
        agency.users["approver"].pk,
    }
    assert all(row.payload["text"] == "The team needs you." for row in rows)
    assert all(row.source_key.startswith("inbox:unit:1:user:") for row in rows)
    inbox.tell(agency.ws, "The team needs you.", source_key="unit:1", event="test")
    assert TelegramDelivery.objects.count() == 3
    assert inbox.tell(agency.ws, "x", source_key="unit:2", event="test", exclude_user_id=agency.users["lead"].pk) == 2
    assert inbox.tell(agency.ws, "x", source_key="unit:3", event="test", only_user_id=agency.users["approver"].pk) == 1
    assert TelegramDelivery.objects.count() == 6


def test_forty_messages_a_day_then_quiet_until_the_briefing(agency, monkeypatch):
    noon = datetime(2026, 10, 19, 12, 0, tzinfo=IST)
    monkeypatch.setattr(timezone, "now", lambda: noon)
    inbox.tell(agency.ws, "first", source_key="unit:cap:0", event="test")
    chat = _private_chat(agency, "lead")
    TelegramDelivery.objects.bulk_create(
        TelegramDelivery(
            connection=agency.connection, chat=chat, source_key=f"inbox:fill:{i}:user:x:part:0", payload={}
        )
        for i in range(inbox.DAILY_CAP - 1)
    )
    # Continuation parts of one long message do not count against the cap.
    TelegramDelivery.objects.create(
        connection=agency.connection, chat=chat, source_key="inbox:fill:0:user:x:part:1", payload={}
    )
    assert inbox.sent_today(chat, agency.ws) == inbox.DAILY_CAP
    assert inbox.tell(agency.ws, "more", source_key="unit:cap:1", event="test") == 2
    assert not TelegramDelivery.objects.filter(chat=chat, source_key__startswith="inbox:unit:cap:1").exists()
    # A new local day starts the count again.
    monkeypatch.setattr(timezone, "now", lambda: noon + timedelta(days=1))
    assert inbox.tell(agency.ws, "next day", source_key="unit:cap:2", event="test") == 3


def test_quiet_hours_hold_everything_except_reminders_and_failed_deliveries(agency, monkeypatch):
    late = datetime(2026, 10, 19, 23, 30, tzinfo=IST)
    monkeypatch.setattr(timezone, "now", lambda: late)
    assert inbox.is_quiet(agency.ws)
    assert inbox.tell(agency.ws, "late draft", source_key="unit:quiet", event="draft_ready") == 0
    assert not TelegramDelivery.objects.exists()
    assert inbox.tell(agency.ws, "still waiting", source_key="unit:reminder", event="approval_reminder") == 3
    assert inbox.tell(agency.ws, "failed", source_key="unit:failed", event="delivery_failed") == 3
    early = datetime(2026, 10, 20, 6, 59, tzinfo=IST)
    monkeypatch.setattr(timezone, "now", lambda: early)
    assert inbox.tell(agency.ws, "early", source_key="unit:early", event="autopilot_planned") == 0
    monkeypatch.setattr(timezone, "now", lambda: early + timedelta(minutes=2))
    assert inbox.tell(agency.ws, "morning", source_key="unit:morning", event="autopilot_planned") == 3


def test_workspaces_stay_separate(agency):
    other = Workspace.objects.create(organization=agency.org, name="Other brand", timezone="Asia/Kolkata")
    WorkspaceMembership.objects.create(workspace=other, user=agency.users["lead"], workspace_role="owner")
    other_connection = TelegramConnection.objects.create(
        workspace=other, token="654321:" + "e" * 32, webhook_secret="other", bot_id=654321, is_active=True
    )
    TelegramUserLink.objects.create(connection=other_connection, user=agency.users["lead"], telegram_user_id=1001)
    assert _ids(inbox.approvers(other)) == [agency.users["lead"].pk]
    assert inbox.tell(other, "other brand", source_key="unit:other", event="test") == 1
    row = TelegramDelivery.objects.get()
    assert row.connection_id == other_connection.pk and row.chat.connection_id == other_connection.pk
    assert row.chat.conversation.workspace_id == other.pk
    assert not TelegramChat.objects.filter(connection=agency.connection).exists()


def test_a_post_arrives_as_its_review_card_when_the_person_may_act(agency):
    post = _pending(agency.ws, agency.users["editor"], agency.account, when=timezone.now() + timedelta(days=2))
    assert inbox.tell(agency.ws, "", source_key="draft:1", event="draft_ready", post=post) == 3
    row = TelegramDelivery.objects.get(chat=_private_chat(agency, "lead"))
    labels = [button["text"] for line in row.payload["reply_markup"]["inline_keyboard"] for button in line]
    assert labels == ["Approve only", "Approve & schedule", "Reject this version", "Request a revised version"]
    assert "Nothing publishes without your approval" in row.payload["text"]
    assert TelegramAction.objects.filter(post=post, used_at__isnull=True).count() == 12  # four per approver
    assert not TelegramDelivery.objects.filter(chat__private_user=agency.users["editor"]).exists()
    # The same draft never arrives twice.
    inbox.tell(agency.ws, "", source_key="draft:1", event="draft_ready", post=post)
    assert TelegramDelivery.objects.count() == 3


def test_a_post_the_card_cannot_carry_arrives_as_a_preview_with_a_link(agency):
    post = _pending(agency.ws, agency.users["editor"], agency.account, caption="Two pictures")
    for index in range(2):
        asset = MediaAsset.objects.create(
            workspace=agency.ws,
            organization=agency.org,
            filename=f"picture-{index}.jpg",
            media_type="image",
            file_size=10,
            processing_status="completed",
        )
        PostMedia.objects.create(post=post, media_asset=asset, position=index)
    assert inbox.tell(agency.ws, "", source_key="draft:2", event="draft_ready", post=post) == 3
    chat = _private_chat(agency, "lead")
    album = TelegramDelivery.objects.get(chat=chat, kind="album")
    assert album.payload["method"] == "sendMediaGroup" and len(album.payload["photo_asset_ids"]) == 2
    text = TelegramDelivery.objects.get(chat=chat, kind="message")
    assert "Two pictures" in text.payload["text"] and "2 pictures" in text.payload["text"]
    button = text.payload["reply_markup"]["inline_keyboard"][0][0]
    assert button["text"] == "Open to approve" and button["url"].startswith("http://localhost:8000/")
    assert "tab=approvals" in button["url"]
    assert not TelegramAction.objects.exists()


def test_cards_are_never_built_inside_agency_work(agency):
    post = _pending(agency.ws, agency.users["editor"], agency.account)
    with guards.agent_work("pipeline"):
        assert inbox.tell(agency.ws, "", source_key="draft:3", event="draft_ready", post=post) == 0
        assert inbox.tell(agency.ws, "plain line", source_key="plain:1", event="test") == 3
    assert not TelegramAction.objects.exists()
    assert TelegramDelivery.objects.count() == 3
    # Outside it (the receipt sweep), the card goes out.
    assert inbox.tell(agency.ws, "", source_key="draft:3", event="draft_ready", post=post) == 3
    assert TelegramAction.objects.exists()


def test_link_buttons_only_point_at_the_app(agency):
    inbox.tell(agency.ws, "hello", source_key="unit:link", event="test")
    chat = _private_chat(agency, "lead")
    markup = outbox.link_keyboard(outbox.link_button("Open Home", "/studio/x/"))
    row = outbox.queue_message(chat, "x", source_key="link:ok", reply_markup=markup)[0]
    assert row.payload["reply_markup"] == {
        "inline_keyboard": [[{"text": "Open Home", "url": "http://localhost:8000/studio/x/"}]]
    }
    for url in ("https://example.com/", "http://localhost:8000@evil.example/", "http://localhost:8000.evil/x"):
        with pytest.raises(ValueError):
            outbox.queue_message(
                chat, "x", source_key=f"link:{url}", reply_markup={"inline_keyboard": [[{"text": "x", "url": url}]]}
            )
    assert outbox.link_button("Open", "//evil.example") is None
