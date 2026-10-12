"""Client-safe event wording and exact-conversation mirrors, never raw notification bodies."""

import hashlib
from datetime import timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import Q
from django.utils import timezone

from .models import TelegramChat, TelegramUserLink
from .outbox import permitted_chat, queue_message
from .permissions import TelegramPermissionDenied, fresh_member, internal_member


def mirror_message(message_id):
    from apps.studio.models import Message

    message = Message.objects.select_related("conversation").filter(pk=message_id).first()
    if message is None:
        return 0
    chats = TelegramChat.objects.select_related("conversation", "connection__workspace__organization").filter(
        conversation=message.conversation, is_active=True
    )
    count = 0
    for chat in chats:
        if not permitted_chat(chat):
            continue
        if message.conversation.audience == "client" and (
            message.is_internal or message.conversation.audience != "client" or message.author_kind == "system"
        ):
            continue
        # Private worker threads cannot mirror another person's authored note.
        if chat.audience == "private" and message.author_kind == "client" and message.author_id != chat.private_user_id:
            continue
        text = f"{message.sender_name}:\n{message.body}"
        if queue_message(chat, text, source_key=f"conversation:{message.conversation_id}:message:{message.pk}"):
            count += 1
    return count


def _post_chats(post):
    originating_threads = post.studio_briefs.filter(
        workspace_id=post.workspace_id,
        job__workspace_id=post.workspace_id,
        job__conversation__workspace_id=post.workspace_id,
    ).values_list("job__conversation_id", flat=True)
    return (
        TelegramChat.objects.select_related("conversation", "connection__workspace__organization")
        .filter(
            Q(conversation__post=post) | Q(conversation__brief__post=post) | Q(conversation_id__in=originating_threads),
            connection__workspace_id=post.workspace_id,
            is_active=True,
        )
        .distinct()
    )


def _post_label(post):
    # Titles are customer-facing composer content; internal_notes never leave.
    return post.title[:100] or "Your post"


def _time(value, workspace):
    try:
        zone = ZoneInfo(workspace.effective_timezone)
    except (ValueError, ZoneInfoNotFoundError):
        zone = ZoneInfo("UTC")
    return timezone.localtime(value, zone).isoformat()


def platform_receipt(platform_post_id):
    from apps.composer.models import PlatformPost
    from apps.publisher.delivery import state

    pp = PlatformPost.objects.select_related("post", "social_account").filter(pk=platform_post_id).first()
    if pp is None or pp.social_account.workspace_id != pp.post.workspace_id:
        return 0
    account = pp.social_account.display_label or pp.social_account.platform
    label = _post_label(pp.post)
    # The provider handle and timestamp are evidence of confirmed publication;
    # a generic Notification titled "Published" is not sufficient.
    if pp.status == "published" and pp.platform_post_id and pp.published_at:
        text = f"Published: {label}\nAccount: {account}\nConfirmed at {_time(pp.published_at, pp.post.workspace)}\nReceipt: {pp.platform_post_id}"
        event = f"published:{pp.platform_post_id}"
    elif pp.status == "failed":
        outcome = state(pp).get("kind")
        detail = (
            "Delivery is uncertain. The team must verify the platform before retrying."
            if outcome == "unknown"
            else "The approved time expired. A person must review a new time."
            if outcome == "expired"
            else "Publication failed. The team is checking the account and will update you."
        )
        text = f"{label}\nAccount: {account}\n{detail}"
        event = f"failed:{outcome or 'failed'}:{pp.retry_count}:{pp.approved_revision or 0}"
    elif pp.status == "scheduled" and (pp.scheduled_at or pp.post.scheduled_at):
        when = pp.scheduled_at or pp.post.scheduled_at
        text = f"Scheduled: {label}\nAccount: {account}\nTime: {_time(when, pp.post.workspace)}\nSM Bean will report the confirmed delivery."
        event = f"scheduled:{when.isoformat()}:{pp.approved_revision or 0}"
    else:
        return 0
    count = 0
    for chat in _post_chats(pp.post):
        if queue_message(chat, text, source_key=f"platform:{pp.pk}:{event}"):
            count += 1
    return count


def notification_event(notification_id):
    from apps.composer.models import Post
    from apps.notifications.models import Notification

    notice = Notification.objects.filter(pk=notification_id).first()
    if notice is None or not isinstance(notice.data, dict):
        return 0
    data = notice.data
    if notice.event_type == "autopilot_planned":
        return _week_notification(notice)
    # Replies are mirrored from their actual Message with visibility checks.
    # Per-person notification wording may contain staff quotes or cost errors.
    if notice.event_type in {"team_message", "post_failed", "post_published"}:
        if data.get("platform_post_id"):
            return platform_receipt(data["platform_post_id"])
        return 0
    wording = {
        "post_submitted": "The team submitted this post for review. Final human approval is still required.",
        "post_approved": "A person approved this post in SM Bean. Publication follows its approved destinations and time.",
        "post_changes_requested": "Changes were requested. The team will prepare a fresh revision for review.",
        "post_rejected": "This revision was rejected and will not be published.",
        "client_approval_requested": "Your sign-off is requested in SM Bean. Internal publication approval remains separate.",
        "approval_hold_requested": "A client requested a hold. The team will review it before publication continues.",
        "approval_reminder": "A human review is still waiting in SM Bean.",
    }.get(notice.event_type)
    if wording is None or not data.get("post_id"):
        return 0
    post = Post.objects.filter(pk=data["post_id"]).first()
    if post is None or (data.get("workspace_id") and str(post.workspace_id) != str(data["workspace_id"])):
        return 0
    # The triggering recipient must remain paired to this exact workspace.
    link = TelegramUserLink.objects.filter(
        connection__workspace_id=post.workspace_id, user=notice.user, is_active=True
    ).first()
    if link is None:
        return 0
    try:
        if fresh_member(link) is None:
            return 0
    except TelegramPermissionDenied:
        return 0
    # Collapse per-user copies of the same revision/event in a group.
    version = hashlib.sha256(f"{post.updated_at.isoformat()}:{data.get('revision', '')}".encode()).hexdigest()[:20]
    key = f"event:{notice.event_type}:post:{post.pk}:{version}"
    count = 0
    for chat in _post_chats(post):
        if chat.audience == "private" and chat.private_user_id != notice.user_id:
            continue
        if queue_message(chat, f"{_post_label(post)}\n{wording}", source_key=key):
            count += 1
    return count


def _week_notification(notice):
    """A completed canonical plan reaches only its internal requesting thread."""
    from apps.studio.models import AutopilotWeek

    data = notice.data
    try:
        week_id, workspace_id = UUID(str(data.get("week_id"))), UUID(str(data.get("workspace_id")))
    except (ValueError, TypeError, AttributeError):
        return 0
    week = (
        AutopilotWeek.objects.select_related("workspace", "job__conversation")
        .filter(
            pk=week_id,
            workspace_id=workspace_id,
            status="planned",
            job__kind="plan",
            job__status="done",
            job__workspace_id=workspace_id,
            job__conversation__workspace_id=workspace_id,
            job__conversation__audience="internal",
        )
        .first()
    )
    if week is None:
        return 0
    link = TelegramUserLink.objects.filter(
        connection__workspace_id=workspace_id, user_id=notice.user_id, is_active=True
    ).first()
    if link is None:
        return 0
    try:
        member = fresh_member(link, "approve_posts")
        if not internal_member(member):
            return 0
    except TelegramPermissionDenied:
        return 0
    ready = week.job.briefs.filter(workspace_id=workspace_id, status__in=["ready", "approved"]).count()
    failed = week.job.briefs.filter(workspace_id=workspace_id, status="failed").count()
    text = (
        f"SM Bean completed the week plan starting {week.week_start.isoformat()}.\n"
        f"Drafts ready for human review: {ready}."
    )
    if failed:
        text += f"\nDrafts needing the team's attention: {failed}."
    text += "\nSend /week for the current plan. Every post still needs final human approval before publication."
    chats = TelegramChat.objects.filter(
        connection_id=link.connection_id,
        conversation_id=week.job.conversation_id,
        audience__in=["team", "private"],
        is_active=True,
    )
    count = 0
    for chat in chats:
        if chat.audience == "private" and chat.private_user_id != notice.user_id:
            continue
        if queue_message(chat, text, source_key=f"week:{week.pk}:planned"):
            count += 1
    return count


def sweep_receipts(*, limit=25):
    """Catch publisher queryset writes that intentionally bypass model signals."""
    from apps.common.models import TaskHeartbeat
    from apps.composer.models import PlatformPost

    checkpoint, _ = TaskHeartbeat.objects.get_or_create(task_name="apps.telegram.receipt_cursor")
    rows = PlatformPost.objects.filter(
        post__workspace__telegram_connection__is_active=True,
        status__in=["published", "failed", "scheduled"],
        updated_at__gte=timezone.now() - timedelta(days=7),
    )
    last_pk = checkpoint.metadata.get("last_pk") if isinstance(checkpoint.metadata, dict) else None
    if last_pk:
        rows = rows.filter(pk__gt=last_pk)
    ids = list(rows.order_by("pk").values_list("pk", flat=True)[: min(100, max(1, limit))])
    # A cyclic cursor keeps older unsent receipts from starving behind the
    # first batch. Semantic delivery keys make every revisit harmless.
    checkpoint.metadata = {"last_pk": str(ids[-1])} if ids else {}
    checkpoint.save(update_fields=["metadata", "updated_at"])
    return sum(platform_receipt(item) for item in ids)
