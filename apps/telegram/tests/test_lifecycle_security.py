"""Re-pairing never authorizes requests queued under an earlier pairing."""

import json
from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.test import RequestFactory
from django.utils import timezone

from apps.members.models import WorkspaceMembership
from apps.studio.models import AgencyJob, Conversation, Message
from apps.telegram import processing, provisioning, tasks
from apps.telegram.models import (
    TelegramAction,
    TelegramChat,
    TelegramConnection,
    TelegramDelivery,
    TelegramUpdate,
    TelegramUserLink,
)
from apps.telegram.webhooks import ingress
from apps.workspaces.models import Workspace

pytestmark = pytest.mark.django_db


@pytest.fixture
def hub(organization, org_owner, monkeypatch):
    workspace = Workspace.objects.create(organization=organization, name="Lifecycle security")
    WorkspaceMembership.objects.create(workspace=workspace, user=org_owner, workspace_role="owner")
    monkeypatch.setattr(tasks, "process_update", Mock())
    monkeypatch.setattr(tasks, "send_delivery", Mock())
    api = Mock()
    api.get_chat_member.side_effect = lambda chat_id, user_id: {"status": "administrator", "user": {"id": user_id}}
    monkeypatch.setattr(provisioning, "BotAPI", Mock(return_value=api))
    conn = TelegramConnection.objects.create(
        workspace=workspace,
        bot_id=123456,
        token="123456:" + "f" * 32,
        webhook_secret="test-secret",
        is_active=True,
    )
    link = TelegramUserLink.objects.create(connection=conn, user=org_owner, telegram_user_id=99)
    conversation = Conversation.objects.create(workspace=workspace, audience="internal", created_by=org_owner)
    chat = TelegramChat.objects.create(
        connection=conn,
        chat_id=-100123,
        chat_type="supergroup",
        audience="team",
        conversation=conversation,
    )
    return conn, link, chat


def pending(conn, chat, update_id, *, sender=99, text="/brief Prepare an old paid request"):
    return TelegramUpdate.objects.create(
        connection=conn,
        update_id=update_id,
        payload={
            "update_id": update_id,
            "_binding": processing.connection_epoch(conn),
            "message": {
                "from": {"id": sender, "is_bot": False},
                "chat": {"id": chat.chat_id, "type": chat.chat_type},
                "text": text,
            },
        },
    )


def re_pair_group(conn, link, chat):
    _, nonce = provisioning.issue_pairing(conn, link.user, purpose="chat", audience="team")
    return provisioning.consume_chat_pairing(conn, nonce, link.telegram_user_id, chat.chat_id, chat.chat_type)


@pytest.mark.parametrize("event", ["removed", "migration"])
def test_lifecycle_suspension_holds_old_commands_and_callbacks_before_same_group_repair(hub, monkeypatch, event):
    conn, link, chat = hub
    old = pending(conn, chat, 11)
    action = TelegramAction.objects.create(
        chat=chat,
        user_link=link,
        kind="prepare",
        token_digest="a" * 64,
        expires_at=timezone.now() + timedelta(minutes=10),
    )
    if event == "removed":
        payload = {
            "my_chat_member": {
                "chat": {"id": chat.chat_id},
                "new_chat_member": {"user": {"id": conn.bot_id}, "status": "kicked"},
            }
        }
    else:
        payload = {"message": {"chat": {"id": chat.chat_id}, "migrate_to_chat_id": -100999}}
    lifecycle = TelegramUpdate.objects.create(
        connection=conn,
        update_id=12,
        payload={"update_id": 12, "_binding": processing.connection_epoch(conn), **payload},
    )
    assert processing.process_one(lifecycle.pk) == "processed"
    old.refresh_from_db()
    action.refresh_from_db()
    assert old.status == "failed" and action.used_at is not None
    restored = re_pair_group(conn, link, chat)
    assert restored.is_active
    handler = Mock()
    monkeypatch.setattr("apps.telegram.conversations.handle_message", handler)
    assert processing.process_one(old.pk) == "skipped"
    handler.assert_not_called()


def test_unpair_holds_only_that_persons_group_requests_and_responses(hub):
    conn, link, chat = hub
    own = pending(conn, chat, 21)
    other = pending(conn, chat, 22, sender=100)
    reply = TelegramDelivery.objects.create(
        connection=conn, chat=chat, source_key="update:21:response:part:0", payload={}
    )
    other_reply = TelegramDelivery.objects.create(
        connection=conn, chat=chat, source_key="update:22:response:part:0", payload={}
    )
    provisioning.unpair(conn, link.user)
    own.refresh_from_db()
    other.refresh_from_db()
    reply.refresh_from_db()
    other_reply.refresh_from_db()
    assert own.status == reply.status == "failed"
    assert other.status == other_reply.status == "pending"
    chat.refresh_from_db()
    assert chat.is_active


def test_request_arriving_while_unpaired_cannot_acquire_repaired_identity(hub, monkeypatch):
    conn, link, chat = hub
    provisioning.unpair(conn, link.user)
    while_unpaired = pending(conn, chat, 31)
    _, nonce = provisioning.issue_pairing(conn, link.user)
    provisioning.consume_user_pairing(conn, nonce, link.telegram_user_id)
    handler = Mock()
    monkeypatch.setattr("apps.telegram.conversations.handle_message", handler)
    assert processing.process_one(while_unpaired.pk) == "skipped"
    handler.assert_not_called()


def test_request_arriving_while_group_disabled_cannot_acquire_new_group_pairing(hub, monkeypatch):
    conn, link, chat = hub
    processing._disable_chat(chat, source_key="removed", reason="The bot was removed.")
    while_disabled = pending(conn, chat, 41)
    re_pair_group(conn, link, chat)
    handler = Mock()
    monkeypatch.setattr("apps.telegram.conversations.handle_message", handler)
    assert processing.process_one(while_disabled.pk) == "skipped"
    handler.assert_not_called()


def test_manual_epoch_change_rejects_uninvalidated_old_request(hub, monkeypatch):
    conn, link, chat = hub
    old = pending(conn, chat, 51)
    link.save(update_fields=["updated_at"])
    handler = Mock()
    monkeypatch.setattr("apps.telegram.conversations.handle_message", handler)
    assert processing.process_one(old.pk) == "failed"
    handler.assert_not_called()


def test_group_pairing_current_update_finishes_while_older_requests_are_held(hub):
    conn, link, chat = hub
    older = pending(conn, chat, 61)
    _, nonce = provisioning.issue_pairing(conn, link.user, purpose="chat", audience="team")
    pairing = pending(conn, chat, 62, text=f"/pair {nonce}")
    assert processing.process_one(pairing.pk) == "processed"
    older.refresh_from_db()
    assert older.status == "failed"
    assert TelegramDelivery.objects.filter(chat=chat, source_key="update:62:response:part:0").exists()


def test_inflight_response_is_not_queued_after_identity_unpair(hub, monkeypatch):
    conn, link, chat = hub
    row = pending(conn, chat, 71)

    def handler(connection, payload):
        provisioning.unpair(conn, link.user)
        return {"text": "An old response must stay held."}

    monkeypatch.setattr("apps.telegram.conversations.handle_message", handler)
    assert processing.process_one(row.pk) == "failed"
    assert not TelegramDelivery.objects.filter(source_key="update:71:response:part:0").exists()


@pytest.mark.parametrize(
    "forward_marker", [{"forward_sender_name": "Hidden sender"}, {"forward_date": 100}, {"is_automatic_forward": True}]
)
def test_legacy_forward_markers_cannot_pair_an_identity(hub, forward_marker):
    conn, link, _ = hub
    _, nonce = provisioning.issue_pairing(conn, link.user)
    with pytest.raises(provisioning.TelegramPermissionDenied):
        provisioning.consume_pairing_message(
            conn,
            {
                "text": f"/start {nonce}",
                "from": {"id": 777, "is_bot": False},
                "chat": {"id": 777, "type": "private"},
                **forward_marker,
            },
        )


@pytest.mark.parametrize("kind", ["animation", "video_note"])
def test_unsupported_video_fields_survive_ingress_and_do_not_start_paid_work(hub, kind):
    conn, link, chat = hub
    update = {
        "update_id": 81,
        "message": {
            "from": {"id": link.telegram_user_id, "is_bot": False},
            "chat": {"id": chat.chat_id, "type": chat.chat_type},
            "caption": "/brief Build a campaign from this video",
            kind: {"file_id": "unsupported-video"},
        },
    }
    request = RequestFactory().post(
        "/webhooks/telegram/",
        data=json.dumps(update),
        content_type="application/json",
        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=conn.webhook_secret,
    )
    assert ingress(request, conn.pk).status_code == 200
    row = TelegramUpdate.objects.get(connection=conn, update_id=81)
    assert kind in row.payload["message"]
    assert processing.process_one(row.pk) == "processed"
    assert not Message.objects.exists() and not AgencyJob.objects.exists()
    assert "Voice and video are not available here yet" in TelegramDelivery.objects.get(chat=chat).payload["text"]
