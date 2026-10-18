"""Claim each authenticated update once; interrupted mutations are held for inspection."""

import hashlib
from contextvars import ContextVar
from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from .models import (
    TelegramChannel,
    TelegramChat,
    TelegramConnection,
    TelegramDelivery,
    TelegramUpdate,
    TelegramUserLink,
)

INBOUND_PROCESSING: ContextVar[bool] = ContextVar("telegram_inbound_processing", default=False)
CURRENT_UPDATE_ID: ContextVar[UUID | None] = ContextVar("telegram_current_update_id", default=None)
UPDATE_CLAIM_TIMEOUT = timedelta(minutes=10)
MAX_UPDATE_ATTEMPTS = 3


def connection_epoch(connection):
    """Encrypted queue binding, never a raw credential or a logged value."""
    return {
        "bot_id": connection.bot_id,
        "workspace_id": str(connection.workspace_id),
        "secret_digest": hashlib.sha256(connection.webhook_secret.encode()).hexdigest(),
        "token_digest": hashlib.sha256(connection.token.encode()).hexdigest(),
    }


def recover_stale_updates(*, limit=25):
    cutoff = timezone.now() - UPDATE_CLAIM_TIMEOUT
    with transaction.atomic():
        rows = list(
            TelegramUpdate.objects.select_for_update(skip_locked=True)
            .filter(status="working", claimed_at__lt=cutoff)
            .order_by("claimed_at")[:limit]
        )
        for row in rows:
            row.status = "failed"
            row.error = "Processing was interrupted. Inspect the conversation before retrying this update."
            row.save(update_fields=["status", "error"])
    return len(rows)


def _claim(update_id):
    with transaction.atomic():
        row = TelegramUpdate.objects.select_for_update(skip_locked=True).filter(pk=update_id, status="pending").first()
        if row is None:
            return None
        if row.attempts >= MAX_UPDATE_ATTEMPTS:
            row.status = "failed"
            row.error = "The update exhausted its processing attempts."
            row.save(update_fields=["status", "error"])
            return None
        row.status, row.claimed_at = "working", timezone.now()
        row.attempts += 1
        row.save(update_fields=["status", "claimed_at", "attempts"])
    return TelegramUpdate.objects.select_related("connection__workspace").get(pk=row.pk)


def _disable_chat(chat, *, source_key, reason, exclude_update_pk=None):
    # Migration is not proof that the new chat has the same client/audience.
    # An authorized manager must pair and verify the replacement again.
    with transaction.atomic():
        from .provisioning import _invalidate_queues

        TelegramConnection.objects.select_for_update().filter(pk=chat.connection_id).first()
        current = TelegramChat.objects.select_for_update().filter(pk=chat.pk).first()
        if current is None or current.updated_at != chat.updated_at:
            return
        _invalidate_queues(chat.connection, chat=chat, exclude_update_pk=exclude_update_pk)
        TelegramChat.objects.filter(pk=chat.pk).update(is_active=False, updated_at=timezone.now())
        TelegramDelivery.objects.get_or_create(
            chat=chat,
            source_key=source_key,
            defaults={"connection": chat.connection, "payload": {}, "status": "failed", "error": reason},
        )


def _lifecycle(row):
    payload = row.payload
    message = payload.get("message", {})
    if message.get("migrate_to_chat_id") or message.get("migrate_from_chat_id"):
        ids = {message.get("chat", {}).get("id"), message.get("migrate_from_chat_id")}
        for chat in TelegramChat.objects.filter(
            connection=row.connection, chat_id__in=ids, updated_at__lte=row.created_at
        ):
            _disable_chat(
                chat,
                source_key=f"update:{row.update_id}:migration",
                reason=("Telegram group migrated. Verify and pair the replacement group before sending again."),
                exclude_update_pk=row.pk,
            )
        return True
    member = payload.get("my_chat_member", {})
    bot = member.get("new_chat_member", {})
    if (
        type(bot.get("user", {}).get("id")) is int
        and bot["user"]["id"] == row.connection.bot_id
        and (bot.get("status") != "administrator" or bot.get("can_post_messages") is not True)
    ):
        # Channel status is independent from private/group pairing. A late
        # removal update cannot revoke a channel verified after its arrival.
        with transaction.atomic():
            from .provisioning import _invalidate_channel_deliveries

            TelegramConnection.objects.select_for_update().filter(pk=row.connection_id).first()
            channels = TelegramChannel.objects.select_for_update().filter(
                connection=row.connection,
                chat_id=member.get("chat", {}).get("id"),
                updated_at__lte=row.created_at,
            )
            _invalidate_channel_deliveries(channels, reason="The bot's channel posting permission was removed.")
            channels.update(is_active=False, updated_at=timezone.now())
    if bot.get("user", {}).get("id") == row.connection.bot_id and bot.get("status") in {"left", "kicked"}:
        for chat in TelegramChat.objects.filter(
            connection=row.connection, chat_id=member.get("chat", {}).get("id"), updated_at__lte=row.created_at
        ):
            _disable_chat(
                chat,
                source_key=f"update:{row.update_id}:removed",
                reason="The Telegram bot was removed from this chat.",
                exclude_update_pk=row.pk,
            )
        return True
    return "my_chat_member" in payload


def process_one(update_id):
    row = _claim(update_id)
    if row is None:
        return "skipped"
    marker = INBOUND_PROCESSING.set(True)
    update_marker = CURRENT_UPDATE_ID.set(row.pk)
    try:
        if not row.connection.is_active:
            raise ValueError("Inactive connection")
        if row.payload.get("_binding") != connection_epoch(row.connection):
            TelegramUpdate.objects.filter(pk=row.pk, status="working", claimed_at=row.claimed_at).update(
                status="failed",
                error="This update belongs to an older bot connection. Send a fresh request after pairing.",
            )
            return "failed"
        from .outbox import _fresh_chat, _scope

        incoming = (
            row.payload.get("callback_query", {}).get("message", {})
            if "callback_query" in row.payload
            else row.payload.get("message", {})
        )
        initial = TelegramChat.objects.filter(
            connection=row.connection, chat_id=incoming.get("chat", {}).get("id"), is_active=True
        ).first()
        query = row.payload.get("callback_query", {})
        sender = query.get("from", {}) if query else incoming.get("from", {})
        link = TelegramUserLink.objects.filter(
            connection=row.connection, telegram_user_id=sender.get("id"), is_active=True
        ).first()
        # Rows arriving while a recipient/identity was disabled are not part of
        # a subsequent pairing. Capturing scope only when a worker runs would
        # let an old /brief acquire the newly paired person's current access.
        if (initial and initial.updated_at > row.created_at) or (link and link.updated_at > row.created_at):
            TelegramUpdate.objects.filter(pk=row.pk, status="working", claimed_at=row.claimed_at).update(
                status="failed",
                error="The chat or personal pairing changed after this update arrived. Send a fresh request.",
            )
            return "failed"
        row.payload["_response_scope"] = _scope(_fresh_chat(initial.pk)) if initial else None
        if "managed_bot" in row.payload:
            from .managed import process_managed_bot_update

            process_managed_bot_update(row.connection, row.payload["managed_bot"])
        elif not _lifecycle(row):
            response = {}
            if "callback_query" in row.payload:
                from .actions import handle_callback

                response = handle_callback(row.connection, row.payload["callback_query"])
            elif "message" in row.payload:
                from .conversations import handle_message
                from .workflow_bridge import handle_workflow_reply

                response = handle_workflow_reply(row.connection, row.payload)
                if response is None:
                    response = handle_message(row.connection, row.payload)
            if not TelegramUpdate.objects.filter(pk=row.pk, status="working", claimed_at=row.claimed_at).exists():
                return "failed"
            from .outbox import queue_response

            queue_response(row.connection, row.payload, response)
        completed = TelegramUpdate.objects.filter(pk=row.pk, status="working", claimed_at=row.claimed_at).update(
            status="processed", processed_at=timezone.now(), error=""
        )
        return "processed" if completed else "failed"
    except Exception:
        # Never print payloads, provider exceptions, URLs or credentials. A
        # mutation/model task may already exist: automatic replay could pay or
        # approve twice. The dashboard exposes this durable safe failure.
        TelegramUpdate.objects.filter(pk=row.pk, status="working", claimed_at=row.claimed_at).update(
            status="failed", error="Telegram processing failed. Inspect the associated conversation before retrying."
        )
        return "failed"
    finally:
        CURRENT_UPDATE_ID.reset(update_marker)
        INBOUND_PROCESSING.reset(marker)


def drain_updates(*, limit=25):
    limit = min(100, max(1, limit))
    recovered = recover_stale_updates(limit=limit)
    ids = list(
        TelegramUpdate.objects.filter(status="pending").order_by("created_at").values_list("pk", flat=True)[:limit]
    )
    outcomes = {"failed": recovered} if recovered else {}
    for update_id in ids:
        status = process_one(update_id)
        outcomes[status] = outcomes.get(status, 0) + 1
    return outcomes
