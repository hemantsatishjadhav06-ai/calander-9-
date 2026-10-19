"""Bridge authenticated Telegram speakers into their exact existing Studio thread.

Telegram is a transport, not a second creative or approval engine. Ordinary
messages and an ordinary “yes” never approve, schedule or confirm a draft;
only a one-use review button does. Replies here are short: the caveats live
in /help and the first pairing message.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.urls import reverse

from apps.composer.models import Post
from apps.studio import chat as studio_chat
from apps.studio import engine
from apps.studio.models import AgencyJob, Conversation, Message, StudioBrief

from .actions import TelegramActionError
from .models import TelegramChat, TelegramConnection, TelegramUserLink
from .outbox import link_button, link_keyboard
from .permissions import fresh_member, internal_member
from .uploads import ReferenceUploadError

HELP = (
    "Tell me what to post. I bring you a brief to confirm, then the draft to approve.\n"
    "/brief <idea> — start a post\n"
    "/brainstorm <idea> — think it through first\n"
    "/reference — send a photo, PDF or short text to use\n"
    "/status — what is happening in this chat\n"
    "/approvals — posts waiting for you\n"
    "/post <ID> [time with offset] — one post's review card\n"
    "/week — this week's plan · /week prepare — plan next week · /week evidence — the sources behind it\n"
    "/pause · /resume · /retry — your latest task\n"
    "/stop — stop your pending requests here\n"
    "/mute · /unmute — messages from the team (your morning briefing still arrives)\n"
    "Only a review button approves or confirms; a plain “yes” never does. Client sign-off and the agency's "
    "approval are separate. In a private chat, photos and PDFs need the caption /reference shared because they "
    "enter the shared brand library."
)
PAIRED_WELCOME = (
    "You're paired. Tell me what to post, or send /help.\n"
    "Nothing publishes without your approval, and a plain “yes” never approves anything."
)
_CLIENT_COMMANDS = {"/brainstorm", "/brief", "/reference"}


def _response(text="", **extra) -> dict[str, Any]:
    return {"text": str(text)[:3900], **extra}


def _card(value):
    if not isinstance(value, dict):
        return _response("Open the current review in SM Bean.")
    result = _response(value.get("text", "Open the current review in SM Bean."))
    keyboard = value.get("reply_markup")
    if keyboard is None and value.get("inline_keyboard"):
        keyboard = {"inline_keyboard": value["inline_keyboard"]}
    if isinstance(keyboard, dict):
        result["reply_markup"] = keyboard
    if value.get("photo_asset_id"):
        result["photo_asset_id"] = str(value["photo_asset_id"])
    return result


def _command(text, username):
    if not text.startswith("/"):
        return "", text
    first, _, rest = text.partition(" ")
    name, _, target = first.partition("@")
    if target and target.casefold() != (username or "").casefold():
        return "foreign_bot", ""
    return name.casefold(), rest.strip()


def _bound(connection, message):
    sender, native = message.get("from"), message.get("chat")
    if (
        not isinstance(sender, dict)
        or type(sender.get("id")) is not int
        or sender["id"] <= 0
        or sender.get("is_bot")
        or message.get("sender_chat") is not None
        or not isinstance(native, dict)
        or type(native.get("id")) is not int
    ):
        raise PermissionDenied("A paired personal Telegram identity is required.")
    current = (
        TelegramConnection.objects.select_related("workspace__organization")
        .filter(pk=connection.pk, workspace_id=connection.workspace_id, is_active=True)
        .first()
    )
    if current is None or current.bot_id != connection.bot_id:
        raise PermissionDenied("This Telegram connection is unavailable.")
    link = (
        TelegramUserLink.objects.select_related("connection__workspace", "user")
        .filter(connection=current, telegram_user_id=sender["id"], is_active=True)
        .first()
    )
    if link is None:
        raise PermissionDenied("Pair your Telegram account from SM Bean first.")
    member = fresh_member(link)
    if member is None:
        raise PermissionDenied("Current workspace access is required.")
    if native.get("type") == "private":
        if native["id"] != sender["id"]:
            raise PermissionDenied("The private chat must belong to its paired speaker.")
        from .provisioning import private_chat

        bound = private_chat(current, link)
    else:
        bound = (
            TelegramChat.objects.select_related("conversation__workspace", "connection")
            .filter(connection=current, chat_id=native["id"], is_active=True)
            .first()
        )
    if bound is None or bound.chat_type != native.get("type"):
        raise PermissionDenied("Ask the manager to pair this chat from SM Bean.")
    context = {"chat_id": str(bound.pk), "user_link_id": str(link.pk)}
    member = studio_chat.telegram_member(bound.conversation, link.user, context)
    return current, bound, link, member, context


def _briefs(bound):
    conversation = bound.conversation
    query = Q(job__conversation=conversation, job__workspace_id=bound.connection.workspace_id)
    if conversation.brief_id:
        query |= Q(pk=conversation.brief_id)
    return StudioBrief.objects.filter(query, workspace_id=bound.connection.workspace_id).select_related("post", "job")


def _posts(bound):
    conversation = bound.conversation
    ids = list(_briefs(bound).exclude(post_id=None).values_list("post_id", flat=True))
    if conversation.post_id:
        ids.append(conversation.post_id)
    return Post.objects.filter(workspace_id=bound.connection.workspace_id, pk__in=ids).prefetch_related(
        "platform_posts__social_account"
    )


def _status(bound, member):
    briefs = list(_briefs(bound).order_by("-created_at")[:8])
    lines = ["Work in this conversation:"]
    for brief in briefs:
        label = (
            brief.get_status_display()
            if internal_member(member)
            else (
                "Draft preparation is in progress"
                if brief.is_active
                else "Awaiting the team's review"
                if brief.status in {StudioBrief.Status.READY, StudioBrief.Status.FAILED}
                else brief.get_status_display()
            )
        )
        lines.append(f"{brief.idea[:120]} — revision {brief.revision}: {label}")
        if brief.post_id:
            lines.append(f"Post ID: {brief.post_id}")
    for post in _posts(bound).order_by("-created_at")[:8]:
        for row in post.platform_posts.all():
            if row.social_account.workspace_id != bound.connection.workspace_id:
                continue
            from apps.publisher.delivery import state

            marker = state(row)
            label = (
                "Delivery outcome unknown — a person must check the account"
                if marker.get("kind") == "unknown"
                else (
                    "Posting time expired — a person must return it for review"
                    if marker.get("kind") == "expired"
                    else row.get_status_display()
                )
            )
            account = (
                row.social_account.account_name or row.social_account.account_handle or row.social_account.platform
            )
            when = row.scheduled_at or post.scheduled_at
            lines.append(f"{account}: {label}" + (f" · {when.isoformat()}" if when else ""))
            if row.status == "published" and row.platform_post_id:
                lines.append(f"Native receipt: {row.platform_post_id}")
    if len(lines) == 1:
        lines.append("Nothing is linked to this chat yet. Send /brief <idea> to start.")
    return _response("\n".join(lines))


def _current_intake(bound, link):
    from apps.studio import creative_brief

    job = creative_brief.latest_intake(bound.conversation, link.user)
    if job is None or not (job.result or {}).get("awaiting_confirmation"):
        return None
    message_id = (job.result or {}).get("message_id")
    return Message.objects.filter(
        pk=message_id, job=job, conversation=bound.conversation, author_kind=Message.AuthorKind.AGENT, is_internal=False
    ).first()


def _client_reference(bound):
    """A lead can review a photo explicitly supplied in this exact client thread."""
    if bound.conversation.audience != Conversation.Audience.CLIENT or bound.audience == "private":
        return ""
    reference_id = ""
    jobs = (
        AgencyJob.objects.filter(
            conversation=bound.conversation, workspace_id=bound.connection.workspace_id, kind=AgencyJob.Kind.CHAT
        )
        .exclude(input__reference_id__isnull=True)
        .order_by("-created_at")[:20]
    )
    for job in jobs:
        try:
            message_id = uuid.UUID(str((job.input or {}).get("message_id", "")))
        except (ValueError, TypeError, AttributeError):
            continue
        if Message.objects.filter(
            pk=message_id,
            conversation=bound.conversation,
            author_id=job.requested_by_id,
            author_kind=Message.AuthorKind.CLIENT,
            is_internal=False,
        ).exists():
            reference_id = (job.input or {}).get("reference_id") or ""
            break
    if reference_id == "none":
        return "none"
    from apps.media_library.models import MediaAsset

    try:
        identifier = uuid.UUID(str(reference_id))
    except (ValueError, TypeError, AttributeError):
        return ""
    return (
        str(identifier)
        if MediaAsset.objects.filter(
            pk=identifier,
            workspace_id=bound.connection.workspace_id,
            organization_id=bound.connection.workspace.organization_id,
            media_type="image",
        ).exists()
        else ""
    )


def _review(bound, link, member, arguments="", *, approvals=False):
    from .actions import issue_post_review

    posts = _posts(bound)
    if not internal_member(member):
        posts = posts.filter(platform_posts__status="pending_client").distinct()
    if approvals:
        status = "pending_review" if internal_member(member) else "pending_client"
        posts = posts.filter(platform_posts__status=status).distinct()
    parts = arguments.split(maxsplit=1)
    when = None
    if parts:
        try:
            identifier = uuid.UUID(parts[0])
        except (ValueError, TypeError):
            return _response("Choose a post ID shown by /status; it must belong to this conversation.")
        posts = posts.filter(pk=identifier)
        if len(parts) > 1:
            try:
                when = datetime.fromisoformat(parts[1].replace("Z", "+00:00"))
            except ValueError:
                return _response("Use an ISO date and time with an explicit timezone offset.")
            if when.tzinfo is None or when.utcoffset() is None:
                return _response("Include the timezone offset in the proposed posting time.")
    choices = list(posts.order_by("-created_at")[:6])
    if not choices:
        return _response("No post here is available for your requested review. Check /status or ask the agency lead.")
    if len(choices) > 1:
        lines = ["Choose the exact post with /post <ID>:"]
        lines.extend(f"{post.title[:100] or post.caption[:100]} · {post.pk}" for post in choices)
        return _response("\n".join(lines))
    return _card(issue_post_review(bound, link, choices[0], publish_at=when))


def _week(bound, link, member, arguments):
    from . import weekly

    parts = arguments.split(maxsplit=1)
    verb = parts[0].casefold() if parts else ""
    prepare, evidence = verb == "prepare", verb == "evidence"
    week_start = parts[1] if (prepare or evidence) and len(parts) > 1 else (arguments or None)
    if prepare or evidence:
        if not internal_member(member) or bound.conversation.audience == Conversation.Audience.CLIENT:
            return _response(
                "Weekly preparation belongs to your paired private or internal team chat. This client group can read its shared plan with /week."
            )
        from .actions import issue_week_confirmation

        preview = weekly.queue_week_plan(link, bound, week_start=week_start, confirmed=False)
        if evidence:
            try:
                return _response(weekly.analysis_text(preview))
            except ValueError as error:
                return _response(str(error))
        if preview.get("needs_confirmation"):
            return _card(issue_week_confirmation(bound, link, preview))
        message = preview.get("message") or preview.get("text") or "Open the current weekly analysis in SM Bean."
        analysis = preview.get("analysis") or {}
        blockers = analysis.get("blockers") if isinstance(analysis, dict) else None
        if isinstance(blockers, list) and blockers:
            message += "\nNeeds attention:\n" + "\n".join(str(item) for item in blockers[:10])
        return _response(message)
    audience = "client" if bound.conversation.audience == Conversation.Audience.CLIENT else "team"
    return _response(
        weekly.summary_text(bound.connection.workspace, week_start=week_start, user=link.user, audience=audience)
    )


def _stop(bound, link, context):
    with transaction.atomic():
        studio_chat.telegram_member(bound.conversation, link.user, context, locked=True)
        jobs = list(
            AgencyJob.objects.select_for_update().filter(
                workspace_id=bound.connection.workspace_id,
                conversation=bound.conversation,
                requested_by=link.user,
                kind=AgencyJob.Kind.CHAT,
                status__in=AgencyJob.ACTIVE_STATUSES,
            )
        )
        for job in jobs:
            engine.cancel(job)
    return _response(
        f"Stopped {len(jobs)} of your pending request(s) here. Scheduled and published posts are unchanged."
    )


def _task_button(workspace_id, job):
    path = reverse("studio:job", kwargs={"workspace_id": workspace_id, "job_id": job.pk})
    return link_keyboard(link_button("Open the task", path))


def _own_jobs(bound, link):
    """The person's own tasks the web can show, newest first; this chat's first."""
    rows = studio_chat.web_jobs(
        AgencyJob.objects.filter(workspace_id=bound.connection.workspace_id, requested_by=link.user)
    )
    here = rows.filter(conversation=bound.conversation).order_by("-updated_at")
    elsewhere = rows.exclude(conversation=bound.conversation).order_by("-updated_at")
    return list(here[:20]) + list(elsewhere[:20])


def _control(bound, link, member, action):
    """/pause acts through the same reviewed control as the web; /resume and /retry point at that review."""
    from apps.studio import opendots

    if not internal_member(member) or not studio_chat.is_staff_membership(member):
        return _response("Only a team member can control the team's tasks.")
    workspace = bound.connection.workspace
    private_active = AgencyJob.objects.filter(
        workspace_id=workspace.pk,
        conversation=bound.conversation,
        requested_by=link.user,
        status__in=AgencyJob.ACTIVE_STATUSES,
    ).exists()
    label = lambda job: (job.title or job.get_kind_display())[:80]  # noqa: E731
    if action == "pause":
        job = next((row for row in _own_jobs(bound, link) if row.status in AgencyJob.ACTIVE_STATUSES), None)
        if job is None:
            hint = " Your request in this chat can be stopped with /stop." if private_active else ""
            return _response("Nothing of yours is running right now." + hint)
        try:
            opendots.control_job(workspace, link.user, job.pk, "pause", expected_revision=job.revision)
        except (opendots.CoworkerControlError, PermissionDenied) as error:
            return _response(str(error))
        return _response(f"Paused “{label(job)}”. Send /resume when you're ready.")
    capability = "can_resume" if action == "resume" else "can_retry"
    for job in _own_jobs(bound, link):
        if job.status in AgencyJob.ACTIVE_STATUSES:
            continue
        if opendots.task_record(job)[capability]:
            verb = "resume" if action == "resume" else "retry"
            keyboard = _task_button(workspace.pk, job)
            text = f"“{label(job)}” needs a quick look at its saved work first. Open it to {verb}."
            return _response(text, reply_markup=keyboard) if keyboard else _response(text)
    return _response(
        "Nothing of yours is waiting to be resumed." if action == "resume" else "Nothing of yours needs a retry."
    )


def _mute(link, *, muted):
    # QuerySet.update leaves updated_at alone: the pairing epoch (and every
    # outstanding button bound to it) must survive a mute.
    TelegramUserLink.objects.filter(pk=link.pk).update(notify_needs_you=not muted)
    if muted:
        return _response("Muted. Your morning briefing and replies still arrive here. Send /unmute to switch back.")
    return _response("Unmuted. The team will tell you here when something needs you.")


def handle_message(connection, update_payload) -> dict[str, Any]:
    """Route one verified update; processing/outbox owns delivery and replay guards."""
    if not isinstance(update_payload, dict) or not isinstance(update_payload.get("message"), dict):
        return _response("", silent=True)
    message = update_payload["message"]
    text = message.get("text", message.get("caption", ""))
    if not isinstance(text, str):
        return _response("Send text or a supported reference file.")
    command, arguments = _command(text.strip(), connection.bot_username)
    if command == "foreign_bot":
        return _response("", silent=True)
    if command in {"/start", "/pair"}:
        from .provisioning import consume_pairing_message

        try:
            paired = consume_pairing_message(connection, message)
            return _response(PAIRED_WELCOME, paired_id=str(paired.pk))
        except Exception:
            return _response("Pairing failed. Create a new one-use link in SM Bean and open it yourself.")
    try:
        current, bound, link, member, context = _bound(connection, message)
        if command == "/help":
            return _response(HELP)
        if command == "/status":
            return _status(bound, member)
        if command == "/week":
            return _week(bound, link, member, arguments)
        if command == "/approvals":
            return _review(bound, link, member, arguments, approvals=True)
        if command == "/post":
            return _review(bound, link, member, arguments)
        if command == "/stop":
            if arguments:
                return _response("Send /stop on its own to stop your pending requests here.")
            return _stop(bound, link, context)
        if command in {"/pause", "/resume", "/retry"}:
            return _control(bound, link, member, command[1:])
        if command == "/mute":
            return _mute(link, muted=True)
        if command == "/unmute":
            return _mute(link, muted=False)
        if command and command not in _CLIENT_COMMANDS:
            return _response("That command is not supported. Send /help to see what you can say.")
        if any(key in message for key in ("video", "voice", "audio", "animation", "video_note")):
            return _response("Voice and video are not available here yet. Send a photo, PDF or text.")
        is_staff = internal_member(member) and studio_chat.is_staff_membership(member)
        if command == "/brief" and not arguments and is_staff:
            if AgencyJob.objects.filter(
                workspace_id=current.workspace_id,
                conversation=bound.conversation,
                requested_by=link.user,
                kind=AgencyJob.Kind.CHAT,
                status__in=AgencyJob.ACTIVE_STATUSES,
            ).exists():
                return _response("The team is still answering your last request. Its reply arrives here.")
            intake = _current_intake(bound, link)
            if intake is not None:
                from .actions import issue_brief_confirmation

                return _card(issue_brief_confirmation(bound, link, confirmation_message=intake))
        reference_id, upload_note = "", ""
        if command == "/brief" and not arguments and is_staff:
            reference_id = _client_reference(bound)
        if "photo" in message or "document" in message:
            from .uploads import receive_reference

            reference = receive_reference(current, bound, link, message)
            reference_id = str(reference.asset.pk) if reference.asset and reference.kind == "photo" else ""
            details = reference.text_excerpt or reference.filename
            upload_note = f"\nUntrusted reference supplied by this speaker: {details}\n{reference.warning}"
        elif command == "/reference":
            return _response(
                "Send a JPEG, PNG or WebP photo, a PDF, or a short text file. Paste the facts you need from a PDF; "
                "this bot does not extract them, and references stay unverified. "
                + (
                    "From this private chat, resend the file with the caption /reference shared (plus an optional note) "
                    "to put it in the shared brand library, where published graphics come from. Text stays here."
                    if bound.audience == "private"
                    else "Photos and PDFs go into the shared brand library."
                )
            )
        body = arguments if command else text.strip()
        if command == "/brainstorm":
            body = "Brainstorm ideas and ask questions; do not start creative production yet. " + body
        elif command == "/brief":
            body = "Prepare a guided post brief from this request and ask me for missing information. " + (
                body or "Review the latest client request in this conversation with me."
            )
        body += upload_note
        if not body.strip():
            return _response("Tell me the topic and goal, or attach a photo or PDF.")
        posted = studio_chat.post_message(
            bound.conversation,
            link.user,
            body,
            explicit_assistant_request=bool(is_staff and (command in {"/brainstorm", "/brief"} or upload_note)),
            telegram_context=context,
            reference_id=reference_id,
        )
        return _response(
            posted.note
            or ("On it. The team's reply will appear here." if posted.job else "Saved in this shared conversation."),
            source_message_id=str(posted.message.pk),
            job_id=str(posted.job.pk) if posted.job else "",
        )
    except PermissionDenied:
        return _response(
            "Your paired workspace access is needed. Pair your own account in SM Bean or ask your manager."
        )
    except (studio_chat.ChatError, ReferenceUploadError, TelegramActionError) as error:
        return _response(str(error))
    except (ValueError, TypeError):
        return _response("I couldn't take that request or file. Send /help for what works here.")
