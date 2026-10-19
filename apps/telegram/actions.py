"""One-use, exact-review human actions; no Telegram or publishing network calls."""

from __future__ import annotations

import hashlib
import secrets
import zoneinfo
from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.approvals import gate
from apps.approvals import services as approval_services
from apps.approvals.actor import TELEGRAM, acting_as, acting_as_telegram
from apps.composer.models import PlatformPost, Post, PostMedia
from apps.composer.services import transition_platform_post
from apps.media_library.models import MediaAsset
from apps.publisher import delivery
from apps.studio import trust
from apps.studio.guards import forbid_in_agent_work
from apps.studio.models import Message

from .models import TelegramAction, TelegramChat, TelegramConnection, TelegramUserLink
from .permissions import fresh_member, internal_member

PREFIX = "tg:a:"
ACTION_TTL = timedelta(minutes=10)
APPROVAL_KINDS = {"approve", "approve_schedule", "schedule"}
#: The one caveat every card that acts carries.
FOOTER = "Nothing publishes without your approval. Buttons work once and expire in 10 minutes."


class TelegramActionError(ValueError):
    """Safe, user-visible action refusal."""


def _digest(nonce):
    return hashlib.sha256(nonce.encode()).hexdigest()


def _chat_access(chat, link, member):
    if (
        not chat.is_active
        or chat.connection_id != link.connection_id
        or chat.connection.workspace_id != member.workspace_id
        or chat.conversation.workspace_id != member.workspace_id
        or (chat.audience == "private" and chat.private_user_id != member.user_id)
        or (chat.audience == "team" and not internal_member(member))
        or (chat.audience == "client" and chat.conversation.audience != "client")
        or (chat.audience == "team" and chat.conversation.audience != "internal")
    ):
        raise TelegramActionError("This paired chat is unavailable for your current workspace access.")


def _material(post):
    rows = list(post.platform_posts.select_related("post__workspace", "social_account").order_by("pk"))
    attachments = list(post.media_attachments.select_related("media_asset").order_by("position", "id"))
    if not rows or any(row.social_account.workspace_id != post.workspace_id for row in rows):
        raise TelegramActionError("Choose current destinations in this workspace before requesting review.")
    if any(
        item.media_asset.workspace_id != post.workspace_id
        or item.media_asset.organization_id != post.workspace.organization_id
        for item in attachments
    ):
        raise TelegramActionError("A graphic is unavailable in this workspace. Request a new review.")
    briefs = post.studio_briefs.select_related("workspace__organization", "source_picture").order_by("pk")
    return {
        "channels": [{"id": str(row.pk), "fingerprint": gate.fingerprint(row)} for row in rows],
        "revision": gate._current_revision(post),
        "media": [
            {
                "id": str(item.media_asset_id),
                "stamp": trust.asset_stamp(item.media_asset),
                "provenance": trust.photo_status(item.media_asset),
            }
            for item in attachments
        ],
        "sources": [
            {
                "id": str(brief.pk),
                "revision": brief.revision,
                "saved": brief.trust_snapshot,
                "current": trust.capture(brief),
            }
            for brief in briefs
        ],
    }


def _post_snapshot(post):
    return {
        "material": _material(post),
        "proposed_publish_at": post.proposed_publish_at.isoformat() if post.proposed_publish_at else None,
        "channels": [
            {
                "id": str(row.pk),
                "status": row.status,
                "time": gate.effective_publish_at(row).isoformat() if gate.effective_publish_at(row) else None,
                "approved": row.approved_fingerprint,
                "approved_time": row.approved_publish_at.isoformat() if row.approved_publish_at else None,
            }
            for row in post.platform_posts.select_related("post").order_by("pk")
        ],
    }


def _post_available(post):
    if delivery.has_unresolved_holds(post):
        raise TelegramActionError("Resolve the unknown or expired delivery in SM Bean before reviewing this post.")
    rows = list(post.platform_posts.select_related("post__workspace", "social_account"))
    if any(row.social_account.needs_reconnect for row in rows):
        raise TelegramActionError("Reconnect the intended brand account in SM Bean before approving this post.")
    for row in rows:
        inputs = {key: value for key, value in (row.platform_extra or {}).items() if key not in gate._RESULT_EXTRA_KEYS}
        if (
            set(inputs) - {"post_type"}
            or inputs.get("post_type", "text") not in {"text", "image"}
            or row.platform_specific_media
        ):
            raise TelegramActionError(
                "Review this version's complete format, audience and publishing settings in SM Bean."
            )
    attachments = list(post.media_attachments.select_related("media_asset"))
    if len(attachments) > 1 or any(item.platform_overrides or not item.media_asset.is_image for item in attachments):
        raise TelegramActionError("Review all graphics, video or media overrides together in SM Bean before approving.")
    if any(delivery.state(row).get("kind") in delivery.UNRESOLVED for row in rows):
        raise TelegramActionError("Resolve the previous delivery record in SM Bean first.")
    if any(row.status in {"publishing", "published", "failed", "on_hold", "scheduled"} for row in rows):
        raise TelegramActionError("This post is already scheduled, sent or held. Manage it in SM Bean.")
    reason = trust.post_blocker(post)
    if reason:
        raise TelegramActionError("Source evidence changed or expired. Request a fresh source review in SM Bean.")


def _issue(chat, link, kind, snapshot, *, label, post=None, brief=None):
    nonce = secrets.token_urlsafe(24)
    connection = TelegramConnection.objects.get(pk=chat.connection_id)
    link = TelegramUserLink.objects.get(pk=link.pk)
    TelegramAction.objects.create(
        chat=chat,
        user_link=link,
        post=post,
        brief=brief,
        kind=kind,
        token_digest=_digest(nonce),
        expires_at=timezone.now() + ACTION_TTL,
        snapshot={
            **snapshot,
            "binding": {
                "connection_id": str(chat.connection_id),
                "bot_id": chat.connection.bot_id,
                "chat_id": chat.chat_id,
                "workspace_id": str(chat.connection.workspace_id),
                "user_id": str(link.user_id),
                "telegram_user_id": link.telegram_user_id,
                "connection_epoch": connection.updated_at.isoformat(),
                "link_epoch": link.updated_at.isoformat(),
                "chat_epoch": chat.updated_at.isoformat(),
                "conversation_id": str(chat.conversation_id),
                "audience": chat.audience,
                "private_user_id": str(chat.private_user_id) if chat.private_user_id else None,
            },
        },
    )
    return {"text": label, "callback_data": PREFIX + nonce}


def _future(value):
    if isinstance(value, str):
        value = parse_datetime(value)
    if value is None or timezone.is_naive(value) or value <= timezone.now():
        raise TelegramActionError("Choose a future time with a timezone, then request a fresh review.")
    return value


def issue_post_review(chat, user_link, post, *, publish_at=None):
    """Show exact public outputs. Buttons never substitute for unseen/truncated content."""
    forbid_in_agent_work("issue Telegram approval buttons")
    member = fresh_member(user_link)
    chat = TelegramChat.objects.select_related("connection", "conversation").get(pk=chat.pk)
    _chat_access(chat, user_link, member)
    if not chat.connection.approvals_enabled or not gate.enforced(member.workspace):
        raise TelegramActionError("Enable Telegram approvals and exact human approval in SM Bean settings first.")
    post = Post.objects.select_related("workspace__organization").get(pk=post.pk, workspace=member.workspace)
    _post_available(post)
    rows = list(post.platform_posts.select_related("social_account").order_by("pk"))
    client = not internal_member(member)
    statuses = {row.status for row in rows}
    if not member.effective_permissions.get("approve_posts"):
        raise TelegramActionError("Your current role cannot review approvals.")
    if client and (chat.audience != "client" or statuses != {"pending_client"}):
        raise TelegramActionError("Client sign-off is available only after the internal review stage.")
    if not client and statuses not in ({"pending_review"}, {"approved"}):
        raise TelegramActionError("Finish the current review stage in SM Bean before issuing this card.")
    when = publish_at or post.proposed_publish_at
    if when is None and statuses == {"approved"}:
        times = {row.approved_publish_at for row in rows}
        when = times.pop() if len(times) == 1 else None
    if client:
        approved_times = {row.approved_publish_at for row in rows}
        if len(approved_times) != 1:
            raise TelegramActionError(
                "The destinations have different approved times. Ask the agency for a fresh review."
            )
        approved_time = approved_times.pop()
        if publish_at is not None and publish_at != approved_time:
            raise TelegramActionError("Clients cannot change the internally approved publishing time.")
        when = approved_time
    if when is not None:
        when = _future(when)
    if statuses == {"approved"} and when is None:
        raise TelegramActionError("Choose a future schedule time in SM Bean before requesting a scheduling card.")
    material = _post_snapshot(post)
    snapshot = {"post": material, "publish_at": when.isoformat() if when else None}
    try:
        zone = zoneinfo.ZoneInfo(member.workspace.effective_timezone or "UTC")
    except zoneinfo.ZoneInfoNotFoundError:
        zone = zoneinfo.ZoneInfo("UTC")
    lines = [
        f"Exact post review — {member.workspace.name}",
        f"Revision: {material['material']['revision'] or 'unversioned'}",
    ]
    lines.append(
        f"Time: {when.astimezone(zone).isoformat()} ({zone.key})"
        if when
        else "Time: unscheduled; approval alone will not publish."
    )
    for row in rows:
        lines.extend(
            [
                f"\n{row.social_account.platform}: {row.social_account.account_name} [{row.social_account.account_platform_id}]",
                f"Title: {row.effective_title or '(none)'}",
                f"Caption:\n{row.effective_caption or '(empty)'}",
                f"First comment: {row.effective_first_comment or '(none)'}",
                f"Post type: {(row.platform_extra or {}).get('post_type', 'image' if post.media_attachments.exists() else 'text')}",
            ]
        )
    attachments = list(post.media_attachments.select_related("media_asset").order_by("position", "id"))
    lines.extend(
        f"Graphic {i + 1}: {item.media_asset.original_filename}; {trust.photo_status(item.media_asset)['label']}; alt text: {item.alt_text or '(none)'}"
        for i, item in enumerate(attachments)
    )
    lines.append(FOOTER)
    text = "\n".join(lines)
    if (
        len(text) > 3900
        or len(attachments) > 1
        or any(row.platform_specific_media for row in rows)
        or any(item.platform_overrides or not item.media_asset.is_image for item in attachments)
    ):
        raise TelegramActionError(
            "This review needs multiple or overridden graphics or a longer preview. Review its full content in SM Bean."
        )
    buttons = []
    if client:
        buttons.append(_issue(chat, user_link, "client_signoff", snapshot, label="Client sign-off only", post=post))
    elif statuses == {"approved"}:
        buttons.append(_issue(chat, user_link, "schedule", snapshot, label="Approve this time & schedule", post=post))
    else:
        buttons.append(_issue(chat, user_link, "approve", snapshot, label="Approve only", post=post))
        if when:
            buttons.append(_issue(chat, user_link, "approve_schedule", snapshot, label="Approve & schedule", post=post))
    if statuses != {"approved"}:
        buttons.extend(
            [
                _issue(chat, user_link, "reject", snapshot, label="Reject this version", post=post),
                _issue(chat, user_link, "changes", snapshot, label="Request a revised version", post=post),
            ]
        )
    return {
        "text": text,
        "inline_keyboard": [[button] for button in buttons],
        "reply_markup": {"inline_keyboard": [[button] for button in buttons]},
        "photo_asset_id": str(attachments[0].media_asset_id) if attachments else None,
        "media": [{"asset_id": str(item.media_asset_id)} for item in attachments],
    }


def _confirmation_snapshot(message):
    job = message.job
    if (
        message.author_kind != "agent"
        or message.is_internal
        or job is None
        or job.status != "done"
        or (job.result or {}).get("awaiting_confirmation") is not True
        or (job.result or {}).get("message_id") != str(message.pk)
    ):
        raise TelegramActionError("Ask the team for a current complete brief before confirming preparation.")
    return {
        "message_id": str(message.pk),
        "body": message.body,
        "job_id": str(job.pk),
        "job_revision": job.revision,
        "result": job.result,
    }


def issue_brief_confirmation(chat, user_link, brief=None, *, confirmation_message=None):
    forbid_in_agent_work("issue a Telegram creative preparation button")
    member = fresh_member(user_link, "create_posts")
    if not internal_member(member):
        raise TelegramActionError("A paired team member must confirm preparation.")
    chat = TelegramChat.objects.select_related("connection", "conversation").get(pk=chat.pk)
    _chat_access(chat, user_link, member)
    message = confirmation_message or (brief if isinstance(brief, Message) else None)
    if message is None:
        raise TelegramActionError("Choose the account manager's complete brief confirmation message.")
    message = Message.objects.select_related("job").get(pk=message.pk, conversation=chat.conversation)
    snapshot = _confirmation_snapshot(message)
    if message.job.requested_by_id != member.user_id:
        raise TelegramActionError("Ask for a fresh brief addressed to your paired account.")
    text = message.body + "\n\nTap to confirm the facts and start the draft. " + FOOTER
    if len(text) > 3900:
        raise TelegramActionError("Review and confirm this complete brief inside SM Bean.")
    button = _issue(chat, user_link, "prepare", {"confirmation": snapshot}, label="Confirm facts & prepare draft")
    return {"text": text, "inline_keyboard": [[button]], "reply_markup": {"inline_keyboard": [[button]]}}


def issue_week_confirmation(chat, user_link, preview):
    """A short summary card with the confirm button; the complete evidence sits behind "Show evidence"."""
    from .weekly import analysis_text, summary_card_text, week_role_ok

    forbid_in_agent_work("issue a Telegram weekly preparation button")
    member = fresh_member(user_link, "create_posts")
    chat = TelegramChat.objects.select_related("connection", "conversation").get(pk=chat.pk)
    if not internal_member(member) or chat.audience == "client" or not week_role_ok(member):
        raise TelegramActionError("Review weekly preparation in a paired internal team or private chat.")
    _chat_access(chat, user_link, member)
    if not preview.get("needs_confirmation") or not preview.get("analysis_token"):
        raise TelegramActionError("Request a fresh weekly analysis before confirming preparation.")
    analysis = preview.get("analysis")
    if (
        not isinstance(analysis, dict)
        or analysis.get("week_start") != preview.get("week_start")
        or not analysis.get("accounts")
        or not isinstance(analysis.get("sources"), dict)
        or analysis.get("blockers")
    ):
        raise TelegramActionError(
            "The weekly evidence or configuration is incomplete or blocked. Request a complete review first."
        )
    # The complete evidence must fit one card, or no confirmation is offered at all.
    evidence = analysis_text(preview)
    text = summary_card_text(preview) + "\n" + FOOTER
    confirm = _issue(
        chat,
        user_link,
        "week_plan",
        {"week_start": preview["week_start"], "analysis_token": preview["analysis_token"]},
        label="Confirm analysis & prepare week",
    )
    show = _issue(
        chat,
        user_link,
        "week_evidence",
        {"week_start": preview["week_start"], "evidence": evidence},
        label="Show evidence",
    )
    keyboard = [[confirm], [show]]
    return {"text": text, "inline_keyboard": keyboard, "reply_markup": {"inline_keyboard": keyboard}}


def _binding(action, connection, sender, chat_id, bot_id):
    expected = action.snapshot.get("binding", {})
    actual = {
        "connection_id": str(connection.pk),
        "bot_id": bot_id,
        "chat_id": chat_id,
        "workspace_id": str(connection.workspace_id),
        "user_id": str(action.user_link.user_id),
        "telegram_user_id": sender,
        "connection_epoch": connection.updated_at.isoformat(),
        "link_epoch": action.user_link.updated_at.isoformat(),
        "chat_epoch": action.chat.updated_at.isoformat(),
        "conversation_id": str(action.chat.conversation_id),
        "audience": action.chat.audience,
        "private_user_id": str(action.chat.private_user_id) if action.chat.private_user_id else None,
    }
    if (
        expected != actual
        or bot_id != connection.bot_id
        or action.chat.chat_id != chat_id
        or action.user_link.telegram_user_id != sender
    ):
        raise TelegramActionError("This button belongs to a different reviewer, chat or bot. Request your own review.")


def verified_approver(workspace, actor):
    """Gate backstop: bare Telegram actors, clients and stale callbacks cannot stamp."""
    if actor.user is None or not actor.telegram_proof or not transaction.get_connection().in_atomic_block:
        return None
    action_id, nonce, sender, chat_id, bot_id = actor.telegram_proof
    action = (
        TelegramAction.objects.select_related("user_link__user", "chat__connection", "chat__conversation")
        .filter(pk=action_id)
        .first()
    )
    if action is None or action.kind not in APPROVAL_KINDS or action.used_at or action.expires_at <= timezone.now():
        return None
    try:
        if not secrets.compare_digest(action.token_digest, _digest(nonce)):
            return None
        member = fresh_member(action.user_link, "approve_posts", locked=True)
        connection = TelegramConnection.objects.get(pk=action.chat.connection_id)
        _chat_access(action.chat, action.user_link, member)
        _binding(action, connection, sender, chat_id, bot_id)
        if (
            not connection.approvals_enabled
            or member.workspace_id != workspace.pk
            or member.user_id != actor.user.pk
            or action.post_id is None
            or action.post.workspace_id != workspace.pk
            or _material(action.post) != action.snapshot.get("post", {}).get("material")
        ):
            return None
        if delivery.has_unresolved_holds(action.post) or any(
            delivery.state(row).get("kind") in delivery.UNRESOLVED
            for row in action.post.platform_posts.select_related("post__workspace", "social_account")
        ):
            return None
        return member.user
    except (PermissionDenied, TelegramActionError, Post.DoesNotExist):
        return None


def handle_callback(connection, payload):
    """Consume authenticated update data, never arbitrary model-generated approval intent."""
    try:
        forbid_in_agent_work("consume a Telegram human action")
        if not isinstance(payload, dict):
            raise TelegramActionError("Invalid review button.")
        sender, message = payload.get("from", {}), payload.get("message", {})
        data = payload.get("data", "")
        if (
            not isinstance(sender, dict)
            or not isinstance(message, dict)
            or sender.get("is_bot")
            or message.get("sender_chat")
            or message.get("forward_origin")
            or message.get("forward_from")
            or not isinstance(data, str)
            or not data.startswith(PREFIX)
            or len(data) != 37
        ):
            raise TelegramActionError("Use the original review button with your paired personal Telegram account.")
        nonce = data[len(PREFIX) :]
        if (
            not isinstance(message.get("chat"), dict)
            or not isinstance(message.get("from"), dict)
            or message["from"].get("is_bot") is not True
        ):
            raise TelegramActionError("Use the original bot review message in its paired chat.")
        sender_id, chat_id, bot_id = (
            sender.get("id"),
            message.get("chat", {}).get("id"),
            message.get("from", {}).get("id"),
        )
        if any(not isinstance(value, int) or isinstance(value, bool) for value in (sender_id, chat_id, bot_id)):
            raise TelegramActionError("A paired numeric Telegram identity and original bot message are required.")
        candidate = (
            TelegramAction.objects.select_related("user_link", "chat__connection")
            .filter(token_digest=_digest(nonce), chat__connection=connection)
            .first()
        )
        if candidate is None:
            raise TelegramActionError("This review button is unavailable. Request a fresh card.")
        with transaction.atomic():
            member = fresh_member(candidate.user_link, locked=True)
            current_connection = TelegramConnection.objects.get(pk=connection.pk)
            chat = (
                TelegramChat.objects.select_for_update(of=("self",))
                .select_related("connection", "conversation")
                .get(pk=candidate.chat_id)
            )
            action = (
                TelegramAction.objects.select_for_update(of=("self",))
                .select_related("user_link__user")
                .get(pk=candidate.pk)
            )
            action.chat = chat
            _chat_access(chat, action.user_link, member)
            _binding(action, current_connection, sender_id, chat_id, bot_id)
            if action.used_at or action.expires_at <= timezone.now():
                raise TelegramActionError("This button was already used or expired. Request a fresh review card.")
            if action.kind in {"prepare", "week_plan", "week_evidence"}:
                if not internal_member(member) or not member.effective_permissions.get("create_posts"):
                    raise TelegramActionError("A current paired team member must confirm preparation.")
                if action.kind == "week_evidence":
                    # Reading the evidence changes nothing; the confirm button stays its own one-use step.
                    outcome = {"ok": True, "text": str(action.snapshot.get("evidence") or "No evidence was saved.")}
                elif action.kind == "week_plan":
                    from .weekly import queue_week_plan

                    result = queue_week_plan(
                        action.user_link,
                        chat,
                        week_start=action.snapshot["week_start"],
                        confirmed=True,
                        analysis_token=action.snapshot["analysis_token"],
                    )
                    outcome = {"ok": bool(result.get("started")), "text": result["message"]}
                else:
                    from apps.studio import chat as studio_chat

                    confirmation = action.snapshot["confirmation"]
                    source = (
                        Message.objects.select_for_update(of=("self",))
                        .select_related("job")
                        .get(pk=confirmation["message_id"], conversation=chat.conversation)
                    )
                    if _confirmation_snapshot(source) != confirmation or source.job.requested_by_id != member.user_id:
                        raise TelegramActionError(
                            "The brief changed. Ask for a current complete brief and confirm it again."
                        )
                    with acting_as(member.user, TELEGRAM):
                        posted = studio_chat.post_message(
                            chat.conversation,
                            member.user,
                            "I reviewed the complete brief and source facts. Prepare a draft for final human review.",
                            kind="confirm_brief",
                            confirmation_message_id=str(source.pk),
                            facts_confirmed=True,
                            explicit_assistant_request=True,
                            telegram_context={"chat_id": str(chat.pk), "user_link_id": str(action.user_link_id)},
                        )
                    outcome = {
                        "ok": posted.job is not None,
                        "text": "The team started on the draft. You'll get it here to approve."
                        if posted.job
                        else (posted.note or "Preparation is blocked; check SM Bean."),
                    }
            else:
                outcome = _apply_post(action, member, nonce, sender_id, chat_id, bot_id)
            action.used_at, action.result = timezone.now(), outcome
            action.save(update_fields=["used_at", "result"])
            return outcome
    except (ValueError, PermissionDenied, Post.DoesNotExist, Message.DoesNotExist) as exc:
        return {"ok": False, "text": str(exc) or "This action is unavailable. Request a fresh review."}


def _apply_post(action, member, nonce, sender_id, chat_id, bot_id):
    if not action.chat.connection.approvals_enabled or not gate.enforced(member.workspace):
        raise TelegramActionError("Telegram exact human approvals are disabled. Review in SM Bean.")
    post = (
        Post.objects.select_for_update()
        .select_related("workspace__organization")
        .get(pk=action.post_id, workspace=member.workspace)
    )
    rows = list(
        PlatformPost.objects.select_for_update(of=("self",))
        .select_related("post__workspace", "social_account")
        .filter(post=post)
        .order_by("pk")
    )
    list(PostMedia.objects.select_for_update().filter(post=post))
    list(MediaAsset.objects.select_for_update().filter(post_usages__post=post))
    _post_available(post)
    if _post_snapshot(post) != action.snapshot.get("post"):
        raise TelegramActionError(
            "Caption, graphic, account, sources, revision or time changed. Request a fresh exact review."
        )
    statuses = {row.status for row in rows}
    client = not internal_member(member)
    if not member.effective_permissions.get("approve_posts"):
        raise TelegramActionError("Your current role cannot action this review.")
    when = _future(action.snapshot["publish_at"]) if action.snapshot.get("publish_at") else None
    if client:
        if (
            action.chat.audience != "client"
            or statuses != {"pending_client"}
            or action.kind not in {"client_signoff", "reject", "changes"}
            or any(not row.approved_fingerprint or row.approved_fingerprint != gate.fingerprint(row) for row in rows)
        ):
            raise TelegramActionError("Client sign-off cannot originate the internal publication approval.")
    elif action.kind in {"approve", "approve_schedule"} and not statuses <= {"pending_review", "approved"}:
        raise TelegramActionError("This version is no longer awaiting internal approval.")
    if action.kind in APPROVAL_KINDS and client:
        raise TelegramActionError("Only a current internal approver can approve a publishing time.")
    with acting_as_telegram(action, nonce=nonce, telegram_user_id=sender_id, chat_id=chat_id, bot_id=bot_id):
        if action.kind in {"approve", "approve_schedule", "client_signoff"}:
            if action.kind != "client_signoff" and when is not None:
                post.proposed_publish_at = when
                post.save(update_fields=["proposed_publish_at", "updated_at"])
            result = approval_services.approve_post(
                post, member.user, member.workspace, "Explicit human review in Telegram."
            )
            if not result:
                raise TelegramActionError("The approval gate refused this version. Request a fresh review.")
            if (
                action.kind != "client_signoff"
                and when is not None
                and any(row.approved_publish_at != when for row in post.platform_posts.all())
            ):
                raise TelegramActionError(
                    "An existing schedule conflicts with the reviewed time. Choose the new time in SM Bean and request fresh approval."
                )
        elif action.kind == "reject":
            approval_services.reject_post(
                post, member.user, member.workspace, "Rejected this exact reviewed version in Telegram."
            )
        elif action.kind == "changes":
            approval_services.request_changes(
                post,
                member.user,
                member.workspace,
                "Please revise this exact version; the reviewer will provide details in the thread.",
            )
        elif action.kind != "schedule":
            raise TelegramActionError("Unsupported review action.")
        if action.kind in {"approve_schedule", "schedule"}:
            if when is None:
                raise TelegramActionError("A future exact publishing time is required.")
            fresh_rows = list(post.platform_posts.select_related("post__workspace", "social_account").order_by("pk"))
            if any(row.status == "pending_client" for row in fresh_rows):
                return {
                    "ok": True,
                    "text": "Approved internally; client sign-off is still required. Nothing was scheduled.",
                }
            if any(row.status != "approved" for row in fresh_rows):
                raise TelegramActionError("Every destination must complete approval before scheduling.")
            for row in fresh_rows:
                _future(when)
                transition_platform_post(row, "scheduled", scheduled_at=when)
            return {
                "ok": True,
                "text": "Approved and scheduled for the exact reviewed time. Delivery is not yet confirmed.",
                "post_id": str(post.pk),
            }
    text = {
        "client_signoff": "Client sign-off recorded. Your agency must still confirm scheduling.",
        "changes": "Changes requested. Tell the team what should change and you'll get a new version to review.",
        "reject": "This version was rejected. Nothing was sent.",
        "approve": "Approved, not yet scheduled. Choose its time to publish.",
    }.get(action.kind, "Review decision recorded. Nothing was sent.")
    return {
        "ok": True,
        "text": text,
        "post_id": str(post.pk),
    }
