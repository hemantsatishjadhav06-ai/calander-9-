"""Status-only channel delivery, separate from every conversation and private chat."""

from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.common.background import check_worker_lease

from .api import BotAPI, TelegramAPIError
from .models import TelegramChannel, TelegramChannelDelivery
from .outbox import MAX_SEND_ATTEMPTS, SEND_CLAIM_TIMEOUT, _source_key
from .permissions import TelegramPermissionDenied
from .processing import connection_epoch

CHANNEL_EVENT_TEXT = {
    "idea": "SM Bean: an idea was added. Open SM Bean for its current status.",
    "draft": "SM Bean: a draft became ready for review. Check its current status in SM Bean. Human approval is required.",
    "review": "SM Bean: a human review was requested for a post. Open SM Bean for its current status.",
    "approved": "SM Bean: a person approved a post. Open SM Bean for its current status, destinations and time.",
    "changes": "SM Bean: changes or a hold review were requested for a post. Open SM Bean for its current status.",
    "scheduled": "SM Bean: a post was scheduled. Check its current status in SM Bean. Publication requires confirmation.",
    "published": "SM Bean: publication was confirmed by the destination platform.",
    "failed": "SM Bean: publication required attention. Review the current delivery status before retrying.",
}


def public_post(post):
    """Deny any post with private or inconsistent provenance, including old links.

    Canonical composer posts have no conversation visibility field. A post
    created from a private thread remains unsuitable for a channel even when
    another public conversation is later attached to it.
    """
    from apps.composer.models import Post
    from apps.studio.models import Conversation

    if post is None or not Post.objects.filter(pk=post.pk, workspace_id=post.workspace_id).exists():
        return False
    briefs = post.studio_briefs.all()
    if briefs.exclude(workspace_id=post.workspace_id).exists():
        return False
    jobs = briefs.filter(job__isnull=False)
    if (
        jobs.exclude(job__workspace_id=post.workspace_id).exists()
        or jobs.exclude(job__conversation__workspace_id=post.workspace_id).exists()
        or jobs.filter(
            Q(job__conversation__is_private=True) | Q(job__conversation__telegram_chats__audience="private")
        ).exists()
    ):
        return False
    conversations = Conversation.objects.filter(Q(post=post) | Q(brief__post=post))
    return not (
        conversations.exclude(workspace_id=post.workspace_id).exists()
        or conversations.filter(Q(is_private=True) | Q(telegram_chats__audience="private")).exists()
    )


def _fresh_channel(channel_id):
    return (
        TelegramChannel.objects.select_related("connection__workspace__organization", "created_by", "user_link")
        .filter(pk=channel_id)
        .first()
    )


def _context(channel):
    from .provisioning import ProvisioningError, channel_actor, channel_authority_digest

    if (
        channel is None
        or not channel.is_active
        or channel.created_by_id is None
        or channel.user_link_id is None
        or not isinstance(channel.chat_id, int)
        or isinstance(channel.chat_id, bool)
        or channel.chat_id >= 0
        or not channel.visibility_confirmed_at
    ):
        return None
    try:
        connection, link, member = channel_actor(channel.connection, channel.created_by)
    except (TelegramPermissionDenied, ProvisioningError):
        return None
    if (
        connection.pk != channel.connection_id
        or channel.organization_id != connection.workspace.organization_id
        or channel_authority_digest(member) != channel.authority_digest
        or connection.bot_id != channel.bot_id
        or connection.updated_at != channel.connection_epoch
        or link.pk != channel.user_link_id
        or link.connection_id != channel.connection_id
        or link.user_id != channel.created_by_id
        or link.telegram_user_id != channel.telegram_user_id
        or link.updated_at != channel.pairing_epoch
    ):
        return None
    return connection, link, member


def permitted_channel(channel):
    """Use fresh owner, tenant and personal pairing authority for every delivery."""
    return _context(_fresh_channel(channel.pk)) is not None


def _scope(channel, context):
    connection, link, member = context
    return {
        "channel_id": str(channel.pk),
        "chat_id": channel.chat_id,
        "channel_epoch": channel.updated_at.isoformat(),
        "visibility_confirmed_at": channel.visibility_confirmed_at.isoformat(),
        "connection_id": str(connection.pk),
        "organization_id": str(channel.organization_id),
        "authority_digest": channel.authority_digest,
        "connection_epoch": connection_epoch(connection),
        "connection_updated_at": connection.updated_at.isoformat(),
        "created_by_id": str(channel.created_by_id),
        "user_link_id": str(link.pk),
        "telegram_user_id": link.telegram_user_id,
        "pairing_epoch": link.updated_at.isoformat(),
        "workspace_role": member.workspace_role,
        "custom_role_id": str(member.custom_role_id) if member.custom_role_id else None,
        "manage_workspace_settings": member.effective_permissions.get("manage_workspace_settings") is True,
    }


def queue_channel_event(channel, event, source_key, *, post=None, brief=None):
    """Queue an allowlisted fixed status only; never accept freeform content."""
    if not isinstance(event, str) or event not in CHANNEL_EVENT_TEXT:
        raise ValueError("Choose a supported Telegram channel status.")
    if post is None:
        raise ValueError("A canonical post is required for a Telegram channel status.")
    key = _source_key(source_key)
    current = _fresh_channel(channel.pk)
    context = _context(current)
    if context is None:
        return None
    if post.workspace_id != context[0].workspace_id or not public_post(post):
        return None
    # Origin metadata is encrypted and only authorizes the status. It is
    # never a transport parameter or a source of user-facing wording.
    payload = {
        "event": event,
        "text": CHANNEL_EVENT_TEXT[event],
        "_scope": _scope(current, context),
        "_post": {"post_id": str(post.pk), "workspace_id": str(post.workspace_id)},
    }
    if event == "draft":
        ready = _ready_brief(post, brief=brief)
        if ready is None:
            return None
        payload["_post"].update(draft_brief_id=str(ready.pk), draft_revision=ready.revision)
    if not _event_proven(post, event, origin=payload["_post"]):
        return None
    with transaction.atomic():
        row, _ = TelegramChannelDelivery.objects.get_or_create(
            channel=current, source_key=key, defaults={"payload": payload}
        )
    return row


def _payload_valid(payload):
    return (
        isinstance(payload, dict)
        and set(payload) == {"event", "text", "_scope", "_post"}
        and isinstance(payload.get("event"), str)
        and payload["event"] in CHANNEL_EVENT_TEXT
        and payload.get("text") == CHANNEL_EVENT_TEXT[payload["event"]]
        and isinstance(payload.get("_scope"), dict)
    )


def _origin_permitted(payload, connection):
    from apps.composer.models import Post

    origin = payload.get("_post")
    expected = {"post_id", "workspace_id"}
    if payload.get("event") == "draft":
        expected |= {"draft_brief_id", "draft_revision"}
    if (
        not isinstance(origin, dict)
        or set(origin) != expected
        or origin["workspace_id"] != str(connection.workspace_id)
    ):
        return False
    try:
        post = Post.objects.filter(pk=origin["post_id"], workspace_id=connection.workspace_id).first()
    except (ValueError, TypeError):
        return False
    return public_post(post) and _event_proven(post, payload["event"], origin=origin)


def _ready_brief(post, *, brief=None, origin=None):
    from apps.studio.models import StudioBrief

    rows = StudioBrief.objects.filter(
        post=post,
        workspace_id=post.workspace_id,
        status__in=["ready", "approved"],
        stage="done",
        finished_at__isnull=False,
        revision__gte=1,
    )
    if brief is not None:
        rows = rows.filter(pk=brief.pk, revision=brief.revision)
    if origin is not None:
        if type(origin.get("draft_revision")) is not int or origin["draft_revision"] < 1:
            return None
        rows = rows.filter(pk=origin.get("draft_brief_id"), revision=origin["draft_revision"])
    return rows.order_by("-finished_at").first()


def _event_proven(post, event, *, origin=None):
    """A publication announcement requires an actual native platform receipt."""
    if event == "draft":
        return _ready_brief(post, origin=origin) is not None
    if event != "published":
        return True
    return (
        post.platform_posts.filter(
            status="published",
            published_at__isnull=False,
            social_account__workspace_id=post.workspace_id,
        )
        .exclude(platform_post_id="")
        .exists()
    )


def _claim(delivery_id):
    now = timezone.now()
    with transaction.atomic():
        row = (
            TelegramChannelDelivery.objects.select_for_update(skip_locked=True)
            .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now), pk=delivery_id, status="pending")
            .first()
        )
        if row is None:
            return None
        if row.attempts >= MAX_SEND_ATTEMPTS:
            row.status, row.error = "failed", "The Telegram channel delivery exhausted its retry attempts."
            row.save(update_fields=["status", "error", "updated_at"])
            return None
        row.status, row.claimed_at = "sending", now
        row.attempts += 1
        row.save(update_fields=["status", "claimed_at", "attempts", "updated_at"])
    return row


def _finish(row, **fields):
    return TelegramChannelDelivery.objects.filter(pk=row.pk, status="sending", claimed_at=row.claimed_at).update(
        updated_at=timezone.now(), **fields
    )


def _before_transport(row):
    check_worker_lease()
    if not TelegramChannelDelivery.objects.filter(pk=row.pk, status="sending", claimed_at=row.claimed_at).exists():
        return None
    channel = _fresh_channel(row.channel_id)
    context = _context(channel)
    if (
        context is None
        or not _payload_valid(row.payload)
        or _scope(channel, context) != row.payload.get("_scope")
        or not _origin_permitted(row.payload, context[0])
    ):
        _finish(
            row,
            status="failed",
            next_attempt_at=None,
            error="This channel, pairing, permission or post visibility changed. Review channel setup before sending.",
        )
        return None
    return channel, context


def _native_verified(api, channel, context):
    connection, link, _ = context
    identity = api.get_me()
    if (
        not isinstance(identity, dict)
        or type(identity.get("id")) is not int
        or identity["id"] != connection.bot_id
        or identity.get("is_bot") is not True
        or not isinstance(identity.get("username"), str)
        or identity["username"].lower() != connection.bot_username.lower()
    ):
        return False
    native = api.call("getChat", {"chat_id": channel.chat_id})
    if (
        not isinstance(native, dict)
        or type(native.get("id")) is not int
        or native["id"] != channel.chat_id
        or native.get("type") != "channel"
    ):
        return False
    bot = api.get_chat_member(channel.chat_id, connection.bot_id)
    actor = api.get_chat_member(channel.chat_id, link.telegram_user_id)
    return bool(
        isinstance(bot, dict)
        and isinstance(bot.get("user"), dict)
        and type(bot["user"].get("id")) is int
        and bot["user"]["id"] == connection.bot_id
        and bot["user"].get("is_bot") is True
        and bot.get("status") == "administrator"
        and bot.get("can_post_messages") is True
        and isinstance(actor, dict)
        and isinstance(actor.get("user"), dict)
        and type(actor["user"].get("id")) is int
        and actor["user"]["id"] == link.telegram_user_id
        and actor["user"].get("is_bot") is False
        and actor.get("status") in {"administrator", "creator"}
    )


def _suspend(row):
    """A confirmed access change invalidates pending work and holds in-flight work."""
    with transaction.atomic():
        channel = TelegramChannel.objects.select_for_update().filter(pk=row.channel_id).first()
        if channel is None:
            return
        context = _context(channel)
        if context is None or _scope(channel, context) != row.payload.get("_scope"):
            return
        now = timezone.now()
        TelegramChannel.objects.filter(pk=channel.pk).update(is_active=False, updated_at=now)
        TelegramChannelDelivery.objects.filter(channel=channel, status="pending").update(
            status="failed", error="Channel access changed. Verify and reconnect the channel.", updated_at=now
        )
        TelegramChannelDelivery.objects.filter(channel=channel, status="sending").update(
            status="unknown",
            error="Channel access changed while sending. Inspect Telegram before retrying.",
            updated_at=now,
        )


def send_one(delivery_id):
    row = _claim(delivery_id)
    if row is None:
        return "skipped"
    attempted = False
    try:
        checked = _before_transport(row)
        if checked is None:
            row.refresh_from_db(fields=["status"])
            return row.status
        channel, context = checked
        api = BotAPI(context[0].token)
        if not _native_verified(api, channel, context):
            recorded = _finish(
                row, status="failed", next_attempt_at=None, error="Telegram channel authority could not be verified."
            )
            _suspend(row)
            return "failed" if recorded else "unknown"
        checked = _before_transport(row)
        if checked is None:
            row.refresh_from_db(fields=["status"])
            return row.status
        channel, _ = checked
        attempted = True
        result = api.call(
            "sendMessage",
            {"chat_id": channel.chat_id, "text": row.payload["text"], "link_preview_options": {"is_disabled": True}},
        )
        if (
            not isinstance(result, dict)
            or type(result.get("message_id")) is not int
            or result["message_id"] <= 0
            or not isinstance(result.get("chat"), dict)
            or type(result["chat"].get("id")) is not int
            or result["chat"]["id"] != channel.chat_id
            or result["chat"].get("type") != "channel"
        ):
            _finish(
                row,
                status="unknown",
                next_attempt_at=None,
                error="Telegram did not return a verified channel receipt. Inspect the channel before resending.",
            )
            return "unknown"
        recorded = _finish(row, status="sent", native_message_id=result["message_id"], error="", next_attempt_at=None)
        return "sent" if recorded else "unknown"
    except TelegramAPIError as exc:
        if attempted and exc.ambiguous:
            status, error = "unknown", "The channel send outcome is unknown. Inspect Telegram before resending."
        elif exc.kind in {"forbidden", "403", "chat_migrated"}:
            recorded = _finish(
                row,
                status="failed",
                next_attempt_at=None,
                error="Channel access changed. Verify and reconnect the channel.",
            )
            _suspend(row)
            return "failed" if recorded else "unknown"
        elif (
            not exc.ambiguous
            and exc.kind in {"rate_limited", "rate_limit", "429", "connect", "connection", "preconnect"}
            and row.attempts < MAX_SEND_ATTEMPTS
        ):
            delay = max(5, int(exc.retry_after or 5 * 2 ** (row.attempts - 1)))
            recorded = _finish(
                row,
                status="pending",
                error="Telegram is temporarily unavailable; a bounded channel retry is queued.",
                next_attempt_at=timezone.now() + timedelta(seconds=delay),
            )
            return "pending" if recorded else "unknown"
        else:
            status, error = "failed", "Telegram channel verification or delivery failed. Review channel setup."
        recorded = _finish(row, status=status, error=error, next_attempt_at=None)
        return status if recorded else "unknown"
    except Exception:
        status = "unknown" if attempted else "failed"
        recorded = _finish(
            row,
            status=status,
            next_attempt_at=None,
            error=(
                "The channel send outcome could not be recorded. Inspect Telegram before resending."
                if attempted
                else "Channel setup or status is unavailable. Review it before retrying."
            ),
        )
        return status if recorded else "unknown"


def recover_stale_deliveries(*, limit=25):
    with transaction.atomic():
        rows = list(
            TelegramChannelDelivery.objects.select_for_update(skip_locked=True)
            .filter(status="sending", claimed_at__lt=timezone.now() - SEND_CLAIM_TIMEOUT)
            .order_by("claimed_at")[:limit]
        )
        for row in rows:
            row.status = "unknown"
            row.error = "Channel sending was interrupted. Inspect Telegram before sending this status again."
            row.save(update_fields=["status", "error", "updated_at"])
    return len(rows)


def drain_channels(*, limit=25):
    limit = min(100, max(1, limit))
    recovered = recover_stale_deliveries(limit=limit)
    ids = list(
        TelegramChannelDelivery.objects.filter(
            Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=timezone.now()), status="pending"
        )
        .order_by("created_at")
        .values_list("pk", flat=True)[:limit]
    )
    outcomes = {"unknown": recovered} if recovered else {}
    for delivery_id in ids:
        status = send_one(delivery_id)
        outcomes[status] = outcomes.get(status, 0) + 1
    return outcomes
