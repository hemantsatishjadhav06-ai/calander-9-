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
import zoneinfo
from dataclasses import dataclass, field
from typing import Any

from .. import budget, chat, engine, services
from ..brand_defaults import ensure_profile
from ..models import AgencyJob, AgencySettings, Conversation, Message, StudioBrief
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


@dataclass
class Outcome:
    reply: str
    action: str
    status: str = ""
    notify_staff: bool = False
    result: dict[str, Any] = field(default_factory=dict)


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
    target = resolve_target(conversation)
    allowed = allowed_actions(membership, conversation, target)
    profile = ensure_profile(workspace)

    run, result = engine.call(
        job,
        "account_manager",
        lambda: client_roles.account_manager(
            profile,
            audience=conversation.audience,
            speaker=speaker,
            history=history(conversation, trigger, for_client=for_client),
            item=describe(target, workspace, for_client=for_client),
            request=trigger.body,
            request_kind=str((job.input or {}).get("kind") or ""),
            allowed_actions=list(allowed),
        ),
        effort=client_roles.ACCOUNT_MANAGER_EFFORT,
    )
    out = result.output
    try:
        outcome = perform(job, conversation, target, requester, membership, out, allowed, trigger, speaker=speaker)
    except engine.StaleJobError:
        raise
    except Exception:
        logger.exception("Chat job %s: acting on %s failed", job.pk, out.action)
        outcome = Outcome(
            reply="Something went wrong passing this on, so I've asked a person on the team to pick it up. " + HANDOFF,
            action=out.action,
            status=Message.ActionStatus.NEEDS_HUMAN,
            notify_staff=True,
        )

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
    engine.finish(
        job, result={"action": outcome.action, "status": outcome.status, "message_id": str(reply.pk), **outcome.result}
    )
    return None


JOB = engine.JobType(
    kind="chat",
    stages=(engine.Stage("answer", "account_manager", answer),),
    priority=engine.PRIORITY_CHAT,
)


# ---------------------------------------------------------------------------
# What the thread is about, and what may be done
# ---------------------------------------------------------------------------


def resolve_target(conversation: Conversation) -> Target:
    """The thread's item, re-checked against the workspace (targets never come from the model)."""
    workspace_id = conversation.workspace_id

    def own(item):
        return item if item is not None and item.workspace_id == workspace_id else None

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
    if target.brief is not None:
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
    job, conversation, target: Target, requester, membership, out, allowed, trigger, *, speaker="staff"
) -> Outcome:
    """Validate the account manager's action against what this person may ask for here, and do it."""
    action = out.action
    reply = (out.reply or "").strip()
    instructions = (out.instructions or "").strip() or trigger.body
    if action not in allowed:
        return Outcome(NOT_ALLOWED, action, Message.ActionStatus.NEEDS_HUMAN, notify_staff=True)
    if action == "answer":
        if out.needs_human:
            return Outcome(_with_handoff(reply), action, Message.ActionStatus.NEEDS_HUMAN, notify_staff=True)
        return Outcome(reply, action)
    if action == "escalate":
        return Outcome(_with_handoff(reply), action, Message.ActionStatus.NEEDS_HUMAN, notify_staff=True)
    if action in REVISION_ACTIONS:
        outcome = _revise(target.brief, action, instructions, reply, speaker=speaker)
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
    brief: StudioBrief | None, action: str, instructions: str, reply: str, *, speaker: str = "staff"
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
    if not services.reopen(brief):
        return _locked(brief, action, speaker)
    try:
        if action == "new_angles":
            services.new_angles(brief, instructions)
        else:
            services.request_changes(
                brief, _FEEDBACK_LEAD.get(action, "") + instructions, new_picture=action == "new_picture"
            )
    except services.StudioActionError as exc:
        logger.info("Chat: revision of brief %s refused: %s", brief.pk, exc)
        return _locked(brief, action, speaker)
    return Outcome(reply, action, Message.ActionStatus.STARTED, result={"brief_id": str(brief.pk)})


def _locked(brief: StudioBrief, action: str, speaker: str) -> Outcome:
    """The reply when the post can't be revised from here, saying why in the reader's terms."""
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
    if blog_post is None:
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
