"""Explicit author-only web workflow questions, answered through verified private receipts."""

import hashlib
import json
import re
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import UUID

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.studio import chat as studio_chat
from apps.studio import creative_brief, customer_workflow
from apps.studio.models import AgencyJob, Conversation, Message

from .models import (
    TelegramChat,
    TelegramConnection,
    TelegramDelivery,
    TelegramUpdate,
    TelegramUserLink,
    TelegramWorkflowPrompt,
)
from .permissions import fresh_member, internal_member
from .processing import CURRENT_UPDATE_ID, connection_epoch

PREFIX = "workflow-prompt:"
PROMPT_TTL = timedelta(days=7)
_KEY = re.compile(r"^workflow-prompt:([0-9a-f-]{36}):part:0$")
CONTROL_TEXT = {
    "pause": "Your task was paused. Open SM Bean to see where it stands.",
    "resume": "Your task was resumed. Open SM Bean to see where it stands.",
    "retry": "A new attempt was requested for your task. Open SM Bean to see where it stands.",
    "cancel": "Your task was stopped. Open SM Bean to see where it stands.",
}


def _hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _thread_link(workspace, conversation):
    base = getattr(settings, "APP_URL", "") or ""
    try:
        parsed = urlsplit(base)
        if (
            len(base) > 512
            or parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]{1,5})?", parsed.netloc)
        ):
            return ""
        return base.rstrip("/") + customer_workflow._thread_url(workspace, conversation)
    except (TypeError, ValueError):
        return ""


def _author_context(conversation, author, *, locked=False):
    workspace, person, member, original = customer_workflow.validate_author(
        conversation, author, locked=locked, require_telegram_opt_in=True
    )
    if TelegramChat.objects.filter(conversation=conversation).exists():
        raise PermissionDenied("Telegram-origin threads cannot become web workflow reply routes.")
    connection = TelegramConnection.objects.filter(workspace=workspace, is_active=True, webhook_status="active").first()
    link = TelegramUserLink.objects.filter(connection=connection, user=person, is_active=True).first()
    if connection is None or link is None:
        raise PermissionDenied("Link your own Telegram account before receiving workflow questions.")
    paired = fresh_member(link, "create_posts", locked=locked)
    if not internal_member(paired) or paired.workspace_id != workspace.pk:
        raise PermissionDenied("Your active agency pairing is required.")
    private = (
        TelegramChat.objects.select_related("conversation", "connection__workspace__organization")
        .filter(
            connection=connection,
            chat_id=link.telegram_user_id,
            private_user=person,
            chat_type="private",
            audience="private",
            is_active=True,
        )
        .first()
    )
    from .outbox import permitted_chat

    if private is None or not private.conversation.is_private or not permitted_chat(private):
        raise PermissionDenied("Create a fresh personal Telegram link before receiving workflow questions.")
    opt_in = (
        Message.objects.filter(
            conversation=conversation,
            action=customer_workflow.TELEGRAM_OPT_IN_ACTION,
            author=person,
            author_kind=Message.AuthorKind.STAFF,
            is_internal=True,
            action_status=Message.ActionStatus.DONE,
        )
        .order_by("pk")
        .first()
    )
    return connection, link, private, paired, original, opt_in


def _snapshot(conversation, context):
    from .outbox import _scope
    from .provisioning import channel_authority_digest

    connection, link, private, member, original, opt_in = context
    return {
        "conversation_id": str(conversation.pk),
        "workspace_id": str(member.workspace_id),
        "organization_id": str(member.workspace.organization_id),
        "author_id": str(member.user_id),
        "idea_id": str(original.pk),
        "idea_digest": _hash(original.body),
        "opt_in_id": str(opt_in.pk),
        "connection_id": str(connection.pk),
        "connection_epoch": connection_epoch(connection),
        "user_link_id": str(link.pk),
        "pairing_epoch": link.updated_at.isoformat(),
        "telegram_user_id": link.telegram_user_id,
        "chat_epoch": private.updated_at.isoformat(),
        "private_scope": _scope(private),
        "authority_digest": channel_authority_digest(member),
    }


def _source_snapshot(message, job):
    return {
        "message": None
        if message is None
        else {
            "id": str(message.pk),
            "conversation": str(message.conversation_id),
            "kind": message.author_kind,
            "internal": message.is_internal,
            "agent": message.agent,
            "job": str(message.job_id),
            "body_digest": _hash(message.body),
        },
        "job": None
        if job is None
        else {
            "id": str(job.pk),
            "workspace": str(job.workspace_id),
            "conversation": str(job.conversation_id),
            "author": str(job.requested_by_id),
            "kind": job.kind,
            "revision": job.revision,
            "status": job.status,
            "result_digest": _hash(json.dumps(job.result, sort_keys=True, separators=(",", ":"))),
        },
    }


def _prompt_context(prompt, *, locked=False):
    if prompt.author_id is None or prompt.user_link_id is None or prompt.expires_at <= timezone.now():
        raise PermissionDenied("This workflow reply request is no longer active.")
    context = _author_context(prompt.conversation, prompt.author, locked=locked)
    connection, link, private, member, _, _ = context
    if (
        prompt.workspace_id != member.workspace_id
        or prompt.organization_id != member.workspace.organization_id
        or prompt.user_link_id != link.pk
        or prompt.chat_id != private.pk
        or not isinstance(prompt.snapshot, dict)
        or prompt.snapshot.get("binding") != _snapshot(prompt.conversation, context)
        or connection.pk != private.connection_id
    ):
        raise PermissionDenied("This workflow pairing or workspace changed.")
    job, source_message = None, None
    if prompt.source_job_id is not None:
        job = AgencyJob.objects.filter(
            pk=prompt.source_job_id,
            workspace_id=prompt.workspace_id,
            conversation_id=prompt.conversation_id,
            requested_by_id=prompt.author_id,
        ).first()
        if job is None:
            raise PermissionDenied("This workflow source job is unavailable.")
    if prompt.source_message_id is not None:
        source_message = Message.objects.filter(
            pk=prompt.source_message_id,
            conversation_id=prompt.conversation_id,
            author_kind=Message.AuthorKind.AGENT,
            agent="account_manager",
            is_internal=False,
            job_id=prompt.source_job_id,
        ).first()
        if (
            source_message is None
            or not isinstance(job.result, dict)
            or job.result.get("message_id") != str(source_message.pk)
        ):
            raise PermissionDenied("This workflow source question is unavailable.")
    if prompt.snapshot.get("source") != _source_snapshot(source_message, job):
        raise PermissionDenied("This workflow source changed after the question was prepared.")
    if "post" in prompt.snapshot and not _post_scope_permitted(prompt):
        raise PermissionDenied("This workflow post or its original thread changed.")
    return context


def _queue(conversation, *, source_key, text, source_message=None, source_job=None, post_scope=None):
    from .outbox import queue_message

    with transaction.atomic():
        context = _author_context(conversation, conversation.created_by, locked=True)
        _, link, private, member, _, _ = context
        snapshot = {"binding": _snapshot(conversation, context), "source": _source_snapshot(source_message, source_job)}
        if post_scope is not None:
            snapshot["post"] = post_scope
        prompt, created = TelegramWorkflowPrompt.objects.get_or_create(
            source_key=source_key,
            defaults={
                "conversation": conversation,
                "workspace": member.workspace,
                "organization_id": member.workspace.organization_id,
                "author": member.user,
                "user_link": link,
                "chat": private,
                "snapshot": snapshot,
                "expires_at": timezone.now() + PROMPT_TTL,
                "source_message": source_message,
                "source_job": source_job,
            },
        )
        if not created:
            return 0
        # The exact native Reply operation, rather than copied text, identifies
        # the workflow. No capability URL or private conversation alias exists.
        if source_key.startswith("question:"):
            text += "\n\nReply to this message with details to continue your saved idea in SM Bean. Your reply will appear in that team thread. A reply does not confirm, approve or publish a post."
        else:
            text += "\n\nContinue in your SM Bean idea thread. Questions that accept replies are labelled separately. Final approval remains in SM Bean."
        link = _thread_link(member.workspace, conversation)
        if link:
            text += "\n" + link
        prompt.snapshot["text_digest"] = _hash(text)
        rows = queue_message(private, text, source_key=f"{PREFIX}{prompt.pk}")
        if len(rows) != 1:
            raise PermissionDenied("The workflow question cannot be delivered as one complete prompt.")
        prompt.delivery = rows[0]
        prompt.save(update_fields=["delivery", "snapshot"])
    return 1


def queue_workflow_message(message_id):
    """Mirror bounded canonical missing-input questions; other progress uses fixed text."""
    message = Message.objects.select_related("conversation__created_by", "job").filter(pk=message_id).first()
    if (
        message is None
        or message.author_kind != Message.AuthorKind.AGENT
        or message.is_internal
        or message.agent != "account_manager"
        or message.job_id is None
    ):
        return 0
    job, conversation = message.job, message.conversation
    if (
        job.kind != AgencyJob.Kind.CHAT
        or job.status != AgencyJob.Status.DONE
        or job.conversation_id != conversation.pk
        or job.workspace_id != conversation.workspace_id
        or job.requested_by_id != conversation.created_by_id
        or not isinstance(job.result, dict)
        or job.result.get("message_id") != str(message.pk)
    ):
        return 0
    result = job.result
    question = False
    if message.action == "new_post" and isinstance(result.get("creative_brief"), dict):
        # The author of a web-saved idea is a team member: only the topic is
        # required, the rest is filled from the brand's defaults (A2).
        if result.get("brief_id"):
            text = (
                "Your idea is queued; the team starts it as soon as a slot frees. The draft comes back to you for approval."
                if result.get("queued")
                else "The team started on your idea. The draft comes back to you for approval."
            )
        elif result.get("awaiting_confirmation") is True:
            text = "Your brief is ready for review. Check the brief and source facts in SM Bean before confirming draft preparation."
        elif creative_brief.missing(result["creative_brief"], required=creative_brief.STAFF_REQUIRED):
            text = "Before the team creates a draft: what should this post be about?"
            question = True
        else:
            text = "Please check the connected accounts and your chosen reference in SM Bean before continuing."
    else:
        text = "The team added an update to your idea. Open it in SM Bean for its current status."
    try:
        prefix = "question" if question else "message"
        return _queue(
            conversation, source_key=f"{prefix}:{message.pk}", text=text, source_message=message, source_job=job
        )
    except PermissionDenied:
        return 0


def job_control_event(job_id, revision, action):
    """Only fixed status text, delivered solely to the opted-in original idea author."""
    if action not in CONTROL_TEXT or type(revision) is not int:
        return 0
    job = AgencyJob.objects.select_related("conversation__created_by").filter(pk=job_id, revision=revision).first()
    if job is None or job.conversation_id is None or job.requested_by_id != job.conversation.created_by_id:
        return 0
    try:
        return _queue(
            job.conversation,
            source_key=f"control:{job.pk}:{revision}:{action}",
            text=CONTROL_TEXT[action],
            source_job=job,
        )
    except PermissionDenied:
        return 0


def sweep_workflow_messages(*, limit=25):
    """Repair a lost completion callback without reissuing any existing prompt."""
    from apps.common.models import TaskHeartbeat

    cap = min(100, max(1, limit))
    checkpoint, _ = TaskHeartbeat.objects.get_or_create(task_name="apps.telegram.workflow_cursor")
    handled = TelegramWorkflowPrompt.objects.exclude(source_message_id=None).values("source_message_id")
    rows = (
        Message.objects.filter(
            author_kind=Message.AuthorKind.AGENT,
            is_internal=False,
            agent="account_manager",
            job__kind=AgencyJob.Kind.CHAT,
            job__status=AgencyJob.Status.DONE,
            conversation__messages__action=customer_workflow.TELEGRAM_OPT_IN_ACTION,
            created_at__gte=timezone.now() - PROMPT_TTL,
        )
        .exclude(pk__in=handled)
        .distinct()
    )
    last_pk = checkpoint.metadata.get("last_pk") if isinstance(checkpoint.metadata, dict) else None
    if last_pk:
        rows = rows.filter(pk__gt=last_pk)
    ids = list(rows.order_by("pk").values_list("pk", flat=True)[:cap])
    checkpoint.metadata = {"last_pk": str(ids[-1])} if ids else {}
    checkpoint.save(update_fields=["metadata", "updated_at"])
    return sum(queue_workflow_message(identifier) for identifier in ids)


def _post_threads(post):

    jobs = post.studio_briefs.filter(
        workspace_id=post.workspace_id,
        job__workspace_id=post.workspace_id,
        job__conversation__workspace_id=post.workspace_id,
    ).values("job__conversation_id")
    return (
        Conversation.objects.filter(workspace_id=post.workspace_id)
        .filter(Q(pk__in=jobs) | Q(post=post) | Q(brief__post=post))
        .distinct()
    )


def _post_scope_permitted(prompt):
    from apps.composer.models import Post

    from .channel_outbox import _event_proven, public_post

    scope = prompt.snapshot.get("post")
    if not isinstance(scope, dict) or set(scope) != {"origin", "event", "post_epoch"}:
        return False
    origin = scope["origin"]
    if not isinstance(origin, dict) or origin.get("workspace_id") != str(prompt.workspace_id):
        return False
    try:
        post = Post.objects.filter(pk=origin.get("post_id"), workspace_id=prompt.workspace_id).first()
    except (ValueError, TypeError):
        return False
    return bool(
        post is not None
        and post.updated_at.isoformat() == scope["post_epoch"]
        and public_post(post)
        and _post_threads(post).filter(pk=prompt.conversation_id).exists()
        and _event_proven(post, scope["event"], origin=origin)
    )


def queue_post_event(post, event, source_key, *, brief=None):
    """Post lifecycle notices follow canonical lineage only, to opted-in original authors."""
    from .channel_outbox import CHANNEL_EVENT_TEXT, _event_proven, _ready_brief, public_post

    if event not in CHANNEL_EVENT_TEXT or not isinstance(source_key, str) or not public_post(post):
        return 0
    origin = {"post_id": str(post.pk), "workspace_id": str(post.workspace_id)}
    if event == "draft":
        ready = _ready_brief(post, brief=brief)
        if ready is None:
            return 0
        origin.update(draft_brief_id=str(ready.pk), draft_revision=ready.revision)
    if not _event_proven(post, event, origin=origin):
        return 0
    post_scope = {"origin": origin, "event": event, "post_epoch": post.updated_at.isoformat()}
    count = 0
    for conversation in _post_threads(post).select_related("created_by")[:25]:
        try:
            count += _queue(
                conversation,
                source_key=f"post:{post.pk}:{conversation.pk}:{_hash(source_key)}",
                text=CHANNEL_EVENT_TEXT[event],
                post_scope=post_scope,
            )
        except PermissionDenied:
            continue
    return count


def delivery_permitted(row, chat):
    """A revoked opt-in/source/role/private identity prevents queued questions leaving."""
    if not row.source_key.startswith(PREFIX):
        return True
    match = _KEY.fullmatch(row.source_key)
    if match is None:
        return False
    try:
        prompt = (
            TelegramWorkflowPrompt.objects.select_related("conversation", "author")
            .filter(
                pk=UUID(match[1]),
                delivery=row,
                chat=chat,
                consumed_at__isnull=True,
            )
            .first()
        )
        if prompt is None:
            return False
        _prompt_context(prompt)
        if not _delivery_text_valid(row, prompt):
            return False
    except (PermissionDenied, ValueError, TypeError):
        return False
    return True


def _delivery_text_valid(row, prompt):
    return bool(
        row.kind == "message"
        and isinstance(row.payload, dict)
        and set(row.payload) == {"method", "text", "_scope"}
        and row.payload.get("method") == "sendMessage"
        and isinstance(row.payload.get("text"), str)
        and prompt.snapshot.get("text_digest") == _hash(row.payload["text"])
        and row.payload.get("_scope") == prompt.snapshot.get("binding", {}).get("private_scope")
    )


def _sent(prompt):
    delivery = TelegramDelivery.objects.filter(pk=prompt.delivery_id, chat_id=prompt.chat_id, status="sent").first()
    if (
        delivery is None
        or type(delivery.native_message_id) is not int
        or delivery.native_message_id <= 0
        or delivery.source_key != f"{PREFIX}{prompt.pk}:part:0"
        or delivery.kind != "message"
        or not _delivery_text_valid(delivery, prompt)
    ):
        raise PermissionDenied("The workflow question has no verified Telegram delivery receipt.")
    return delivery


def handle_workflow_reply(connection, payload):
    """Only authenticated Reply metadata to a SENT prompt routes to its original web thread."""
    message = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(message, dict) or not isinstance(message.get("reply_to_message"), dict):
        return None
    native = message.get("chat", {})
    reply_id = message["reply_to_message"].get("message_id")
    if not isinstance(native, dict) or native.get("type") != "private" or type(reply_id) is not int or reply_id <= 0:
        return None
    prompt = (
        TelegramWorkflowPrompt.objects.select_related("conversation", "author")
        .filter(
            chat__connection=connection,
            chat__chat_id=native.get("id"),
            delivery__native_message_id=reply_id,
        )
        .order_by("-created_at", "-pk")
        .first()
    )
    if prompt is None:
        return None
    denied = {
        "text": "This workflow reply request is unavailable. Open your saved idea in SM Bean or wait for a fresh question."
    }
    try:
        update = TelegramUpdate.objects.filter(
            pk=CURRENT_UPDATE_ID.get(), connection=connection, status="working"
        ).first()
        if (
            update is None
            or update.payload.get("message") != message
            or payload.get("_binding") != connection_epoch(connection)
            or update.payload.get("_binding") != connection_epoch(connection)
            or any(
                message.get(name)
                for name in (
                    "sender_chat",
                    "forward_origin",
                    "forward_from",
                    "forward_from_chat",
                    "forward_sender_name",
                    "forward_date",
                    "is_automatic_forward",
                )
            )
        ):
            raise PermissionDenied
        sender = message.get("from", {})
        body = message.get("text")
        if (
            not isinstance(sender, dict)
            or type(sender.get("id")) is not int
            or sender.get("is_bot") is not False
            or sender["id"] != native.get("id")
            or not isinstance(body, str)
            or not body.strip()
            or body.lstrip().startswith("/")
            or any(
                message.get(key)
                for key in ("photo", "document", "video", "voice", "audio", "animation", "video_note", "sticker")
            )
        ):
            raise PermissionDenied
        with transaction.atomic():
            context = _prompt_context(prompt, locked=True)
            prompt = TelegramWorkflowPrompt.objects.select_for_update().get(pk=prompt.pk)
            if (
                prompt.consumed_at is not None
                or context[1].telegram_user_id != sender["id"]
                or not prompt.source_key.startswith("question:")
            ):
                raise PermissionDenied
            _sent(prompt)
            posted = studio_chat.post_message(prompt.conversation, prompt.author, body)
            prompt.consumed_at = timezone.now()
            prompt.response_message = posted.message
            prompt.snapshot["reply"] = {
                "body_digest": _hash(posted.message.body),
                "job_id": str(posted.job.pk) if posted.job else None,
                "job_revision": posted.job.revision if posted.job else None,
            }
            prompt.save(update_fields=["consumed_at", "response_message", "snapshot"])
            if posted.job is not None:
                posted.message.job = posted.job
                posted.message.save(update_fields=["job"])
                posted.job.input = {**posted.job.input, "workflow_telegram_context": {"prompt_id": str(prompt.pk)}}
                posted.job.save(update_fields=["input"])
        return {
            "text": posted.note
            or "Your reply was saved in the original SM Bean idea thread. Final confirmation and approval remain separate."
        }
    except (PermissionDenied, studio_chat.ChatError, ValueError, TypeError):
        return denied


def workflow_member(job, conversation, requester, *, locked=False):
    """Repeat the exact receipt/source/author proof before provider spend and mutation."""
    context = (job.input or {}).get("workflow_telegram_context")
    if not isinstance(context, dict) or set(context) != {"prompt_id"}:
        raise PermissionDenied("This workflow Telegram origin is invalid.")
    try:
        prompt = (
            TelegramWorkflowPrompt.objects.select_related("conversation", "author")
            .filter(pk=UUID(context["prompt_id"]))
            .first()
        )
    except (ValueError, TypeError, AttributeError):
        raise PermissionDenied("This workflow Telegram origin is invalid.") from None
    response = Message.objects.filter(pk=prompt.response_message_id).first() if prompt is not None else None
    if (
        prompt is None
        or prompt.author_id != getattr(requester, "pk", None)
        or prompt.conversation_id != conversation.pk
        or prompt.workspace_id != job.workspace_id
        or prompt.consumed_at is None
        or prompt.response_message_id is None
        or not isinstance(prompt.snapshot, dict)
        or str(prompt.response_message_id) != (job.input or {}).get("message_id")
        or response is None
        or response.conversation_id != conversation.pk
        or response.author_id != requester.pk
        or response.author_kind != Message.AuthorKind.STAFF
        or response.is_internal
        or response.job_id != job.pk
        or not isinstance(prompt.snapshot.get("reply"), dict)
        or prompt.snapshot["reply"].get("body_digest") != _hash(response.body)
        or prompt.snapshot["reply"].get("job_id") != str(job.pk)
        or not AgencyJob.objects.filter(
            pk=job.pk,
            workspace_id=prompt.workspace_id,
            conversation_id=prompt.conversation_id,
            requested_by_id=prompt.author_id,
            revision=job.revision,
        ).exists()
    ):
        raise PermissionDenied("This workflow Telegram reply no longer has its original author.")
    member = _prompt_context(prompt, locked=locked)[3]
    _sent(prompt)
    return member
