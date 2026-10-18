"""Encrypted, deduplicated outbound messages with explicit uncertain-send holds."""

import hashlib
import re
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.common.background import check_worker_lease

from .api import BotAPI, TelegramAPIError
from .models import TelegramChat, TelegramDelivery, TelegramUserLink
from .permissions import TelegramPermissionDenied, fresh_member, internal_member
from .processing import connection_epoch

MAX_SEND_ATTEMPTS = 4
SEND_CLAIM_TIMEOUT = timedelta(minutes=5)
MAX_PHOTO_BYTES = 10 * 1024 * 1024
_CALLBACK = re.compile(r"^tg:a:[A-Za-z0-9_-]{32}$")


def _chunks(text, limit=4096):
    """Telegram counts UTF-16 units; an emoji consumes two."""
    result, current, count = [], [], 0
    for char in text:
        # Lone surrogates cannot be encoded or delivered as JSON text.
        if 0xD800 <= ord(char) <= 0xDFFF or char == "\x00":
            continue
        size = 2 if ord(char) > 0xFFFF else 1
        if count + size > limit:
            result.append("".join(current))
            current, count = [], 0
        current.append(char)
        count += size
    if current:
        result.append("".join(current))
    return result


def _source_key(value):
    if not isinstance(value, str) or not value:
        raise ValueError("A semantic delivery key is required.")
    return value if len(value) <= 180 else "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _keyboard(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"inline_keyboard"}:
        raise ValueError("Unsupported Telegram keyboard.")
    rows = value["inline_keyboard"]
    if not isinstance(rows, list) or len(rows) > 10:
        raise ValueError("Invalid Telegram keyboard.")
    clean = []
    for row in rows:
        if not isinstance(row, list) or not 1 <= len(row) <= 8:
            raise ValueError("Invalid Telegram keyboard.")
        buttons = []
        for button in row:
            if not isinstance(button, dict) or set(button) != {"text", "callback_data"}:
                raise ValueError("Invalid Telegram callback.")
            label, callback = button["text"], button["callback_data"]
            if (
                not isinstance(label, str)
                or not 1 <= len(label) <= 80
                or not isinstance(callback, str)
                or not _CALLBACK.fullmatch(callback)
            ):
                raise ValueError("Invalid Telegram callback.")
            buttons.append({"text": label, "callback_data": callback})
        clean.append(buttons)
    return {"inline_keyboard": clean}


def permitted_chat(chat):
    """Re-check the tenant, thread and private recipient at queue and send time."""
    connection, conversation = chat.connection, chat.conversation
    workspace = connection.workspace
    org = workspace.organization
    if (
        not chat.is_active
        or not connection.is_active
        or workspace.is_archived
        or org.deletion_requested_at
        or org.deleted_at
    ):
        return False
    if conversation.workspace_id != connection.workspace_id:
        return False
    if chat.audience in {"client", "team"} and conversation.is_private:
        return False
    if chat.audience == "client":
        return (
            chat.chat_type in {"group", "supergroup"}
            and conversation.audience == "client"
            and chat.private_user_id is None
        )
    if chat.audience == "team":
        return (
            chat.chat_type in {"group", "supergroup"}
            and chat.private_user_id is None
            and conversation.audience == "internal"
        )
    if chat.audience != "private" or chat.chat_type != "private" or chat.private_user_id is None:
        return False
    if conversation.created_by_id != chat.private_user_id:
        return False
    if TelegramChat.objects.filter(conversation_id=conversation.pk).exclude(pk=chat.pk).exists():
        return False
    link = TelegramUserLink.objects.filter(
        connection=connection, user_id=chat.private_user_id, telegram_user_id=chat.chat_id, is_active=True
    ).first()
    if link is None:
        return False
    try:
        member = fresh_member(link)
        expected = "internal" if internal_member(member) else "client"
        return member is not None and conversation.audience == expected
    except TelegramPermissionDenied:
        return False


def _fresh_chat(chat_id):
    return (
        TelegramChat.objects.select_related("connection__workspace__organization", "conversation")
        .filter(pk=chat_id)
        .first()
    )


def _scope(chat):
    return {
        "connection_id": str(chat.connection_id),
        "workspace_id": str(chat.connection.workspace_id),
        "bot_id": chat.connection.bot_id,
        "connection_epoch": connection_epoch(chat.connection),
        "chat_id": chat.chat_id,
        "conversation_id": str(chat.conversation_id),
        "conversation_audience": chat.conversation.audience,
        "conversation_is_private": chat.conversation.is_private,
        "audience": chat.audience,
        "private_user_id": str(chat.private_user_id) if chat.private_user_id else None,
    }


def _insert(chat, source_key, payload, *, kind="message"):
    # A private chat may be rebound to a new conversation after a role change.
    # Its stable UUID alone cannot authorize delivering an older internal reply.
    payload = {**payload, "_scope": _scope(chat)}
    with transaction.atomic():
        delivery, created = TelegramDelivery.objects.get_or_create(
            chat=chat,
            source_key=source_key,
            defaults={"connection": chat.connection, "kind": kind, "payload": payload},
        )
        if created:
            from .tasks import send_delivery

            transaction.on_commit(lambda: send_delivery(str(delivery.pk)))
    return delivery


def queue_message(chat, text, *, source_key, reply_markup=None, after_source_keys=None):
    current = _fresh_chat(chat.pk)
    if current is None or not permitted_chat(current):
        return []
    if not isinstance(text, str):
        raise ValueError("Telegram text must be a string.")
    keyboard = _keyboard(reply_markup)
    base = _source_key(source_key)
    # Bound a single model/event reply; the conversation retains full content.
    pieces = _chunks(text)
    if len(pieces) > 8:
        # An incomplete review must never carry an approval button.
        pieces, keyboard = pieces[:8], None
        pieces[-1] = (_chunks(pieces[-1], 3900) or [""])[0] + "\nFull reply continues in SM Bean."
    rows = []
    previous = list(after_source_keys or [])
    for index, piece in enumerate(pieces):
        payload = {"method": "sendMessage", "text": piece}
        if previous:
            payload["after_source_keys"] = previous
        if keyboard and index == len(pieces) - 1:
            payload["reply_markup"] = keyboard
        key = f"{base}:part:{index}"
        rows.append(_insert(current, key, payload))
        previous = [key]
    return rows


def queue_photo(chat, asset_id, *, caption="", source_key, reply_markup=None):
    from apps.media_library.models import MediaAsset

    current = _fresh_chat(chat.pk)
    if current is None or not permitted_chat(current):
        return None
    asset = MediaAsset.objects.filter(
        pk=asset_id,
        workspace_id=current.connection.workspace_id,
        organization_id=current.connection.workspace.organization_id,
    ).first()
    if asset is None or not asset.is_image or asset.processing_status != "completed":
        return None
    payload = {"method": "sendPhoto", "photo_asset_id": str(asset.pk), "caption": (_chunks(caption, 1024) or [""])[0]}
    keyboard = _keyboard(reply_markup)
    if keyboard:
        payload["reply_markup"] = keyboard
    return _insert(current, _source_key(source_key), payload, kind="photo")


def queue_response(connection, payload, response):
    if not isinstance(response, dict) or response.get("silent"):
        return []
    query = payload.get("callback_query")
    message = query.get("message", {}) if query else payload.get("message", {})
    chat = TelegramChat.objects.filter(
        connection=connection, chat_id=message.get("chat", {}).get("id"), is_active=True
    ).first()
    if chat is None:
        return []
    current = _fresh_chat(chat.pk)
    if current is None:
        return []
    # A handler can finish after a disconnect, role downgrade or re-pair.
    # Its old response must not inherit a freshly rebound chat's authority.
    if payload.get("_binding") != connection_epoch(current.connection):
        raise ValueError("The response belongs to an older connection.")
    if payload.get("_response_scope") is not None and payload["_response_scope"] != _scope(current):
        raise ValueError("The response belongs to an older conversation.")
    key = f"update:{payload['update_id']}:response"
    text = response.get("text", "")
    if query:
        current = _fresh_chat(chat.pk)
        if current is not None and permitted_chat(current):
            ack = (_chunks(text, 200) or ["Done."])[0]
            _insert(
                current,
                f"{key}:callback",
                {"method": "answerCallbackQuery", "callback_query_id": query["id"], "text": ack},
            )
    markup = response.get("reply_markup")
    if markup is None and "inline_keyboard" in response:
        markup = {"inline_keyboard": response["inline_keyboard"]}
    result, prerequisites = [], []
    if response.get("photo_asset_id"):
        photo = queue_photo(chat, response["photo_asset_id"], source_key=f"{key}:photo")
        if photo:
            result.append(photo)
            prerequisites.append(photo.source_key)
        elif markup:
            # Missing review media prevents exposing its human action.
            markup = None
            text += "\nThe review graphic is unavailable. Open SM Bean to review it before acting."
    result.extend(queue_message(chat, text, source_key=key, reply_markup=markup, after_source_keys=prerequisites))
    return result


def recover_stale_deliveries(*, limit=25):
    with transaction.atomic():
        rows = list(
            TelegramDelivery.objects.select_for_update(skip_locked=True)
            .filter(status="sending", claimed_at__lt=timezone.now() - SEND_CLAIM_TIMEOUT)
            .order_by("claimed_at")[:limit]
        )
        for row in rows:
            row.status = "unknown"
            row.error = "Sending was interrupted. Inspect Telegram before sending this message again."
            row.save(update_fields=["status", "error", "updated_at"])
    return len(rows)


def _claim(delivery_id):
    now = timezone.now()
    with transaction.atomic():
        row = (
            TelegramDelivery.objects.select_for_update(skip_locked=True)
            .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now), pk=delivery_id, status="pending")
            .first()
        )
        if row is None:
            return None
        prerequisites = row.payload.get("after_source_keys", []) if isinstance(row.payload, dict) else []
        if prerequisites:
            prior = list(
                TelegramDelivery.objects.filter(chat_id=row.chat_id, source_key__in=prerequisites).values_list(
                    "status", flat=True
                )
            )
            if len(prior) != len(prerequisites) or any(status in {"failed", "unknown"} for status in prior):
                row.status = "failed"
                row.error = "An earlier review segment was not delivered. Reissue the complete review before acting."
                row.save(update_fields=["status", "error", "updated_at"])
                return None
            if any(status != "sent" for status in prior):
                return None
        if row.attempts >= MAX_SEND_ATTEMPTS:
            row.status, row.error = "failed", "The Telegram delivery exhausted its retry attempts."
            row.save(update_fields=["status", "error", "updated_at"])
            return None
        row.status, row.claimed_at = "sending", now
        row.attempts += 1
        row.save(update_fields=["status", "claimed_at", "attempts", "updated_at"])
    return TelegramDelivery.objects.select_related("connection", "chat").get(pk=row.pk)


def _finish(row, **fields):
    return TelegramDelivery.objects.filter(pk=row.pk, status="sending", claimed_at=row.claimed_at).update(
        updated_at=timezone.now(), **fields
    )


def _before_transport(row, chat):
    check_worker_lease()
    if not TelegramDelivery.objects.filter(pk=row.pk, status="sending", claimed_at=row.claimed_at).exists():
        return None
    current = _fresh_chat(chat.pk)
    if (
        current is None
        or not permitted_chat(current)
        or _scope(current) != row.payload.get("_scope")
        or not _workflow_permitted(row, current)
    ):
        _finish(
            row,
            status="failed",
            error="The recipient changed before sending. Request a fresh reply in the current thread.",
        )
        return None
    return current


def _workflow_permitted(row, chat):
    if not row.source_key.startswith("workflow-prompt:"):
        return True
    from .workflow_bridge import delivery_permitted

    return delivery_permitted(row, chat) is True


def _suspend_recipient(row, reason):
    from .provisioning import _invalidate_queues

    with transaction.atomic():
        current = (
            TelegramChat.objects.select_for_update(of=("self",))
            .select_related("connection", "conversation")
            .filter(pk=row.chat_id)
            .first()
        )
        if current is None or _scope(current) != row.payload.get("_scope"):
            return
        _invalidate_queues(current.connection, chat=current)
        TelegramChat.objects.filter(pk=current.pk).update(is_active=False, updated_at=timezone.now())
        TelegramDelivery.objects.filter(chat_id=current.pk, status="pending").update(status="failed", error=reason)


def _photo_content(row, chat):
    from apps.media_library.models import MediaAsset

    asset = MediaAsset.objects.filter(
        pk=row.payload.get("photo_asset_id"),
        workspace_id=chat.connection.workspace_id,
        organization_id=chat.connection.workspace.organization_id,
        media_type="image",
        processing_status="completed",
    ).first()
    if asset is None or not asset.file or not 0 < asset.file_size <= MAX_PHOTO_BYTES:
        raise ValueError("This photo is unavailable.")
    with asset.file.open("rb") as stream:
        content = stream.read(MAX_PHOTO_BYTES + 1)
    if not content or len(content) > MAX_PHOTO_BYTES:
        raise ValueError("This photo exceeds the Telegram limit.")
    # Decode verification is bounded by the same pixel cap as incoming media.
    from io import BytesIO

    from PIL import Image

    with Image.open(BytesIO(content)) as image:
        if image.format not in {"JPEG", "PNG", "WEBP"} or image.width * image.height > 25_000_000:
            raise ValueError("Unsupported Telegram image.")
        image.verify()
    return content, asset


def _photo_caption(asset, caption):
    from apps.studio.trust import photo_status

    label = photo_status(asset)["label"]
    combined = f"{label}\n{caption}" if caption else label
    return (_chunks(combined, 1024) or [""])[0]


def send_one(delivery_id):
    row = _claim(delivery_id)
    if row is None:
        return "skipped"
    attempted = False
    try:
        chat = _fresh_chat(row.chat_id)
        if (
            chat is None
            or chat.connection_id != row.connection_id
            or not permitted_chat(chat)
            or not _workflow_permitted(row, chat)
        ):
            _finish(
                row, status="failed", error="The Telegram connection, recipient or conversation is no longer permitted."
            )
            return "failed"
        payload = row.payload
        if not isinstance(payload, dict):
            raise ValueError("Invalid delivery.")
        if payload.get("_scope") != _scope(chat):
            _finish(
                row,
                status="failed",
                error="This chat's conversation or audience changed. Request a fresh reply in the current thread.",
            )
            return "failed"
        method = payload.get("method")
        if method == "sendPhoto" and row.kind == "photo":
            # Asset/storage errors happen before the API method starts. The
            # transport labels genuine uncertain HTTP sends explicitly.
            content, asset = _photo_content(row, chat)
            chat = _before_transport(row, chat)
            if chat is None:
                return "unknown"
            api = BotAPI(chat.connection.token)
            attempted = True
            result = api.send_photo(
                chat.chat_id,
                content,
                filename="graphic.jpg",
                caption=_photo_caption(asset, payload.get("caption", "")),
                reply_markup=_keyboard(payload.get("reply_markup")),
            )
        elif method == "sendMessage" and row.kind == "message":
            text = payload.get("text")
            if not isinstance(text, str) or not text or len(text.encode("utf-16-le")) // 2 > 4096:
                raise ValueError("Invalid text.")
            params = {"chat_id": chat.chat_id, "text": text, "link_preview_options": {"is_disabled": True}}
            if payload.get("reply_markup"):
                params["reply_markup"] = _keyboard(payload["reply_markup"])
            chat = _before_transport(row, chat)
            if chat is None:
                return "unknown"
            api = BotAPI(chat.connection.token)
            attempted = True
            result = api.call("sendMessage", params)
        elif method == "answerCallbackQuery" and row.kind == "message":
            text, query_id = payload.get("text"), payload.get("callback_query_id")
            if (
                not isinstance(text, str)
                or len(text.encode("utf-16-le")) // 2 > 200
                or not isinstance(query_id, str)
                or len(query_id) > 128
            ):
                raise ValueError("Invalid callback acknowledgement.")
            chat = _before_transport(row, chat)
            if chat is None:
                return "unknown"
            api = BotAPI(chat.connection.token)
            attempted = True
            result = api.call("answerCallbackQuery", {"callback_query_id": query_id, "text": text})
        else:
            raise ValueError("Unsupported delivery.")
        message_id = result.get("message_id") if isinstance(result, dict) else None
        if row.source_key.startswith("workflow-prompt:") and (
            type(message_id) is not int
            or message_id <= 0
            or not isinstance(result.get("chat"), dict)
            or type(result["chat"].get("id")) is not int
            or result["chat"]["id"] != chat.chat_id
            or result["chat"].get("type") != "private"
        ):
            _finish(
                row,
                status="unknown",
                next_attempt_at=None,
                error="Telegram did not return a verified private workflow receipt. Inspect the chat before resending.",
            )
            return "unknown"
        if method != "answerCallbackQuery" and (not isinstance(message_id, int) or isinstance(message_id, bool)):
            _finish(
                row,
                status="unknown",
                error="Telegram did not return a verifiable message receipt. Inspect the chat before resending.",
            )
            return "unknown"
        recorded = _finish(row, status="sent", native_message_id=message_id, error="", next_attempt_at=None)
        return "sent" if recorded else "unknown"
    except TelegramAPIError as exc:
        if exc.ambiguous:
            status, error = "unknown", "The Telegram send outcome is unknown. Inspect the chat before resending."
        elif exc.kind in {"forbidden", "403", "chat_migrated"}:
            reason = (
                "Telegram group migrated. Verify and pair the replacement group before sending again."
                if exc.kind == "chat_migrated"
                else "Telegram disabled this recipient. Verify chat access and pair it again."
            )
            # This request received a definitive rejection. Settle it before
            # suspending the chat, whose other in-flight sends remain unknown.
            recorded = _finish(row, status="failed", error=reason, next_attempt_at=None)
            _suspend_recipient(row, reason)
            return "failed" if recorded else "unknown"
        elif (
            exc.kind in {"rate_limited", "rate_limit", "429", "connect", "connection", "preconnect"}
            and row.attempts < MAX_SEND_ATTEMPTS
        ):
            delay = max(5, int(exc.retry_after or 5 * 2 ** (row.attempts - 1)))
            requeued = _finish(
                row,
                status="pending",
                error="Telegram is temporarily unavailable; a bounded retry is queued.",
                next_attempt_at=timezone.now() + timedelta(seconds=delay),
            )
            return "pending" if requeued else "unknown"
        else:
            status, error = "failed", "Telegram rejected this delivery. Review the recipient and message."
        _finish(row, status=status, error=error, next_attempt_at=None)
        return status
    except Exception:
        status = "unknown" if attempted else "failed"
        _finish(
            row,
            status=status,
            error=(
                "The send outcome could not be recorded. Inspect Telegram before resending."
                if attempted
                else "This Telegram message or media is unavailable. Review it before retrying."
            ),
        )
        return status


def drain_outbox(*, limit=25):
    from .channel_outbox import drain_channels

    limit = min(100, max(1, limit))
    recovered = recover_stale_deliveries(limit=limit)
    ids = list(
        TelegramDelivery.objects.filter(
            Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=timezone.now()), status="pending"
        )
        .order_by("created_at")
        .values_list("pk", flat=True)[:limit]
    )
    outcomes = {"unknown": recovered} if recovered else {}
    for delivery_id in ids:
        status = send_one(delivery_id)
        outcomes[status] = outcomes.get(status, 0) + 1
    for status, count in drain_channels(limit=limit).items():
        outcomes[status] = outcomes.get(status, 0) + count
    return outcomes
