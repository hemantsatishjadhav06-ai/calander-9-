"""Client-safe event wording and exact-conversation mirrors, never raw notification bodies.

Two kinds of delivery live here. Mirrors repeat a thread's own messages into
the chats bound to that thread. The manager inbox (``inbox.tell``) goes
further: whenever something needs a person, every current approver hears
about it in their own paired private chat, with the review card when they
may act from Telegram and a link into the app otherwise.
"""

import hashlib
from datetime import timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from . import inbox
from .models import TelegramChat, TelegramUserLink
from .outbox import link_button, link_keyboard, permitted_chat, queue_message
from .permissions import TelegramPermissionDenied, fresh_member, internal_member

#: The intake's own hint becomes stale once the confirm button is attached to the card.
_BRIEF_HINT = (
    "Send /brief to open the current confirmation card after checking these source facts. "
    "Its explicit button only starts a draft for human approval."
)


def _agent_result(message):
    job = message.job
    if message.author_kind != "agent" or message.is_internal or job is None or not isinstance(job.result, dict):
        return None
    return job


def _confirmation_for(message, chat):
    """The requester's private chat gets the brief card with its one-use button instead of a hint."""
    job = _agent_result(message)
    return bool(
        job is not None
        and chat.audience == "private"
        and chat.private_user_id is not None
        and chat.private_user_id == job.requested_by_id
        and job.result.get("awaiting_confirmation") is True
        and job.result.get("message_id") == str(message.pk)
    )


def _progress_markup(message, chat):
    """When the team started a draft, the person gets one button to its progress page."""
    job = _agent_result(message)
    if job is None or chat.audience != "private" or chat.private_user_id != job.requested_by_id:
        return None
    brief_id = job.result.get("brief_id")
    if not brief_id or job.result.get("message_id") != str(message.pk):
        return None
    try:
        path = reverse("studio:detail", kwargs={"workspace_id": job.workspace_id, "brief_id": UUID(str(brief_id))})
    except (ValueError, TypeError, AttributeError):
        return None
    return link_keyboard(link_button("Open progress", path))


def _routine_markup(message, chat):
    """A routine the manager proposed: Telegram has no card, so the reply carries the way to turn it on.

    The button is a plain link to the Routines page (its own permissions
    apply there); it goes to the team's chats only: the requester's private
    chat and the internal team group, never a client group.
    """
    job = _agent_result(message)
    if job is None or chat.audience == "client" or job.result.get("message_id") != str(message.pk):
        return None
    if chat.audience == "private" and chat.private_user_id != job.requested_by_id:
        return None
    if not job.result.get("routine_id"):
        return None
    return link_keyboard(
        link_button(
            "Open Routines to turn it on", reverse("studio:routines", kwargs={"workspace_id": job.workspace_id})
        )
    )


def brief_card(message_id, chat_id):
    """Attach the one-use confirm button to the manager's brief in the requester's private chat.

    Runs outside agency work (the mirror defers it through a task when needed)
    because issuing a button is a person-facing step the guards keep away from
    agents. Falls back to the plain mirror when the card cannot be issued.
    """
    from apps.studio.models import Message

    from .actions import TelegramActionError, issue_brief_confirmation

    message = Message.objects.select_related("conversation", "job").filter(pk=message_id).first()
    chat = (
        TelegramChat.objects.select_related("conversation", "connection__workspace__organization")
        .filter(pk=chat_id, is_active=True, audience="private")
        .first()
    )
    if message is None or chat is None or chat.conversation_id != message.conversation_id or not permitted_chat(chat):
        return 0
    key = f"conversation:{message.conversation_id}:message:{message.pk}"
    link = TelegramUserLink.objects.filter(
        connection=chat.connection, user_id=chat.private_user_id, is_active=True
    ).first()
    card = None
    if link is not None and _confirmation_for(message, chat):
        try:
            card = issue_brief_confirmation(chat, link, confirmation_message=message)
        except (TelegramActionError, PermissionDenied):
            card = None
    if card is None:
        return len(queue_message(chat, f"{message.sender_name}:\n{message.body}", source_key=key))
    from apps.studio.jobtypes.chat import TELEGRAM_BRIEF_HINT

    text = card["text"]
    for hint in (_BRIEF_HINT, TELEGRAM_BRIEF_HINT):
        text = text.replace(hint, "")
    text = text.replace("\n\n\n", "\n\n").strip()
    return len(queue_message(chat, text, source_key=key, reply_markup=card.get("reply_markup")))


def mirror_message(message_id):
    from apps.studio import guards
    from apps.studio.models import Message

    message = Message.objects.select_related("conversation", "job").filter(pk=message_id).first()
    if message is None:
        return 0
    if not TelegramChat.objects.filter(conversation_id=message.conversation_id).exists():
        from .workflow_bridge import queue_workflow_message

        return queue_workflow_message(message.pk)
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
        if _confirmation_for(message, chat):
            if guards.in_agent_work():
                from .tasks import send_brief_card

                send_brief_card(str(message.pk), str(chat.pk))
                continue
            count += 1 if brief_card(message.pk, chat.pk) else 0
            continue
        text = f"{message.sender_name}:\n{message.body}"
        markup = _progress_markup(message, chat)
        if markup is not None:
            text += "\n\nThe team started."
        else:
            markup = _routine_markup(message, chat)
        if queue_message(
            chat, text, source_key=f"conversation:{message.conversation_id}:message:{message.pk}", reply_markup=markup
        ):
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
    # Titles and captions are customer-facing composer content; internal_notes never leave.
    return inbox.post_label(post)


def _channel_post_event(post, event, *, source_key, brief=None):
    """A channel receives only fixed status text for a nonprivate canonical post."""
    from .channel_outbox import public_post, queue_channel_event
    from .models import TelegramChannel

    if not public_post(post):
        return 0
    channels = TelegramChannel.objects.filter(connection__workspace_id=post.workspace_id, is_active=True)
    return sum(
        queue_channel_event(channel, event, source_key=source_key, post=post, brief=brief) is not None
        for channel in channels
    )


def _workflow_post_event(post, event, *, source_key, brief=None):
    """Only the opted-in original web author receives a private fixed status."""
    from .workflow_bridge import queue_post_event

    return queue_post_event(post, event, source_key=source_key, brief=brief)


def _open_button(label, path):
    return link_keyboard(link_button(label, path))


def ready_draft(brief_id, *, post_id=None, author_id=None):
    """A finished canonical Studio handoff: status to channels and the author, the review card to approvers."""
    from apps.studio.models import StudioBrief

    try:
        brief_id = UUID(str(brief_id))
    except (ValueError, TypeError, AttributeError):
        return 0
    rows = StudioBrief.objects.select_related("post", "workspace").filter(
        pk=brief_id,
        post__isnull=False,
        status__in=["ready", "approved"],
        stage="done",
        finished_at__isnull=False,
        revision__gte=1,
    )
    if post_id is not None:
        rows = rows.filter(post_id=post_id)
    if author_id is not None:
        rows = rows.filter(author_id=author_id)
    brief = rows.first()
    if brief is None or brief.workspace_id != brief.post.workspace_id:
        return 0
    key = f"studio:{brief.pk}:revision:{brief.revision}:draft-ready"
    count = _channel_post_event(brief.post, "draft", source_key=key, brief=brief) + _workflow_post_event(
        brief.post, "draft", source_key=key, brief=brief
    )
    return count + inbox.tell(brief.workspace, "", source_key=key, event="draft_ready", post=brief.post)


def _time(value, workspace):
    try:
        zone = ZoneInfo(workspace.effective_timezone)
    except (ValueError, ZoneInfoNotFoundError):
        zone = ZoneInfo("UTC")
    return timezone.localtime(value, zone).isoformat()


def platform_receipt(platform_post_id):
    from apps.composer.models import PlatformPost
    from apps.publisher.delivery import state

    pp = PlatformPost.objects.select_related("post__workspace", "social_account").filter(pk=platform_post_id).first()
    if pp is None or pp.social_account.workspace_id != pp.post.workspace_id:
        return 0
    account = pp.social_account.display_label or pp.social_account.platform
    label = _post_label(pp.post)
    # The provider handle and timestamp are evidence of confirmed publication;
    # a generic Notification titled "Published" is not sufficient.
    if pp.status == "published" and pp.platform_post_id and pp.published_at:
        text = f"Published: {label}\nAccount: {account}\nConfirmed at {_time(pp.published_at, pp.post.workspace)}\nReceipt: {pp.platform_post_id}"
        event = f"published:{pp.platform_post_id}"
        channel_event = "published"
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
        channel_event = "failed"
    elif pp.status == "scheduled" and (pp.scheduled_at or pp.post.scheduled_at):
        when = pp.scheduled_at or pp.post.scheduled_at
        text = f"Scheduled: {label}\nAccount: {account}\nTime: {_time(when, pp.post.workspace)}\nSM Bean will report the confirmed delivery."
        event = f"scheduled:{when.isoformat()}:{pp.approved_revision or 0}"
        channel_event = "scheduled"
    else:
        return 0
    count = 0
    for chat in _post_chats(pp.post):
        if queue_message(chat, text, source_key=f"platform:{pp.pk}:{event}"):
            count += 1
    count += _channel_post_event(pp.post, channel_event, source_key=f"platform:{pp.pk}:{event}")
    count += _workflow_post_event(pp.post, channel_event, source_key=f"platform:{pp.pk}:{event}")
    if pp.status == "failed":
        count += inbox.tell(
            pp.post.workspace,
            f"Delivery needs you: {label} on {account}.\n{detail}",
            source_key=f"platform:{pp.pk}:{event}",
            event="delivery_failed",
            reply_markup=_open_button("Open delivery", inbox.approvals_path(pp.post.workspace_id)),
        )
    return count


_INBOX_WORDING = {
    "post_submitted": "A post is ready for your approval.",
    "client_approval_requested": "The client was asked to sign off.",
    "approval_reminder": "Still waiting for your approval.",
    "approval_stalled": "This approval has waited too long. Please take a look.",
}


def _report_notice(notice):
    """A finished report: one line and a link to every approver, keyed by the report itself."""
    from apps.workspaces.models import Workspace

    data = notice.data
    workspace = Workspace.objects.filter(pk=data.get("workspace_id")).first() if data.get("workspace_id") else None
    if workspace is None:
        return 0
    reference = data.get("report_id") or data.get("job_id") or data.get("week_start") or str(notice.pk)
    return inbox.tell(
        workspace,
        "Your weekly report is ready.",
        source_key=f"report:{reference}",
        event="report_generated",
        reply_markup=_open_button(
            "Open the report", reverse("studio:autopilot", kwargs={"workspace_id": workspace.pk})
        ),
    )


def notification_event(notification_id):
    from apps.composer.models import Post
    from apps.notifications.models import Notification

    notice = Notification.objects.filter(pk=notification_id).first()
    if notice is None or not isinstance(notice.data, dict):
        return 0
    data = notice.data
    if notice.event_type == "autopilot_planned":
        return _week_notification(notice)
    if notice.event_type == "report_generated":
        return _report_notice(notice)
    # Replies are mirrored from their actual Message with visibility checks.
    # Per-person notification wording may contain staff quotes or cost errors.
    if notice.event_type in {"team_message", "post_failed", "post_published"}:
        if data.get("platform_post_id"):
            return platform_receipt(data["platform_post_id"])
        if notice.event_type == "team_message" and data.get("kind") == "routine":
            return _routine_notice(notice)
        return 0
    wording = {
        "post_submitted": "The team submitted this post for review. Final human approval is still required.",
        "post_approved": "A person approved this post in SM Bean. Publication follows its approved destinations and time.",
        "post_changes_requested": "Changes were requested. The team will prepare a fresh revision for review.",
        "post_rejected": "This revision was rejected and will not be published.",
        "client_approval_requested": "Your sign-off is requested in SM Bean. Internal publication approval remains separate.",
        "approval_hold_requested": "A client requested a hold. The team will review it before publication continues.",
        "approval_reminder": "A human review is still waiting in SM Bean.",
        "approval_stalled": "An approval has been waiting too long in SM Bean.",
    }.get(notice.event_type)
    if wording is None or not data.get("post_id"):
        return 0
    post = Post.objects.select_related("workspace").filter(pk=data["post_id"]).first()
    if post is None or (data.get("workspace_id") and str(post.workspace_id) != str(data["workspace_id"])):
        return 0
    draft_count = 0
    ready_brief = False
    if notice.event_type == "post_submitted":
        if data.get("studio_brief_id"):
            draft_count = ready_draft(data["studio_brief_id"], post_id=post.pk, author_id=notice.user_id)
            ready_brief = True
        else:
            # The normal approval engine notifies reviewers before Studio's
            # author notice. Its already committed canonical handoff must
            # announce draft readiness before the review status too.
            ready_id = (
                post.studio_briefs.filter(status__in=["ready", "approved"], stage="done", finished_at__isnull=False)
                .order_by("-finished_at")
                .values_list("pk", flat=True)
                .first()
            )
            if ready_id:
                draft_count = ready_draft(ready_id, post_id=post.pk)
                ready_brief = True
    # Per-user notices may target reviewers who do not use Telegram. The web
    # workflow author is authenticated by their own explicit opt-in and
    # pairing, rather than inheriting the triggering recipient's identity.
    version = hashlib.sha256(f"{post.updated_at.isoformat()}:{data.get('revision', '')}".encode()).hexdigest()[:20]
    key = f"event:{notice.event_type}:post:{post.pk}:{version}"
    channel_event = {
        "post_submitted": "review",
        "post_approved": "approved",
        "post_changes_requested": "changes",
        "post_rejected": "changes",
        "client_approval_requested": "review",
        "approval_hold_requested": "changes",
        "approval_reminder": "review",
        "approval_stalled": "review",
    }[notice.event_type]
    private_count = _workflow_post_event(post, channel_event, source_key=key)
    # Every current approver hears what needs them, whoever this notice was for.
    # A draft the team made already arrived as its review card.
    inbox_count = 0
    reminder = notice.event_type in {"approval_reminder", "approval_stalled"}
    if notice.event_type in _INBOX_WORDING and (reminder or not ready_brief):
        # A reminder brings a fresh card (the earlier buttons have expired) and
        # reaches Telegram once per post, revision and workspace-local day.
        inbox_key = (
            f"{key}:{timezone.localtime(timezone.now(), inbox.zone_of(post.workspace)):%Y-%m-%d}" if reminder else key
        )
        inbox_count = inbox.tell(
            post.workspace,
            f"{_post_label(post)}\n{_INBOX_WORDING[notice.event_type]}",
            source_key=inbox_key,
            event=notice.event_type,
            reply_markup=_open_button("Open to approve", inbox.post_path(post)),
            post=post if reminder else None,
        )
    base = draft_count + private_count + inbox_count
    # The triggering recipient must remain paired to this exact workspace.
    link = TelegramUserLink.objects.filter(
        connection__workspace_id=post.workspace_id, user=notice.user, is_active=True
    ).first()
    if link is None:
        return base
    try:
        if fresh_member(link) is None:
            return base
    except TelegramPermissionDenied:
        return base
    # Collapse per-user copies of the same revision/event in a group.
    count = base
    for chat in _post_chats(post):
        if chat.audience == "private" and chat.private_user_id != notice.user_id:
            continue
        if queue_message(chat, f"{_post_label(post)}\n{wording}", source_key=key):
            count += 1
    count += _channel_post_event(post, channel_event, source_key=key)
    return count


def _routine_notice(notice):
    """A routine that failed or was interrupted: one line to every approver's inbox, with a link to Routines.

    The in-app notice goes to the routine's author once per run
    (``apps.studio.routines._notify_creator``); its body is the routine's own
    plain sentence, never a quote from the thread. The run id keys the inbox
    message, so a repeated notice never reaches Telegram twice.
    """
    from apps.studio.models import Routine

    data = notice.data
    try:
        routine_id, workspace_id = UUID(str(data.get("routine_id"))), UUID(str(data.get("workspace_id")))
    except (ValueError, TypeError, AttributeError):
        return 0
    routine = Routine.objects.select_related("workspace").filter(pk=routine_id, workspace_id=workspace_id).first()
    if routine is None:
        return 0
    body = " ".join(str(notice.body or "").split())[:300] or "This routine needs a look."
    run_id = str(data.get("run_id") or "") or f"notice:{notice.pk}"
    return inbox.tell(
        routine.workspace,
        f"Routine “{routine.display_title}” needs you: {body}",
        source_key=f"routine:{routine.pk}:{run_id}",
        event="routine",
        reply_markup=_open_button("Open routines", reverse("studio:routines", kwargs={"workspace_id": workspace_id})),
    )


def _week_notification(notice):
    """A completed canonical plan: every approver's inbox, plus its internal requesting thread."""
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
    ready = week.job.briefs.filter(workspace_id=workspace_id, status__in=["ready", "approved"]).count()
    failed = week.job.briefs.filter(workspace_id=workspace_id, status="failed").count()
    short = f"Next week is planned: {ready} draft{'s' if ready != 1 else ''} ready for your approval."
    if failed:
        short += f" {failed} need{'s' if failed == 1 else ''} the team's attention."
    count = inbox.tell(
        week.workspace,
        short,
        source_key=f"week:{week.pk}:planned",
        event="autopilot_planned",
        reply_markup=_open_button("Open approvals", inbox.approvals_path(workspace_id)),
    )
    link = TelegramUserLink.objects.filter(
        connection__workspace_id=workspace_id, user_id=notice.user_id, is_active=True
    ).first()
    if link is None:
        return count
    try:
        member = fresh_member(link, "approve_posts")
        if not internal_member(member):
            return count
    except TelegramPermissionDenied:
        return count
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
    return sum(platform_receipt(item) for item in ids) + _sweep_ready_drafts(limit=limit)


def _sweep_ready_drafts(*, limit=25):
    """Recover queryset handoffs or missed notices without broadcasting ideas."""
    from apps.common.models import TaskHeartbeat
    from apps.studio.models import StudioBrief

    checkpoint, _ = TaskHeartbeat.objects.get_or_create(task_name="apps.telegram.draft_cursor")
    rows = StudioBrief.objects.filter(
        post__isnull=False,
        post__workspace__telegram_connection__is_active=True,
        status__in=["ready", "approved"],
        stage="done",
        finished_at__isnull=False,
        revision__gte=1,
        updated_at__gte=timezone.now() - timedelta(days=7),
    )
    last_pk = checkpoint.metadata.get("last_pk") if isinstance(checkpoint.metadata, dict) else None
    if last_pk:
        rows = rows.filter(pk__gt=last_pk)
    ids = list(rows.order_by("pk").values_list("pk", flat=True)[: min(100, max(1, limit))])
    checkpoint.metadata = {"last_pk": str(ids[-1])} if ids else {}
    checkpoint.save(update_fields=["metadata", "updated_at"])
    return sum(ready_draft(item) for item in ids)
