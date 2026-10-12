"""Authenticated, bounded ingress. Telegram requests never run model or network work."""

import json
import secrets

from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import TelegramConnection, TelegramUpdate

MAX_UPDATE_BYTES = 256 * 1024
_MESSAGE_FIELDS = {
    "message_id",
    "date",
    "chat",
    "from",
    "text",
    "caption",
    "entities",
    "caption_entities",
    "photo",
    "document",
    "sender_chat",
    "forward_origin",
    "forward_from",
    "forward_from_chat",
    "forward_sender_name",
    "forward_date",
    "is_automatic_forward",
    "migrate_to_chat_id",
    "migrate_from_chat_id",
    "voice",
    "video",
    "audio",
    "sticker",
    "reply_to_message",
}


def _number(value, *, positive=False):
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and -(2**63) < value < 2**63
        and (value > 0 if positive else True)
    )


def _message(value):
    if not isinstance(value, dict) or not isinstance(value.get("chat"), dict):
        raise ValueError
    if not _number(value["chat"].get("id")) or value["chat"].get("type") not in {
        "private",
        "group",
        "supergroup",
        "channel",
    }:
        raise ValueError
    if "from" in value and (not isinstance(value["from"], dict) or not _number(value["from"].get("id"), positive=True)):
        raise ValueError
    for name, limit in (("text", 4096), ("caption", 1024)):
        if name in value and (not isinstance(value[name], str) or len(value[name]) > limit):
            raise ValueError
    result = {key: item for key, item in value.items() if key in _MESSAGE_FIELDS}
    # A quoted message isn't an independent identity or attachment source.
    if "reply_to_message" in result:
        quoted = result["reply_to_message"]
        if not isinstance(quoted, dict):
            raise ValueError
        result["reply_to_message"] = {key: quoted[key] for key in ("message_id", "text", "caption") if key in quoted}
    return result


def minimal_update(payload):
    if not isinstance(payload, dict) or not _number(payload.get("update_id")) or payload["update_id"] < 0:
        raise ValueError
    result = {"update_id": payload["update_id"]}
    supported = [key for key in ("message", "callback_query", "my_chat_member") if key in payload]
    if len(supported) > 1:
        raise ValueError
    if "message" in payload:
        result["message"] = _message(payload["message"])
    elif "callback_query" in payload:
        query = payload["callback_query"]
        if not isinstance(query, dict) or not isinstance(query.get("id"), str) or len(query["id"]) > 128:
            raise ValueError
        sender, data = query.get("from"), query.get("data")
        if not isinstance(sender, dict) or not _number(sender.get("id"), positive=True):
            raise ValueError
        if not isinstance(data, str) or len(data.encode("utf-8")) > 64:
            raise ValueError
        result["callback_query"] = {"id": query["id"], "from": sender, "data": data}
        if "message" in query:
            result["callback_query"]["message"] = _message(query["message"])
    elif "my_chat_member" in payload:
        member = payload["my_chat_member"]
        if not isinstance(member, dict) or not isinstance(member.get("chat"), dict):
            raise ValueError
        if not _number(member["chat"].get("id")):
            raise ValueError
        result["my_chat_member"] = {key: member[key] for key in ("chat", "new_chat_member") if key in member}
    return result


@csrf_exempt
@require_POST
def ingress(request, connection_id):
    connection = TelegramConnection.objects.filter(pk=connection_id, is_active=True).first()
    supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if (
        connection is None
        or not supplied
        or len(supplied) > 256
        or not connection.webhook_secret
        or not secrets.compare_digest(supplied.encode("utf-8"), connection.webhook_secret.encode("utf-8"))
    ):
        return JsonResponse({"ok": False}, status=403)
    cap = min(MAX_UPDATE_BYTES, max(1024, int(getattr(settings, "TELEGRAM_UPDATE_MAX_BYTES", MAX_UPDATE_BYTES))))
    try:
        declared = int(request.META.get("CONTENT_LENGTH") or 0)
        if declared < 0 or declared > cap:
            return JsonResponse({"ok": False}, status=413)
        # Read at most the application cap, even when Content-Length is absent.
        body = request.read(cap + 1)
        if len(body) > cap:
            return JsonResponse({"ok": False}, status=413)
        payload = minimal_update(json.loads(body))
        from .processing import connection_epoch

        payload["_binding"] = connection_epoch(connection)
    except RequestDataTooBig:
        return JsonResponse({"ok": False}, status=413)
    except (ValueError, TypeError, UnicodeDecodeError, RecursionError):
        return JsonResponse({"ok": False}, status=400)
    with transaction.atomic():
        update, created = TelegramUpdate.objects.get_or_create(
            connection=connection, update_id=payload["update_id"], defaults={"payload": payload}
        )
        if created:
            from .tasks import process_update

            transaction.on_commit(lambda: process_update(str(update.pk)))
    return JsonResponse({"ok": True})
