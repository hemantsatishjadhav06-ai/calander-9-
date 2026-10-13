import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.db import connection as db_connection
from django.db import connections
from django.test import RequestFactory
from django.utils import timezone

from apps.studio.models import Conversation, Message
from apps.telegram.models import TelegramChat, TelegramConnection, TelegramDelivery, TelegramUpdate
from apps.telegram.processing import connection_epoch, process_one, recover_stale_updates
from apps.telegram.webhooks import MAX_UPDATE_BYTES, ingress
from apps.workspaces.models import Workspace

pytestmark = pytest.mark.django_db


def create_hub(organization, user, monkeypatch):
    from apps.telegram import tasks

    monkeypatch.setattr(tasks, "process_update", Mock())
    monkeypatch.setattr(tasks, "send_delivery", Mock())
    workspace = Workspace.objects.create(organization=organization, name="Telegram test client")
    conn = TelegramConnection.objects.create(
        workspace=workspace,
        token="123456:" + "f" * 32,
        webhook_secret="test-shared-secret",
        bot_id=123456,
        bot_username="fake_test_bot",
        is_active=True,
        created_by=user,
    )
    conversation = Conversation.objects.create(workspace=workspace, audience="client", created_by=user)
    chat = TelegramChat.objects.create(
        connection=conn, chat_id=-123, chat_type="supergroup", audience="client", conversation=conversation
    )
    return conn, chat


@pytest.fixture
def hub(organization, user, monkeypatch):
    return create_hub(organization, user, monkeypatch)


def payload(update_id=1, **changes):
    message = {
        "message_id": 7,
        "chat": {"id": -123, "type": "supergroup"},
        "from": {"id": 99},
        "text": "A client request",
    }
    message.update(changes)
    return {"update_id": update_id, "message": message}


def authenticated(conn, value):
    return {**value, "_binding": connection_epoch(conn)}


def request(conn, data, *, secret="test-shared-secret"):
    body = json.dumps(data) if not isinstance(data, bytes) else data
    value = RequestFactory().post(
        "/webhooks/telegram/", data=body, content_type="application/json", HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=secret
    )
    return ingress(value, conn.pk)


def test_secret_and_active_connection_required_before_queue(hub):
    conn, _ = hub
    assert request(conn, payload(), secret="incorrect").status_code == 403
    conn.is_active = False
    conn.save(update_fields=["is_active"])
    assert request(conn, payload()).status_code == 403
    assert TelegramUpdate.objects.count() == 0


@pytest.mark.parametrize(
    "data",
    [
        b"not JSON",
        [],
        {"update_id": True},
        {"update_id": -1},
        {"update_id": 2**63},
        {"update_id": 1, "message": {"chat": {"id": True, "type": "group"}}},
        payload(text="a" * 4097),
    ],
)
def test_malformed_shape_is_rejected(hub, data):
    conn, _ = hub
    assert request(conn, data).status_code == 400
    assert not TelegramUpdate.objects.exists()


def test_oversized_body_is_rejected_before_json_parse(hub):
    conn, _ = hub
    assert request(conn, b"x" * (MAX_UPDATE_BYTES + 1)).status_code == 413
    assert not TelegramUpdate.objects.exists()


def managed_event(update_id=301, **overrides):
    event = {
        "user": {"id": 99, "is_bot": False, "first_name": "Private owner name"},
        "bot": {"id": 654321, "is_bot": True, "username": "separate_client_bot"},
        **overrides,
    }
    return {"update_id": update_id, "managed_bot": event}


@pytest.mark.parametrize(
    "event",
    [
        managed_event(user={"id": True, "is_bot": False}),
        managed_event(user={"id": 99, "is_bot": True}),
        managed_event(bot={"id": 654321, "is_bot": False, "username": "separate_bot"}),
        managed_event(bot={"id": 654321, "is_bot": True, "username": "unsafe/url"}),
        {**managed_event(), "message": payload()["message"]},
    ],
)
def test_managed_update_rejects_malformed_identity_or_ambiguous_shape(hub, event):
    conn, _ = hub
    assert request(conn, event).status_code == 400
    assert not TelegramUpdate.objects.exists()


def test_managed_update_requires_webhook_secret_and_only_queues_minimal_identity(hub, monkeypatch):
    conn, _ = hub
    handler = Mock(side_effect=AssertionError("No manager provisioning may run inside ingress"))
    monkeypatch.setattr("apps.telegram.managed.process_managed_bot_update", handler)
    assert request(conn, managed_event(), secret="incorrect").status_code == 403
    assert not TelegramUpdate.objects.exists()
    assert request(conn, managed_event()).status_code == 200
    assert request(conn, managed_event()).status_code == 200
    row = TelegramUpdate.objects.get()
    assert row.payload["managed_bot"] == {
        "user": {"id": 99, "is_bot": False},
        "bot": {"id": 654321, "is_bot": True, "username": "separate_client_bot"},
    }
    handler.assert_not_called()


def test_managed_event_dispatches_once_after_authenticated_worker_claim(hub, monkeypatch):
    conn, _ = hub
    handler = Mock(return_value={"status": "ignored"})
    monkeypatch.setattr("apps.telegram.managed.process_managed_bot_update", handler)
    assert request(conn, managed_event()).status_code == 200
    row = TelegramUpdate.objects.get()
    assert process_one(row.pk) == "processed"
    assert process_one(row.pk) == "skipped"
    handler.assert_called_once_with(conn, row.payload["managed_bot"])


def test_managed_event_cannot_dispatch_under_rotated_manager_connection(hub, monkeypatch):
    conn, _ = hub
    handler = Mock()
    monkeypatch.setattr("apps.telegram.managed.process_managed_bot_update", handler)
    assert request(conn, managed_event()).status_code == 200
    row = TelegramUpdate.objects.get()
    conn.webhook_secret = "changed-manager-secret"
    conn.save(update_fields=["webhook_secret"])
    assert process_one(row.pk) == "failed"
    handler.assert_not_called()


def test_ingress_is_encrypted_minimal_idempotent_and_only_queues(hub, django_capture_on_commit_callbacks, monkeypatch):
    from apps.telegram import tasks

    conn, _ = hub
    untrusted = payload(unused_customer_secret="discard-me")
    untrusted["extraneous"] = "discard-top"
    handler = Mock(side_effect=AssertionError("Ingress must not execute conversation work"))
    monkeypatch.setattr("apps.telegram.conversations.handle_message", handler)
    with django_capture_on_commit_callbacks(execute=True):
        assert request(conn, untrusted).status_code == 200
        assert request(conn, untrusted).status_code == 200
    assert TelegramUpdate.objects.count() == 1
    row = TelegramUpdate.objects.get()
    assert "extraneous" not in row.payload
    assert "unused_customer_secret" not in row.payload["message"]
    assert tasks.process_update.call_count == 1
    handler.assert_not_called()
    with db_connection.cursor() as cursor:
        cursor.execute("SELECT payload FROM telegram_update WHERE id = %s", [row.pk])
        encrypted = cursor.fetchone()[0]
    assert "A client request" not in encrypted
    assert "from" not in encrypted


def test_processing_once_suppresses_input_echo_and_queues_safe_response(
    hub, monkeypatch, django_capture_on_commit_callbacks
):
    conn, chat = hub
    row = TelegramUpdate.objects.create(connection=conn, update_id=2, payload=authenticated(conn, payload(2)))

    def handle(connection, update):
        Message.objects.create(conversation=chat.conversation, author_kind="client", body="incoming echo")
        return {"text": "The team is preparing the requested draft.", "chat_id": -999}

    handler = Mock(side_effect=handle)
    monkeypatch.setattr("apps.telegram.conversations.handle_message", handler)
    with django_capture_on_commit_callbacks(execute=True):
        assert process_one(row.pk) == "processed"
        assert process_one(row.pk) == "skipped"
    handler.assert_called_once()
    deliveries = list(TelegramDelivery.objects.all())
    assert len(deliveries) == 1
    assert deliveries[0].chat_id == chat.pk
    assert "incoming echo" not in deliveries[0].payload["text"]
    row.refresh_from_db()
    assert row.attempts == 1 and row.status == "processed"


def test_processing_exception_and_stale_claim_are_held_without_model_replay(hub, monkeypatch):
    conn, _ = hub
    handler = Mock(side_effect=RuntimeError("https://api.telegram.org/botSECRET_TOKEN/private"))
    monkeypatch.setattr("apps.telegram.conversations.handle_message", handler)
    failed = TelegramUpdate.objects.create(connection=conn, update_id=3, payload=authenticated(conn, payload(3)))
    assert process_one(failed.pk) == "failed"
    assert process_one(failed.pk) == "skipped"
    failed.refresh_from_db()
    assert "SECRET_TOKEN" not in failed.error
    stale = TelegramUpdate.objects.create(
        connection=conn,
        update_id=4,
        payload=payload(4),
        status="working",
        attempts=1,
        claimed_at=timezone.now() - timedelta(hours=1),
    )
    assert recover_stale_updates(limit=1) == 1
    assert process_one(stale.pk) == "skipped"
    stale.refresh_from_db()
    assert stale.status == "failed" and "Inspect" in stale.error
    assert handler.call_count == 1


def test_group_migration_disables_old_binding_without_taking_over_another_client(hub):
    conn, chat = hub
    row = TelegramUpdate.objects.create(
        connection=conn, update_id=5, payload=authenticated(conn, payload(5, migrate_to_chat_id=-456))
    )
    assert process_one(row.pk) == "processed"
    chat.refresh_from_db()
    assert not chat.is_active
    assert not TelegramChat.objects.filter(connection=conn, chat_id=-456).exists()
    assert TelegramDelivery.objects.filter(chat=chat, status="failed", error__contains="pair the replacement").exists()


def test_membership_update_cannot_disable_chat_for_a_different_bot(hub):
    conn, chat = hub
    row = TelegramUpdate.objects.create(
        connection=conn,
        update_id=6,
        payload=authenticated(
            conn,
            {
                "update_id": 6,
                "my_chat_member": {
                    "chat": {"id": chat.chat_id},
                    "new_chat_member": {"user": {"id": conn.bot_id + 1}, "status": "kicked"},
                },
            },
        ),
    )
    assert process_one(row.pk) == "processed"
    chat.refresh_from_db()
    assert chat.is_active
    assert not TelegramDelivery.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_concurrent_workers_claim_update_once_and_handler_runs_outside_db_lock(hub, monkeypatch):
    conn, _ = hub
    row = TelegramUpdate.objects.create(connection=conn, update_id=31, payload=authenticated(conn, payload(31)))
    entered, release = threading.Event(), threading.Event()

    def handle(connection, update):
        assert not db_connection.in_atomic_block
        entered.set()
        assert release.wait(timeout=10)
        return {"text": "Queued once"}

    handler = Mock(side_effect=handle)
    monkeypatch.setattr("apps.telegram.conversations.handle_message", handler)

    def work():
        try:
            return process_one(row.pk)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(work)
        assert entered.wait(timeout=10)
        second = pool.submit(work)
        try:
            assert second.result(timeout=10) == "skipped"
        finally:
            release.set()
        assert first.result(timeout=10) == "processed"
    assert handler.call_count == 1
    assert TelegramDelivery.objects.count() == 1


def test_callback_dispatch_and_ack_are_bound_to_inbound_chat(hub, monkeypatch):
    conn, chat = hub
    query = {
        "id": "test-callback-id",
        "from": {"id": 99},
        "data": "tg:a:" + "n" * 32,
        "message": {"message_id": 3, "chat": {"id": chat.chat_id, "type": "supergroup"}},
    }
    row = TelegramUpdate.objects.create(
        connection=conn, update_id=33, payload=authenticated(conn, {"update_id": 33, "callback_query": query})
    )
    handler = Mock(return_value={"ok": False, "text": "This review is no longer current.", "chat_id": -999})
    monkeypatch.setattr("apps.telegram.actions.handle_callback", handler)
    assert process_one(row.pk) == "processed"
    handler.assert_called_once()
    assert handler.call_args.args[1] == query
    rows = list(TelegramDelivery.objects.filter(chat=chat))
    assert len(rows) == 2
    assert {row.payload["method"] for row in rows} == {"sendMessage", "answerCallbackQuery"}
    assert all(row.chat_id == chat.pk for row in rows)


def test_recurring_worker_registration_restores_exactly_one_bounded_schedule():
    from background_task.models import Task

    from apps.telegram.apps import TelegramConfig
    from apps.telegram.tasks import TELEGRAM_SWEEP_SECONDS

    Task.objects.filter(verbose_name="run_telegram_cycle").delete()
    TelegramConfig._register_tasks(sender=None)
    TelegramConfig._register_tasks(sender=None)
    rows = Task.objects.filter(verbose_name="run_telegram_cycle")
    assert rows.count() == 1
    assert rows.get().repeat == TELEGRAM_SWEEP_SECONDS


@pytest.mark.parametrize("change", ["bot", "secret", "token"])
def test_older_ingress_epoch_is_rejected_even_when_chat_and_user_are_active(hub, monkeypatch, change):
    conn, _ = hub
    assert request(conn, payload(91)).status_code == 200
    row = TelegramUpdate.objects.get(update_id=91)
    handler = Mock(return_value={"text": "Must not enqueue a paid draft"})
    monkeypatch.setattr("apps.telegram.conversations.handle_message", handler)
    if change == "bot":
        conn.bot_id += 1
        conn.save(update_fields=["bot_id"])
    elif change == "secret":
        conn.webhook_secret = "fresh-secret-after-disconnect"
        conn.save(update_fields=["webhook_secret"])
    else:
        conn.token = "123456:" + "g" * 32
        conn.save(update_fields=["token"])
    assert process_one(row.pk) == "failed"
    handler.assert_not_called()
    row.refresh_from_db()
    assert "older bot connection" in row.error
    assert not TelegramDelivery.objects.exists()


def test_handler_response_cannot_inherit_new_connection_after_reconnect(hub, monkeypatch):
    conn, _ = hub
    row = TelegramUpdate.objects.create(connection=conn, update_id=92, payload=authenticated(conn, payload(92)))

    def handle(connection, update):
        TelegramConnection.objects.filter(pk=conn.pk).update(webhook_secret="new-connection-secret")
        return {"text": "An old internal response must not be rebound"}

    monkeypatch.setattr("apps.telegram.conversations.handle_message", handle)
    assert process_one(row.pk) == "failed"
    assert not TelegramDelivery.objects.exists()
