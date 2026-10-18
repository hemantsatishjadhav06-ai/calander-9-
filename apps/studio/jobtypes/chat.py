"""The ``chat`` job: the account manager answers one message, and the team acts on it.

One stage, ``answer``, run in the worker inside ``guards.agent_work`` (the
engine does that), so nothing the model chooses ever runs in a web request
with a person's approval rights. The stage:

1. reads the thread (internal notes left out of a client thread), what the
   thread is about — only what the reader may see — and the brand profile;
2. asks the account manager for a reply and one action from a closed list,
   offered only when the person who asked may have it done and the thread's
   own item supports it (a revision needs a post the team made, an article
   edit needs an article, and so on);
3. checks the action again in code and does it through the same services
   people use: ``studio.services.request_changes`` / ``new_angles`` (after
   ``reopen`` when a client's change request sent the post back),
   ``create_brief`` for a new post, a ``blog`` job for an article. The post or
   article always comes from the thread's row, never from the answer;
4. posts the reply — replaced by a plain sentence from the code when the action
   couldn't be done, so the thread never claims work that isn't happening —
   and tells people who need to know.

It never approves, schedules or publishes; a client's own request to change a
post waiting for their OK is recorded by the portal view, in the client's own
request, before this job runs.
"""

from __future__ import annotations

import logging
import uuid
import zoneinfo
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .. import budget, chat, creative_brief, creative_sources, engine, memory, pipeline, services
from ..brand_defaults import ensure_profile
from ..models import AgencyJob, AgencySettings, AgentRun, Conversation, Message, StudioBrief
from ..roles import base
from ..roles import client as client_roles

logger = logging.getLogger(__name__)

REVISION_ACTIONS = ("revise_copy", "revise_design", "new_picture", "new_angles")
ALL_ACTIONS = ("answer", *REVISION_ACTIONS, "new_post", "edit_blog", "escalate")
#: What a client may ask for: changes to their own posts and new posts (which still need the agency's approval).
CLIENT_ACTIONS = frozenset({"answer", *REVISION_ACTIONS, "new_post", "escalate"})
#: Anyone else who somehow wrote (a viewer, an ex-member): an answer, or a person.
OTHER_ACTIONS = frozenset({"answer", "escalate"})

HANDOFF = "A person from the team will reply here."
NOT_ALLOWED = "I can't arrange that from here, so I've passed your message to a person on the team. " + HANDOFF
BUSY = "The team is already working on this post. Once this round is ready, tell me what to change and I'll pass it on."
ARTICLE_LOCKED = (
    "This article is approved or already live, so the writers can't change it from here. I've asked a person on "
    "the team to look at your request. " + HANDOFF
)
#: Posts one person may have in the works at once from the thread.
MAX_ACTIVE_CHAT_POSTS = 2
SOURCE_MAX_AGE = timedelta(minutes=30)
LOCKED = (
    "This post has already been approved or scheduled, so it can't be changed from here. I've asked a person on the "
    "team to pause it and make the change."
)

WAITING_FOR_YOU = (
    "This post is waiting for your OK. To change it, press “Request a change” on it under Approvals and say what "
    "you'd like — that sends it back to the team, and the new version comes back to you."
)
WAITING_FOR_CLIENT = (
    "This post is waiting for the client's OK, so it can't be changed from here. I've asked a person on the team to "
    "take it back from the client first."
)

_FEEDBACK_LEAD = {
    "revise_copy": "Change the words: ",
    "revise_design": "Change the design (keep the caption unless this needs it): ",
    "new_picture": "Paint a new picture: ",
}

_CLIENT_STATUS = {
    "draft": "with the agency team",
    "pending_review": "with the agency team for their check",
    "changes_requested": "being revised after a change request",
    "rejected": "with the agency team",
    "approved": "approved, not on the calendar yet",
    "pending_client": "waiting for the client's OK",
    "on_hold": "on hold — nothing goes out while held",
    "publishing": "going out now",
    "published": "published",
    "failed": "the team is sorting out a problem posting it",
}


@dataclass
class Target:
    brief: StudioBrief | None = None
    post: Any = None
    blog_post: Any = None
    ambiguous_briefs: list[StudioBrief] = field(default_factory=list)
    invalid_selection: bool = False


@dataclass
class Outcome:
    reply: str
    action: str
    status: str = ""
    notify_staff: bool = False
    result: dict[str, Any] = field(default_factory=dict)


def _lock_current_job(job):
    """Serialize side effects with cancellation/restart, after all network work."""
    current = (
        AgencyJob.objects.select_for_update()
        .filter(
            pk=job.pk,
            workspace_id=job.workspace_id,
            conversation_id=job.conversation_id,
            requested_by_id=job.requested_by_id,
            revision=job.revision,
            stage=job.stage,
            status=AgencyJob.Status.WORKING,
        )
        .first()
    )
    if current is None:
        raise engine.StaleJobError


def _current_membership(job, conversation, requester):
    """Lock and revalidate the author and permissions before mutating creative work."""
    from django.core.exceptions import PermissionDenied

    from apps.telegram.permissions import current_member

    if "workflow_telegram_context" in (job.input or {}):
        from apps.telegram.workflow_bridge import workflow_member

        try:
            member = workflow_member(job, conversation, requester, locked=True)
        except PermissionDenied:
            return None
        _lock_current_job(job)
        return member
    telegram_context = (job.input or {}).get("telegram_context")
    if telegram_context is not None:
        try:
            kind, paired_member = chat.telegram_job_author_kind(job, conversation, requester, locked=True)
        except chat.ChatError:
            return None
        _lock_current_job(job)
        if not Message.objects.filter(
            pk=(job.input or {}).get("message_id"),
            conversation=conversation,
            author_id=requester.pk,
            author_kind=kind,
            is_internal=False,
        ).exists():
            return None
        return paired_member
    # Use the same workspace/actor/role -> job order as Telegram and the
    # assistant task controls. A returning web result must not hold the job
    # while waiting for a workspace lock held by a person pausing that job.
    try:
        membership = current_member(conversation.workspace, requester, locked=True)
    except PermissionDenied:
        return None
    _lock_current_job(job)
    current_thread = (
        Conversation.objects.select_for_update()
        .filter(
            pk=conversation.pk,
            workspace_id=job.workspace_id,
        )
        .first()
    )
    if (
        current_thread is None
        or membership.workspace_id != job.workspace_id
        or current_thread.audience != conversation.audience
    ):
        return None
    # Retain the fresh audience/targets while preserving the pre-call model input.
    conversation.audience = current_thread.audience
    conversation.brief_id, conversation.post_id, conversation.blog_post_id = (
        current_thread.brief_id,
        current_thread.post_id,
        current_thread.blog_post_id,
    )
    conversation._state.fields_cache.clear()
    conversation.workspace = membership.workspace
    try:
        kind = chat.web_kind_for_member(membership, conversation)
    except chat.ChatError:
        return None
    if not Message.objects.filter(
        pk=(job.input or {}).get("message_id"),
        conversation=conversation,
        author_id=requester.pk,
        author_kind=kind,
        is_internal=False,
    ).exists():
        return None
    return membership


# ---------------------------------------------------------------------------
# The stage
# ---------------------------------------------------------------------------


def answer(job: AgencyJob) -> None:
    workspace = job.workspace
    conversation = None
    if job.conversation_id is not None:
        conversation = (
            Conversation.objects.filter(pk=job.conversation_id, workspace_id=job.workspace_id)
            .select_related("workspace", "brief", "post", "blog_post")
            .first()
        )
    if conversation is None:
        engine.finish(job, result={"skipped": "The thread was deleted."})
        return None
    message_id = str((job.input or {}).get("message_id") or "")
    trigger = None
    if message_id:
        trigger = Message.objects.filter(pk=message_id, conversation=conversation).select_related("author").first()
    if trigger is None:
        engine.finish(job, result={"skipped": "The message was deleted."})
        return None
    if not budget.can_spend(workspace):
        chat.post_system_message(
            conversation, chat.refusal_text(workspace, "budget", audience=conversation.audience), job=job
        )
        engine.finish(job, result={"skipped": "over budget"})
        return None

    requester = job.requested_by
    membership = chat.membership_for(requester, workspace)
    speaker = "staff" if chat.is_staff_membership(membership) else "client"
    for_client = conversation.audience == Conversation.Audience.CLIENT
    if requester is None or not requester.is_active or trigger.author_id != requester.pk or trigger.is_internal:
        engine.finish(job, result={"skipped": "This request no longer has an authorized author."})
        return None
    try:
        telegram_context = (job.input or {}).get("telegram_context")
        if "workflow_telegram_context" in (job.input or {}):
            from django.core.exceptions import PermissionDenied

            from apps.telegram.workflow_bridge import workflow_member

            try:
                membership = workflow_member(job, conversation, requester)
            except PermissionDenied:
                raise chat.ChatError("This workflow Telegram author is no longer authorized.") from None
            author_kind = Message.AuthorKind.STAFF
        elif telegram_context is not None:
            author_kind, membership = chat.telegram_job_author_kind(job, conversation, requester)
        else:
            author_kind, membership = chat.web_author_kind(conversation, requester)
    except chat.ChatError as exc:
        reason = (
            str(exc)
            if (job.input or {}).get("telegram_context") is not None
            else "This request no longer has an authorized author."
        )
        engine.finish(job, result={"skipped": reason})
        return None
    if author_kind != trigger.author_kind:
        engine.finish(job, result={"skipped": "The request author's role changed."})
        return None
    speaker = "client" if author_kind == Message.AuthorKind.CLIENT else "staff"
    if (job.input or {}).get("kind") == "confirm_brief":
        outcome = _confirm(job, conversation, trigger, requester, membership)
        reply = chat.post_agent_message(
            conversation, outcome.reply, job=job, action=outcome.action, action_status=outcome.status
        )
        engine.finish(
            job,
            result={**outcome.result, "action": outcome.action, "status": outcome.status, "message_id": str(reply.pk)},
        )
        return None
    target = resolve_target(
        conversation, requester=requester, target_brief_id=(job.input or {}).get("target_brief_id") or ""
    )
    if target.invalid_selection:
        reply = chat.post_agent_message(
            conversation,
            "Choose a draft from this thread's draft selector, then send the requested change here.",
            job=job,
            action="answer",
            action_status=Message.ActionStatus.DECLINED,
        )
        engine.finish(
            job, result={"action": "answer", "status": Message.ActionStatus.DECLINED, "message_id": str(reply.pk)}
        )
        return None
    allowed = allowed_actions(membership, conversation, target)
    if telegram_context is not None and speaker == "client":
        allowed = tuple(action for action in allowed if action in CLIENT_ACTIONS)
    profile = ensure_profile(workspace)
    guided = (speaker == "staff" and conversation.audience == Conversation.Audience.INTERNAL) or (
        telegram_context is not None
        and conversation.audience == Conversation.Audience.CLIENT
        and (speaker == "client" or (job.input or {}).get("explicit_assistant_request") is True)
    )
    context = _guided_context(job, conversation, trigger, requester, profile) if guided else None
    item_context = describe(target, workspace, for_client=for_client)
    if guided and target.brief is not None:
        human_input = job.input or {}
        chosen_reference = human_input.get("reference_id") or ""
        if chosen_reference == "none":
            item_context += "\nThe person explicitly chose to clear the supplied photo."
        elif chosen_reference:
            chosen = _reference(workspace, chosen_reference)
            if chosen is not None:
                item_context += "\nThe person selected a replacement photo for this revision: " + base.untrusted(
                    "person_selected_photo", chosen.title or chosen.filename, limit=300
                )
        chosen_style = human_input.get("style_mode") or ""
        if chosen_style in {"brand", "fresh"}:
            item_context += f"\nThe person selected the {chosen_style} layout option for this revision."
    extra = (
        {
            "guided": True,
            "creative_brief": context["creative_brief"],
            "sources": context["sources"],
            "available_channels": _channel_choices(context["accounts"]),
        }
        if context is not None
        else {}
    )

    if "workflow_telegram_context" in (job.input or {}):
        from django.core.exceptions import PermissionDenied

        from apps.telegram.workflow_bridge import workflow_member

        try:
            workflow_member(job, conversation, requester)
        except PermissionDenied:
            engine.finish(job, result={"skipped": "This workflow Telegram author is no longer authorized."})
            return None
    elif telegram_context is None:
        try:
            current_kind, membership = chat.web_author_kind(conversation, requester)
        except chat.ChatError:
            current_kind = ""
        if current_kind != trigger.author_kind:
            engine.finish(job, result={"skipped": "This request no longer has an authorized author."})
            return None
    else:
        try:
            current_kind, membership = chat.telegram_job_author_kind(job, conversation, requester)
        except chat.ChatError as exc:
            engine.finish(job, result={"skipped": str(exc)})
            return None
        if current_kind != trigger.author_kind:
            engine.finish(job, result={"skipped": "This Telegram role changed. Send the request again."})
            return None
    # Source reads may finish after a person pauses/stops the task. Fence this
    # request once more immediately before beginning any paid model work.
    with transaction.atomic():
        _lock_current_job(job)
    run, result = engine.call(
        job,
        "account_manager",
        lambda: client_roles.account_manager(
            profile,
            audience=conversation.audience,
            speaker=speaker,
            history=history(conversation, trigger, for_client=for_client),
            item=item_context,
            request=trigger.body,
            request_kind=str((job.input or {}).get("kind") or ""),
            allowed_actions=list(allowed),
            **extra,
        ),
        effort=client_roles.ACCOUNT_MANAGER_EFFORT,
    )
    out = result.output
    # Intake source reads happen before taking any mutation locks.
    prepared_intake = None
    if (
        context is not None
        and out.action in allowed
        and out.action in {"answer", "new_post"}
        and (out.action == "new_post" or out.creative_brief is not None)
    ):
        prepared_intake = _intake(job, conversation, trigger, out, context)
    with transaction.atomic():
        membership = _current_membership(job, conversation, requester)
        if membership is None or not budget.can_spend(workspace):
            skipped = "This request no longer has an authorized author." if membership is None else "over budget"
            engine.end(run, summary=skipped, status=AgentRun.Status.SKIPPED, result=result)
            engine.finish(job, result={"skipped": skipped})
            return None
        target = resolve_target(
            conversation, requester=requester, target_brief_id=(job.input or {}).get("target_brief_id") or ""
        )
        allowed = allowed_actions(membership, conversation, target)
        if telegram_context is not None:
            try:
                current_kind, _member = chat.telegram_job_author_kind(job, conversation, requester, locked=True)
            except chat.ChatError:
                current_kind = ""
            if current_kind != trigger.author_kind:
                engine.end(run, summary="Telegram pairing changed", status=AgentRun.Status.SKIPPED, result=result)
                engine.finish(job, result={"skipped": "This Telegram pairing changed."})
                return None
            speaker = "client" if current_kind == Message.AuthorKind.CLIENT else "staff"
            if speaker == "client":
                allowed = tuple(action for action in allowed if action in CLIENT_ACTIONS)
        else:
            speaker = "staff" if chat.is_staff_membership(membership) else "client"
        try:
            outcome = perform(
                job,
                conversation,
                target,
                requester,
                membership,
                out,
                allowed,
                trigger,
                speaker=speaker,
                guided_context=context,
                prepared_intake=prepared_intake,
            )
        except engine.StaleJobError:
            raise
        except Exception:
            logger.exception("Chat job %s: acting on %s failed", job.pk, out.action)
            outcome = Outcome(
                reply="Something went wrong passing this on, so I've asked a person on the team to pick it up. "
                + HANDOFF,
                action=out.action,
                status=Message.ActionStatus.NEEDS_HUMAN,
                notify_staff=True,
            )
        if outcome.notify_staff and chat.is_private_conversation(conversation):
            destination = "client group" if speaker == "client" else "internal team group"
            sharing_instruction = (
                f"Share the request yourself in the intended {destination} for a person's review. "
                "This private chat is not forwarded to the agency."
            )
            if outcome.result.get("client_preparation_requested"):
                outcome.reply = (
                    creative_brief.summary(outcome.result.get("creative_brief")) + "\n\n" + sharing_instruction
                )
                outcome.reply += " A paired agency lead can check the request and confirm draft preparation there; your message has not started or approved a draft."
            elif outcome.status == Message.ActionStatus.NEEDS_HUMAN:
                outcome.reply = "This request needs a person's decision. " + sharing_instruction
            else:
                outcome.reply += "\n\n" + sharing_instruction
            outcome.notify_staff = False
        reply = chat.post_agent_message(
            conversation, outcome.reply, job=job, action=outcome.action, action_status=outcome.status
        )
        engine.end(
            run,
            summary=f"Answered {trigger.sender_name}: {outcome.action.replace('_', ' ')}"
            + (f" ({outcome.status.replace('_', ' ')})" if outcome.status else "")
            + f". {out.reason}".rstrip(". ")
            + ".",
            output={
                "action": out.action,
                "performed": outcome.action,
                "status": outcome.status,
                "needs_human": out.needs_human,
                "instructions": out.instructions,
                "reason": out.reason,
                **outcome.result,
            },
            result=result,
        )
        engine.finish(
            job,
            result={**outcome.result, "action": outcome.action, "status": outcome.status, "message_id": str(reply.pk)},
        )
    if outcome.notify_staff:
        chat.notify_staff(
            conversation,
            title="A message in the team thread needs a person",
            body=f"{trigger.sender_name}: “{trigger.body[:160]}” — {out.reason}"[:500],
            exclude=requester if speaker == "staff" else None,
            kind="needs_person",
        )
    if speaker == "client" and requester is not None:
        chat.notify_clients_of_reply(conversation, only=requester)
    return None


JOB = engine.JobType(
    kind="chat",
    stages=(engine.Stage("answer", "account_manager", answer),),
    priority=engine.PRIORITY_CHAT,
)


# ---------------------------------------------------------------------------
# What the thread is about, and what may be done
# ---------------------------------------------------------------------------


def resolve_target(conversation: Conversation, *, requester=None, target_brief_id="") -> Target:
    """The thread's item, re-checked against the workspace (targets never come from the model)."""
    workspace_id = conversation.workspace_id

    def own(item):
        return item if item is not None and item.workspace_id == workspace_id else None

    if target_brief_id:
        try:
            selected_id = uuid.UUID(str(target_brief_id))
        except (ValueError, TypeError, AttributeError):
            return Target(invalid_selection=True)
        choices = StudioBrief.objects.filter(
            pk=selected_id,
            workspace_id=workspace_id,
            origin=StudioBrief.Origin.CHAT,
            job__workspace_id=workspace_id,
            job__conversation=conversation,
        )
        if not chat.is_staff(requester, conversation.workspace):
            choices = choices.filter(requested_by=requester) if requester is not None else choices.none()
        selected = choices.first()
        if selected is None:
            return Target(invalid_selection=True)
        return Target(brief=selected, post=own(selected.post) if selected.post_id else None)

    brief = own(conversation.brief) if conversation.brief_id else None
    post = own(conversation.post) if conversation.post_id else None
    blog_post = own(conversation.blog_post) if conversation.blog_post_id else None
    if brief is None and post is not None:
        brief = (
            StudioBrief.objects.filter(workspace_id=workspace_id, post=post)
            .exclude(status=StudioBrief.Status.DISCARDED)
            .order_by("-created_at")
            .first()
        )
    if post is None and brief is not None and brief.post_id:
        post = own(brief.post)
    if brief is None and post is None and blog_post is None and requester is not None:
        from apps.composer.models import PlatformPost

        locked_channels = PlatformPost.objects.filter(post_id=OuterRef("post_id")).exclude(
            status__in=pipeline.REVISABLE_STATUSES
        )
        revisable_channels = PlatformPost.objects.filter(
            post_id=OuterRef("post_id"), status__in=pipeline.REVISABLE_STATUSES
        )
        linked: list[StudioBrief] = list(
            StudioBrief.objects.filter(
                workspace_id=workspace_id,
                origin=StudioBrief.Origin.CHAT,
                job__workspace_id=workspace_id,
                job__conversation=conversation,
                requested_by=requester,
            )
            .exclude(status=StudioBrief.Status.DISCARDED)
            .annotate(_has_locked_channel=Exists(locked_channels), _has_revisable_channel=Exists(revisable_channels))
            .filter(~Q(status=StudioBrief.Status.APPROVED) | Q(_has_locked_channel=False, _has_revisable_channel=True))
            .order_by("-created_at")[:3]
        )
        if len(linked) > 1:
            return Target(ambiguous_briefs=linked)
        if linked:
            brief = linked[0]
            post = own(brief.post) if brief.post_id else None
    return Target(brief=brief, post=post, blog_post=blog_post)


def allowed_actions(membership, conversation: Conversation, target: Target) -> tuple[str, ...]:
    """The actions the account manager may choose for this person in this thread."""
    if chat.is_staff_membership(membership):
        permitted: frozenset[str] = frozenset(ALL_ACTIONS)
    elif chat.is_client_membership(membership) and conversation.audience == Conversation.Audience.CLIENT:
        permitted = CLIENT_ACTIONS
    else:
        permitted = OTHER_ACTIONS
    offered = ["answer"]
    if target.brief is not None or target.ambiguous_briefs:
        offered += REVISION_ACTIONS
    offered.append("new_post")
    if target.blog_post is not None:
        offered.append("edit_blog")
    offered.append("escalate")
    return tuple(action for action in offered if action in permitted)


def _zone(workspace):
    try:
        return zoneinfo.ZoneInfo(workspace.effective_timezone or "UTC")
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return zoneinfo.ZoneInfo("UTC")


def _when(moment, workspace) -> str:
    if moment is None:
        return ""
    return f"{moment.astimezone(_zone(workspace)):%a %d %b, %H:%M} ({workspace.effective_timezone or 'UTC'})"


def _channels(post, workspace, *, for_client: bool) -> list[str]:
    lines = []
    for pp in post.platform_posts.select_related("social_account"):
        account = pp.social_account
        name = account.account_name or account.get_platform_display()
        status = _CLIENT_STATUS.get(pp.status, pp.status) if for_client else pp.get_status_display()
        if pp.status == "scheduled" and pp.scheduled_at:
            status = f"scheduled for {_when(pp.scheduled_at, workspace)}"
        lines.append(f"{account.get_platform_display()} ({name}): {status}")
    return lines


def describe(target: Target, workspace, *, for_client: bool) -> str:
    """What the thread is about, as the account manager reads it — for a client, only what a client may see."""
    brief, post, blog_post = target.brief, target.post, target.blog_post
    if blog_post is not None and not for_client:
        return "\n".join(
            [
                f"The blog article “{blog_post.title}”. Status: {blog_post.get_status_display()}.",
                f"Search title: {blog_post.seo_title or '(none yet)'}; focus keyword: "
                f"{blog_post.focus_keyword or '(none yet)'}.",
                base.untrusted("article_excerpt", blog_post.excerpt or blog_post.body[:600], limit=800),
            ]
        )
    if post is None and brief is None:
        return _describe_general(workspace, for_client=for_client)

    lines = []
    if for_client:
        lines.append("A post the agency made for the client.")
    elif brief is not None:
        lines.append(f"A post the team made from an idea. Brief status: {brief.get_status_display()}.")
        if brief.status in StudioBrief.ACTIVE_STATUSES:
            lines.append("The team is working on it right now.")
    else:
        lines.append("A post someone on the team wrote in the composer (not made by the agents).")
    if post is not None:
        lines += _channels(post, workspace, for_client=for_client)
        when = post.scheduled_at or post.proposed_publish_at
        if when and not post.scheduled_at:
            lines.append(f"Proposed time (not scheduled until a person approves): {_when(when, workspace)}.")
    elif brief is not None and brief.proposed_publish_at:
        lines.append(f"Proposed time: {_when(brief.proposed_publish_at, workspace)}.")
    if brief is not None and not for_client:
        review = brief.review_notes or {}
        if review.get("score"):
            lines.append(f"Brand reviewer: {review['score']}/10 — {review.get('summary', '')}".strip())
        if review.get("risk_flags"):
            lines.append("Reviewer's flags: " + "; ".join(map(str, review["risk_flags"])))
        if brief.feedback:
            lines.append(base.untrusted("latest_change_request", brief.feedback, limit=800))
        lines.append(base.untrusted("original_idea", brief.idea, limit=800))
    caption = (brief.caption if brief is not None else "") or (post.caption if post is not None else "")
    lines.append(base.untrusted("caption", caption, limit=2500))
    if brief is not None:
        graphic = (brief.post_copy or {}).get("alt_text") or brief.headline
        if graphic:
            lines.append(base.untrusted("the_graphic", graphic, limit=400))
    return "\n".join(lines)


def _describe_general(workspace, *, for_client: bool) -> str:
    from apps.composer.models import Post

    if for_client:
        waiting = list(
            Post.objects.filter(workspace=workspace, platform_posts__status="pending_client")
            .distinct()
            .order_by("-created_at")[:5]
        )
        lines = ["The client's account in general (no single post)."]
        if waiting:
            lines.append(f"{len(waiting)} post(s) are waiting for the client's OK in their portal:")
            lines += [base.untrusted("post_title", p.title or (p.caption or "")[:80], limit=120) for p in waiting]
        else:
            lines.append("No posts are waiting for the client's OK right now.")
        return "\n".join(lines)
    recent = list(
        StudioBrief.objects.filter(workspace=workspace)
        .exclude(status=StudioBrief.Status.DISCARDED)
        .select_related("chosen_concept")
        .order_by("-created_at")[:5]
    )
    lines = ["The workspace in general (no single post). Recent work by the team:"]
    lines += [f"- {base.untrusted('title', b.title, limit=120)} — {b.get_status_display()}" for b in recent]
    if not recent:
        lines.append("(nothing yet)")
    return "\n".join(lines)


def history(conversation: Conversation, trigger: Message, *, for_client: bool) -> list[str]:
    """The messages before ``trigger``, oldest first; people's words wrapped as untrusted text."""
    rows = list(
        chat.visible_messages(conversation, for_client=for_client)
        .filter(created_at__lt=trigger.created_at)
        .exclude(pk=trigger.pk)
        .order_by("-created_at")[: chat.HISTORY_LIMIT]
    )
    rows.reverse()
    lines = []
    for message in rows:
        if message.author_kind == Message.AuthorKind.AGENT:
            lines.append(f"{message.sender_name} (the team's reply): {message.body[:1500]}")
        elif message.author_kind == Message.AuthorKind.SYSTEM:
            lines.append(f"(system note) {message.body[:500]}")
        else:
            who = "client" if message.author_kind == Message.AuthorKind.CLIENT else "team member"
            tag = "internal_note" if message.is_internal else f"{who.replace(' ', '_')}_message"
            lines.append(base.untrusted(tag, message.body, limit=1500, author=f"{message.sender_name} ({who})"))
    return lines


# ---------------------------------------------------------------------------
# Acting on the answer
# ---------------------------------------------------------------------------


def perform(
    job,
    conversation,
    target: Target,
    requester,
    membership,
    out,
    allowed,
    trigger,
    *,
    speaker="staff",
    guided_context=None,
    prepared_intake=None,
) -> Outcome:
    """Validate the account manager's action against what this person may ask for here, and do it."""
    action = out.action
    reply = (out.reply or "").strip()
    instructions = (out.instructions or "").strip() or trigger.body
    if action not in allowed:
        return Outcome(NOT_ALLOWED, action, Message.ActionStatus.NEEDS_HUMAN, notify_staff=True)
    if (
        guided_context is not None
        and action in {"answer", "new_post"}
        and (action == "new_post" or out.creative_brief is not None)
    ):
        intake = (
            prepared_intake if prepared_intake is not None else _intake(job, conversation, trigger, out, guided_context)
        )
        if (job.input or {}).get("telegram_context") is not None and speaker == "client":
            intake.result["awaiting_confirmation"] = False
            intake.result["client_preparation_requested"] = True
            intake.reply = intake.reply.replace(
                "Use Confirm brief after checking the source facts. This only starts a draft for human approval.",
                "A paired agency lead must send /brief here to check this request and confirm preparation. Your message does not approve or start a draft.",
            )
            if not creative_brief.missing(intake.result.get("creative_brief")):
                intake.status = Message.ActionStatus.NEEDS_HUMAN
                intake.notify_staff = True
        return intake
    if action == "answer":
        if out.needs_human:
            return Outcome(_with_handoff(reply), action, Message.ActionStatus.NEEDS_HUMAN, notify_staff=True)
        return Outcome(reply, action)
    if action == "escalate":
        return Outcome(_with_handoff(reply), action, Message.ActionStatus.NEEDS_HUMAN, notify_staff=True)
    if action in REVISION_ACTIONS:
        if target.ambiguous_briefs:
            names = "; ".join((brief.title or brief.idea)[:100] for brief in target.ambiguous_briefs)
            return Outcome(
                f"Which draft should I change? There are several unfinished drafts in this thread: {names}. Choose the intended draft in this thread's draft selector and send the change here.",
                action,
                Message.ActionStatus.DECLINED,
            )
        outcome = _revise(
            target.brief,
            action,
            instructions,
            reply,
            speaker=speaker,
            requester=requester,
            revision_input=job.input or {},
            allow_choices=speaker == "staff"
            and (
                conversation.audience == Conversation.Audience.INTERNAL
                or (
                    (job.input or {}).get("telegram_context") is not None
                    and (job.input or {}).get("explicit_assistant_request") is True
                )
            ),
        )
    elif action == "new_post":
        outcome = _new_post(job, conversation.workspace, requester, membership, instructions, reply)
    elif action == "edit_blog":
        outcome = _edit_blog(job, conversation.workspace, target.blog_post, requester, instructions, reply)
    else:  # pragma: no cover - the schema allows nothing else
        return Outcome(NOT_ALLOWED, action, Message.ActionStatus.NEEDS_HUMAN, notify_staff=True)
    if out.needs_human:
        outcome.notify_staff = True
    return outcome


def _with_handoff(reply: str) -> str:
    reply = reply or "Thanks for your message."
    return reply if "person" in reply.lower() else f"{reply} {HANDOFF}"


def _revise(
    brief: StudioBrief | None,
    action: str,
    instructions: str,
    reply: str,
    *,
    speaker: str = "staff",
    requester=None,
    revision_input=None,
    allow_choices=False,
) -> Outcome:
    if brief is None:
        return Outcome(NOT_ALLOWED, action, Message.ActionStatus.NEEDS_HUMAN, notify_staff=True)
    brief.refresh_from_db()
    if brief.status in (StudioBrief.Status.PLANNED, *StudioBrief.ACTIVE_STATUSES):
        return Outcome(BUSY, action, Message.ActionStatus.DECLINED)
    if brief.status == StudioBrief.Status.DISCARDED:
        return Outcome(
            "This post was discarded, so I've asked a person on the team to look at your request. " + HANDOFF,
            action,
            Message.ActionStatus.NEEDS_HUMAN,
            notify_staff=True,
        )
    human_choices = revision_input or {}
    reference_id = human_choices.get("reference_id") or ""
    style_mode = human_choices.get("style_mode") or ""
    if (reference_id or style_mode) and not allow_choices:
        return Outcome(
            "Photo and style choices must be made by the agency team in its internal thread.",
            action,
            Message.ActionStatus.DECLINED,
        )
    source_picture_mode = "keep" if not reference_id else "clear" if reference_id == "none" else "replace"
    source_picture = _reference(brief.workspace, reference_id) if source_picture_mode == "replace" else None
    if style_mode not in {"", "brand", "fresh"} or (source_picture_mode == "replace" and source_picture is None):
        return Outcome(
            "The selected photo or style is unavailable. Choose a current photo from this workspace or clear it, then send the revision again.",
            action,
            Message.ActionStatus.DECLINED,
        )
    choices: dict[str, Any] = {
        "source_picture_mode": source_picture_mode,
        "source_picture": source_picture,
        "style_mode": style_mode,
        "allow_reopen": True,
    }
    try:
        if action == "new_angles":
            services.new_angles(brief, instructions, requested_by=requester, **choices)
        else:
            services.request_changes(
                brief,
                _FEEDBACK_LEAD.get(action, "") + instructions,
                new_picture=action == "new_picture",
                requested_by=requester,
                **choices,
            )
    except services.StudioActionError as exc:
        logger.info("Chat: revision of brief %s refused: %s", brief.pk, exc)
        return _locked(brief, action, speaker)
    effective_photo_action = (
        "clear" if source_picture_mode == "keep" and action == "new_picture" else source_picture_mode
    )
    details = {
        "keep": "The current photo choice is kept.",
        "clear": "The previous photo is cleared; the team will generate a new image or use the brand background.",
        "replace": "The team will use the photo you selected.",
    }
    queued_reply = "The revision is queued for the creative team. " + details[effective_photo_action]
    if style_mode:
        queued_reply += (
            " The layout will be fresh within the brand."
            if style_mode == "fresh"
            else " The brand look will be followed."
        )
    queued_reply += " The updated draft returns for human review before publishing."
    result: dict[str, Any] = {"brief_id": str(brief.pk), "queued": True}
    if allow_choices:
        result.update(
            photo_action=effective_photo_action,
            reference_id=str(brief.source_picture_id) if brief.source_picture_id else "none",
            style_mode="brand" if brief.style_lock else "fresh",
        )
    return Outcome(queued_reply, action, Message.ActionStatus.STARTED, result=result)


def _locked(brief: StudioBrief, action: str, speaker: str) -> Outcome:
    """The reply when the post can't be revised from here, saying why in the reader's terms."""
    if services.has_unconfirmed_delivery(brief):
        return Outcome(
            "The previous delivery record needs a human decision before the content, photo or account can change. "
            "Check an unknown outcome, or use Return for review after an expired publishing time.",
            action,
            Message.ActionStatus.NEEDS_HUMAN,
            notify_staff=True,
        )
    if "pending_client" in services.post_statuses(brief):
        if speaker == "client":
            # The client's own button does it (and records their decision); the thread can't.
            return Outcome(WAITING_FOR_YOU, action, Message.ActionStatus.DECLINED)
        return Outcome(WAITING_FOR_CLIENT, action, Message.ActionStatus.NEEDS_HUMAN, notify_staff=True)
    return Outcome(LOCKED, action, Message.ActionStatus.NEEDS_HUMAN, notify_staff=True)


def lead_for(workspace):
    """Whose name a draft asked for by a client carries: the agency lead, else the first owner or manager."""
    from apps.approvals.actor import is_internal_approver
    from apps.members.models import WorkspaceMembership

    row = AgencySettings.objects.filter(workspace=workspace).select_related("lead").first()
    if (
        row is not None
        and row.lead is not None
        and row.lead.is_active
        and is_internal_approver(row.lead, workspace)
        and chat.is_staff(row.lead, workspace)
    ):
        return row.lead
    for role in ("owner", "manager"):
        for membership in (
            WorkspaceMembership.objects.filter(workspace=workspace, workspace_role=role, user__is_active=True)
            .select_related("user", "custom_role")
            .order_by("added_at")
        ):
            perms = membership.effective_permissions
            if perms.get("create_posts") and perms.get("approve_posts"):
                return membership.user
    return None


def accounts_for(workspace) -> list:
    """Where a new post goes: the autopilot's accounts, else every account the studio can post to."""
    from ..forms import studio_accounts

    row = AgencySettings.objects.filter(workspace=workspace).first()
    accounts = [a for a in row.accounts.filter(workspace=workspace)] if row is not None else []
    accounts = [a for a in accounts if not a.needs_reconnect]
    if not accounts:
        accounts = [a for a in studio_accounts(workspace) if not a.needs_reconnect]
    return accounts


def _account_info(account) -> dict:
    return {
        "id": str(account.pk),
        "platform": account.platform,
        "name": account.account_name or account.account_handle or account.platform,
        "native_id": str(account.account_platform_id or ""),
        "handle": account.account_handle or "",
    }


def _account_label(account) -> str:
    return f"{account.platform}:{account.account_name or account.account_handle or account.pk} [{account.pk}]"


def _channel_choices(accounts) -> list[str]:
    counts: dict[str, int] = {}
    for account in accounts:
        counts[account.platform] = counts.get(account.platform, 0) + 1
    return [account.platform if counts[account.platform] == 1 else _account_label(account) for account in accounts]


def _selected_accounts(channels, accounts) -> tuple[list, str]:
    """Resolve only explicit, unique destinations in this workspace."""
    selected = []
    for channel in channels:
        value = channel.strip().casefold()
        candidates = [
            account
            for account in accounts
            if value
            in {
                str(account.pk).casefold(),
                account.platform.casefold(),
                _account_label(account).casefold(),
                (account.account_name or "").casefold(),
                (account.account_handle or "").casefold(),
            }
        ]
        if len(candidates) != 1:
            return (
                [],
                "Choose one exact connected account for each channel; unavailable or ambiguous channel choices cannot start a draft.",
            )
        if candidates[0] not in selected:
            selected.append(candidates[0])
    return selected, ""


def _collect_sources(workspace, profile, accounts) -> dict:
    sources = creative_sources.collect(workspace, profile, accounts)
    sources = (
        dict(sources)
        if isinstance(sources, dict)
        else {"notes": ["Source evidence is unavailable; supply and check current brand facts."]}
    )
    sources["creative_memory"] = memory.prompt_memory(workspace, platforms={a.platform for a in accounts})
    sources["available_accounts"] = [_account_info(account) for account in accounts]
    return sources


def _guided_context(job, conversation, trigger, requester, profile) -> dict:
    # Offer all currently connected Studio accounts, not only autopilot defaults.
    from ..forms import studio_accounts

    accounts = [account for account in studio_accounts(conversation.workspace) if not account.needs_reconnect]
    previous = creative_brief.latest_intake(conversation, requester, before=trigger.created_at)
    old = previous.result if previous is not None else {}
    reusable = bool(old.get("creative_brief")) and not (old.get("brief_id") or old.get("confirmed_from"))
    sources = old.get("sources") if reusable else None
    words = trigger.body.casefold()
    creative_request = reusable or any(
        word in words
        for word in (
            "post",
            "draft",
            "creative",
            "campaign",
            "image",
            "caption",
            "design",
            "social",
            "announce",
            "publish",
        )
    )
    if (not isinstance(sources, dict) or not sources) and creative_request:
        sources = _collect_sources(conversation.workspace, profile, accounts)
    return {
        "creative_brief": old.get("creative_brief", {}) if reusable else {},
        "sources": sources if isinstance(sources, dict) else {},
        "accounts": accounts,
        "profile": profile,
        "reference_id": (job.input or {}).get("reference_id", old.get("reference_id", "") if reusable else ""),
        "style_mode": (job.input or {}).get("style_mode", old.get("style_mode", "") if reusable else ""),
    }


def _reference(workspace, reference_id):
    from apps.media_library.models import MediaAsset

    if reference_id in {"", "none", None}:
        return None
    try:
        selected = uuid.UUID(str(reference_id))
    except (ValueError, TypeError, AttributeError):
        return None
    return MediaAsset.objects.filter(
        pk=selected,
        workspace=workspace,
        organization_id=workspace.organization_id,
        media_type=MediaAsset.MediaType.IMAGE,
    ).first()


def _intake(job, conversation, trigger, out, context) -> Outcome:
    proposed = creative_brief.normalized(out.creative_brief)
    previous = creative_brief.normalized(context["creative_brief"])
    new_topic = bool(previous["topic"] and proposed["topic"] and previous["topic"] != proposed["topic"])
    if new_topic:
        data = creative_brief.merge({}, proposed)
        context["sources"] = _collect_sources(conversation.workspace, context["profile"], context["accounts"])
        context["reference_id"] = (job.input or {}).get("reference_id", "")
        context["style_mode"] = (job.input or {}).get("style_mode", "")
    else:
        data = creative_brief.merge(previous, proposed)
    if not context["sources"]:
        context["sources"] = _collect_sources(conversation.workspace, context["profile"], context["accounts"])
    if not data["visual_direction"] and context["style_mode"] in {"brand", "fresh"}:
        data["visual_direction"] = (
            "Use a fresh layout within the brand's colours and typography."
            if context["style_mode"] == "fresh"
            else "Match the current brand series and its saved creative memory."
        )
    if not data["topic"] and out.action == "new_post":
        data["topic"] = ((out.instructions or "").strip() or trigger.body)[:1000]
    reference_id = context["reference_id"]
    reference = _reference(conversation.workspace, reference_id)
    reference_error = bool(reference_id not in {"", "none", None} and reference is None)
    if reference is not None:
        data["references"] = f"Use the selected reference: {reference.title or reference.filename}"[:1000]
    elif reference_id == "none":
        data["references"] = (
            "No uploaded reference selected; follow the confirmed visual direction and saved creative memory preference."
        )
    elif reference_error:
        data["references"] = ""
    selected, channel_error = _selected_accounts(data["channels"], context["accounts"])
    if channel_error:
        data["channels"] = []
    ready = not creative_brief.missing(data) and bool(selected) and not reference_error
    result = {
        "creative_brief": data,
        "sources": context["sources"],
        "awaiting_confirmation": ready,
        "reference_id": str(reference_id or ""),
        "style_mode": context["style_mode"] if context["style_mode"] in {"", "brand", "fresh"} else "",
        "selected_accounts": [_account_info(account) for account in selected],
    }
    if ready:
        names = "; ".join(f"{a.get_platform_display()}: {a.account_name or a.account_handle}" for a in selected)
        reply = (
            "Please check this brief and its source evidence before the team creates a draft.\n\n"
            + creative_brief.summary(data)
        )
        reply += f"\nSelected accounts: {names}.\nUse Confirm brief after checking the source facts. This only starts a draft for human approval."
        if (job.input or {}).get("telegram_context") is not None and trigger.author_kind == Message.AuthorKind.STAFF:
            reply = reply.replace(
                "Use Confirm brief after checking the source facts. This only starts a draft for human approval.",
                "Send /brief to open the current confirmation card after checking these source facts. Its explicit button only starts a draft for human approval.",
            )
    else:
        reply = creative_brief.questions(data, _channel_choices(context["accounts"]))
        if reference_error:
            reply += " The selected reference is unavailable; choose another image or no uploaded reference."
        if channel_error:
            reply += " " + channel_error
    return Outcome(reply, "new_post", result=result)


def _brief_notes(data, sources, *, style_mode="") -> str:
    # The full immutable evidence remains on the chat job. Put the person's
    # direction first so the downstream bounded prompt keeps the essentials.
    notes = [
        f"Audience: {data['audience']}",
        f"Key message: {data['key_message']}",
        f"Call to action: {data['call_to_action']}",
        f"Visual direction: {data['visual_direction']}",
        f"References: {data['references']}",
        f"Constraints: {data['constraints'] or 'None specified'}",
        f"Style choice: {style_mode or 'brand'}. The person checked this snapshot; it is not independent fact verification.",
    ]
    website = sources.get("website") or {}
    if isinstance(website, dict):
        excerpt = website.get("excerpt") or website.get("text") or ""
        notes.append(f"Website source ({website.get('status', 'unavailable')}): {str(excerpt)[:600]}")
    for channel in (sources.get("channels") or [])[:3]:
        if not isinstance(channel, dict):
            continue
        captions = [
            str(post.get("caption") or "")[:180] for post in (channel.get("posts") or [])[:2] if isinstance(post, dict)
        ]
        notes.append(
            f"Channel evidence ({channel.get('source', 'source snapshot')}; {channel.get('platform', '')}): {'; '.join(captions)}"
        )
    remembered = sources.get("creative_memory") or {}
    if isinstance(remembered, dict):
        notes.append("Saved creative memory, for visual craft only: " + str(remembered.get("house_style") or "")[:250])
        notes.extend(str(item)[:250] for item in (remembered.get("references") or [])[:3])
    return "\n".join(notes)[:12000]


def _source_expired(sources) -> bool:
    if not isinstance(sources, dict):
        return True
    try:
        fetched = parse_datetime(str(sources.get("fetched_at") or ""))
        if fetched is None or timezone.is_naive(fetched):
            return True
        age = timezone.now() - fetched
        return age < timedelta(0) or age > SOURCE_MAX_AGE
    except (ValueError, TypeError, OverflowError):
        return True


def _confirm(job, conversation, trigger, requester, membership) -> Outcome:
    denied = Outcome(
        "This brief cannot be confirmed from this message. Ask the team to show your current complete brief, then check its source facts and confirm it here.",
        "new_post",
        Message.ActionStatus.DECLINED,
    )
    telegram_guided = False
    context = (job.input or {}).get("telegram_context")
    if context is not None and (job.input or {}).get("explicit_assistant_request") is True:
        try:
            kind, _member = chat.telegram_author_kind(conversation, requester, context)
            telegram_guided = kind == Message.AuthorKind.STAFF
        except chat.ChatError:
            pass
    if (
        (conversation.audience != Conversation.Audience.INTERNAL and not telegram_guided)
        or not chat.is_staff_membership(membership)
        or not requester.is_active
        or trigger.author_kind != Message.AuthorKind.STAFF
        or trigger.author_id != requester.pk
        or trigger.is_internal
        or (job.input or {}).get("facts_confirmed") is not True
    ):
        return denied
    try:
        source_id = uuid.UUID(str((job.input or {}).get("confirmation_message_id") or ""))
    except (ValueError, TypeError, AttributeError):
        return denied
    # Read-only network work must not hold a conversation row lock. Its
    # candidate and membership are revalidated below before any result is used.
    candidate = (
        Message.objects.filter(
            pk=source_id,
            conversation=conversation,
            author_kind=Message.AuthorKind.AGENT,
            is_internal=False,
        )
        .select_related("job")
        .first()
    )
    refreshed = None
    if (
        candidate is not None
        and candidate.job is not None
        and candidate.job.workspace_id == job.workspace_id
        and candidate.job.requested_by_id == requester.pk
        and candidate.job.conversation_id == conversation.pk
        and candidate.job.status == AgencyJob.Status.DONE
        and (candidate.job.result or {}).get("awaiting_confirmation") is True
        and (candidate.job.result or {}).get("message_id") == str(candidate.pk)
        and _source_expired((candidate.job.result or {}).get("sources"))
    ):
        from ..forms import studio_accounts

        available = [a for a in studio_accounts(conversation.workspace) if not a.needs_reconnect]
        refreshed = _collect_sources(conversation.workspace, ensure_profile(conversation.workspace), available)
    with transaction.atomic():
        membership = _current_membership(job, conversation, requester)
        if (
            not chat.is_staff_membership(membership)
            or (conversation.audience != Conversation.Audience.INTERNAL and not telegram_guided)
            or not budget.can_spend(conversation.workspace)
        ):
            return denied
        existing = StudioBrief.objects.filter(
            workspace=conversation.workspace,
            origin=StudioBrief.Origin.CHAT,
            requested_by=requester,
            job__conversation=conversation,
            job__input__confirmation_message_id=str(source_id),
        ).first()
        if existing is not None:
            return Outcome(
                "This confirmed brief already has a draft. Open it here to review it; publishing still requires human approval.",
                "new_post",
                Message.ActionStatus.STARTED,
                result={"brief_id": str(existing.pk), "confirmed_from": str(source_id), "awaiting_confirmation": False},
            )
        source = (
            Message.objects.filter(
                pk=source_id,
                conversation=conversation,
                author_kind=Message.AuthorKind.AGENT,
                is_internal=False,
                created_at__lt=trigger.created_at,
            )
            .select_related("job")
            .first()
        )
        source_job = source.job if source is not None else None
        if (
            source is None
            or source_job is None
            or source_job.workspace_id != job.workspace_id
            or source_job.conversation_id != conversation.pk
            or source_job.requested_by_id != requester.pk
            or source_job.kind != AgencyJob.Kind.CHAT
            or source_job.status != AgencyJob.Status.DONE
            or (source_job.result or {}).get("awaiting_confirmation") is not True
            or (source_job.result or {}).get("message_id") != str(source.pk)
        ):
            return denied
        latest = creative_brief.latest_intake(conversation, requester, before=trigger.created_at)
        if latest is None or latest.pk != source_job.pk:
            return denied
        # A newer request can still be queued; do not confirm the old snapshot
        # while a delayed model turn is collecting the person's changes.
        prior_confirmation_ids = [
            row.get("message_id")
            for row in AgencyJob.objects.filter(
                workspace_id=job.workspace_id,
                conversation=conversation,
                requested_by=requester,
                kind=AgencyJob.Kind.CHAT,
                input__kind="confirm_brief",
                input__confirmation_message_id=str(source_id),
            ).values_list("input", flat=True)
            if isinstance(row, dict) and row.get("message_id")
        ]
        if (
            Message.objects.filter(
                conversation=conversation,
                author=requester,
                author_kind=Message.AuthorKind.STAFF,
                is_internal=False,
                created_at__gt=source.created_at,
                created_at__lt=trigger.created_at,
            )
            .exclude(pk__in=prior_confirmation_ids)
            .exists()
        ):
            return denied
        snapshot = source_job.result
        data = creative_brief.normalized(snapshot.get("creative_brief"))
        sources = snapshot.get("sources")
        if creative_brief.missing(data) or not isinstance(sources, dict):
            return denied
        from ..forms import studio_accounts

        accounts, error = _selected_accounts(
            data["channels"], [a for a in studio_accounts(conversation.workspace) if not a.needs_reconnect]
        )
        if not accounts or error:
            return denied
        stored_accounts = snapshot.get("selected_accounts")
        if not isinstance(stored_accounts, list) or {
            a["id"] for a in stored_accounts if isinstance(a, dict) and "id" in a
        } != {str(a.pk) for a in accounts}:
            return denied
        if {row["id"]: row for row in stored_accounts if isinstance(row, dict) and "id" in row} != {
            str(account.pk): _account_info(account) for account in accounts
        }:
            return denied
        reference_id = snapshot.get("reference_id") or ""
        reference = _reference(conversation.workspace, reference_id)
        if reference_id not in {"", "none"} and reference is None:
            return denied
        if (
            StudioBrief.objects.filter(
                workspace=conversation.workspace,
                origin=StudioBrief.Origin.CHAT,
                requested_by=requester,
                status__in=StudioBrief.ACTIVE_STATUSES,
            ).count()
            >= MAX_ACTIVE_CHAT_POSTS
        ):
            return Outcome(
                "The team is still making your previous drafts. Once one is ready, confirm this brief again.",
                "new_post",
                Message.ActionStatus.DECLINED,
            )
        style_mode = snapshot.get("style_mode") or ""
        if refreshed is not None:
            updated = {**snapshot, "sources": refreshed, "awaiting_confirmation": True}
            names = "; ".join(f"{a.get_platform_display()}: {a.account_name or a.account_handle}" for a in accounts)
            return Outcome(
                "The source snapshot was older than 30 minutes, so I refreshed it. Check the updated evidence and confirm this brief again before the team starts.\n\n"
                + creative_brief.summary(data)
                + f"\nSelected accounts: {names}.",
                "new_post",
                result=updated,
            )
        if _source_expired(sources):
            return denied
        _lock_current_job(job)
        brief = services.create_brief(
            conversation.workspace,
            requester,
            idea=data["topic"][:2000],
            goal=data["goal"],
            notes=_brief_notes(data, sources, style_mode=style_mode),
            accounts=accounts,
            style_lock=style_mode != "fresh",
            source_picture=reference,
            origin=StudioBrief.Origin.CHAT,
            job=job,
            requested_by=requester,
        )
        return Outcome(
            "The confirmed brief is with the creative team. Its draft will appear in this thread for review; a person must approve it before anything is scheduled or published.",
            "new_post",
            Message.ActionStatus.STARTED,
            result={
                **snapshot,
                "brief_id": str(brief.pk),
                "confirmed_from": str(source_id),
                "awaiting_confirmation": False,
            },
        )


def _new_post(job, workspace, requester, membership, idea: str, reply: str) -> Outcome:
    if chat.is_staff_membership(membership):
        author = requester
    elif chat.is_client_membership(membership):
        author = lead_for(workspace)
    else:
        return Outcome(NOT_ALLOWED, "new_post", Message.ActionStatus.NEEDS_HUMAN, notify_staff=True)
    if author is None:
        return Outcome(
            "I've passed your idea to the team — they'll pick it up and set it going. " + HANDOFF,
            "new_post",
            Message.ActionStatus.NEEDS_HUMAN,
            notify_staff=True,
        )
    accounts = accounts_for(workspace)
    if not accounts:
        return Outcome(
            "There's no connected account to make a post for yet, so I've asked a person on the team to sort that "
            "out first. " + HANDOFF,
            "new_post",
            Message.ActionStatus.NEEDS_HUMAN,
            notify_staff=True,
        )
    # One message, one post, and only a couple in the works per person: a thread
    # can't fan out into a run of paid pipelines.
    in_progress = StudioBrief.objects.filter(
        workspace=workspace,
        origin=StudioBrief.Origin.CHAT,
        requested_by=requester,
        status__in=StudioBrief.ACTIVE_STATUSES,
    ).count()
    if in_progress >= MAX_ACTIVE_CHAT_POSTS:
        return Outcome(
            "The team is still making the last post you asked for. Once it's ready for review, ask again and "
            "I'll start this one.",
            "new_post",
            Message.ActionStatus.DECLINED,
        )
    brief = services.create_brief(
        workspace,
        author,
        idea=idea[:2000],
        accounts=accounts,
        origin=StudioBrief.Origin.CHAT,
        job=job,
        requested_by=requester,
    )
    return Outcome(reply, "new_post", Message.ActionStatus.STARTED, result={"brief_id": str(brief.pk)})


def _edit_blog(job, workspace, blog_post, requester, instructions: str, reply: str) -> Outcome:
    from apps.blog import services as blog_services
    from apps.blog.views_team import REVISABLE

    if blog_post is None:
        return Outcome(NOT_ALLOWED, "edit_blog", Message.ActionStatus.NEEDS_HUMAN, notify_staff=True)
    # The same rules as the article page's own "Ask the SEO team": the person may edit
    # this article, and it is still the team's to change (not approved or live).
    if blog_post.status not in REVISABLE:
        return Outcome(ARTICLE_LOCKED, "edit_blog", Message.ActionStatus.NEEDS_HUMAN, notify_staff=True)
    if not blog_services.can_edit(requester, blog_post):
        return Outcome(NOT_ALLOWED, "edit_blog", Message.ActionStatus.NEEDS_HUMAN, notify_staff=True)
    busy = AgencyJob.objects.filter(
        workspace=workspace, kind=AgencyJob.Kind.BLOG, blog_post=blog_post, status__in=AgencyJob.ACTIVE_STATUSES
    ).exists()
    if busy:
        return Outcome(
            "The writers are already working on this article. Once their version is in, tell me what to change "
            "and I'll pass it on.",
            "edit_blog",
            Message.ActionStatus.DECLINED,
        )
    blog_job = engine.create(
        workspace,
        AgencyJob.Kind.BLOG,
        title=f"Revise “{blog_post.title}”"[:200],
        input={"revision_of": str(blog_post.pk), "feedback": instructions[:4000]},
        requested_by=requester,
        parent=job,
        blog_post=blog_post,
    )
    return Outcome(reply, "edit_blog", Message.ActionStatus.STARTED, result={"blog_job_id": str(blog_job.pk)})
