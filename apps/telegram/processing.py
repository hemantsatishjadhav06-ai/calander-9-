"""Claim each authenticated update once; interrupted mutations are held for inspection."""

import hashlib
from contextvars import ContextVar
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import TelegramChat, TelegramDelivery, TelegramUpdate

INBOUND_PROCESSING: ContextVar[bool] = ContextVar("telegram_inbound_processing", default=False)
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


def _disable_chat(chat, *, source_key, reason):
    # Migration is not proof that the new chat has the same client/audience.
    # An authorized manager must pair and verify the replacement again.
    with transaction.atomic():
        TelegramChat.objects.filter(pk=chat.pk).update(is_active=False)
        TelegramDelivery.objects.filter(chat=chat, status="pending").update(status="failed", error=reason)
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
        for chat in TelegramChat.objects.filter(connection=row.connection, chat_id__in=ids):
            _disable_chat(
                chat,
                source_key=f"update:{row.update_id}:migration",
                reason=("Telegram group migrated. Verify and pair the replacement group before sending again."),
            )
        return True
    member = payload.get("my_chat_member", {})
    bot = member.get("new_chat_member", {})
    if bot.get("user", {}).get("id") == row.connection.bot_id and bot.get("status") in {"left", "kicked"}:
        for chat in TelegramChat.objects.filter(connection=row.connection, chat_id=member.get("chat", {}).get("id")):
            _disable_chat(
                chat,
                source_key=f"update:{row.update_id}:removed",
                reason="The Telegram bot was removed from this chat.",
            )
        return True
    return "my_chat_member" in payload


def process_one(update_id):
    row = _claim(update_id)
    if row is None:
        return "skipped"
    marker = INBOUND_PROCESSING.set(True)
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
        row.payload["_response_scope"] = _scope(_fresh_chat(initial.pk)) if initial else None
        if not _lifecycle(row):
            response = {}
            if "callback_query" in row.payload:
                from .actions import handle_callback

                response = handle_callback(row.connection, row.payload["callback_query"])
            elif "message" in row.payload:
                from .conversations import handle_message

                response = handle_message(row.connection, row.payload)
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
