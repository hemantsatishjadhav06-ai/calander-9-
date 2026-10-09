"""The ``inbox`` job: reply drafts for comments, messages and reviews — for a person to send.

Two stages, each one agent's turn (skipped when it has nothing to do):

1. ``community`` — the community manager drafts replies to comments,
   mentions and direct messages;
2. ``reviews`` — the reviews manager drafts replies to reviews and flags the
   unhappy ones (one or two stars, anger, anything someone must fix), and the
   people who look after the inbox are told.

The messages come from the job's input (``inbox_team.queue``), re-read from
the database and re-checked against the workspace; each one the model sees
gets a short reference, and a draft can only land on a message by that
reference. A message that has picked up a reply in the meantime (a person's,
or this job's on an earlier attempt) is left alone, so a retry never
duplicates a draft. Drafts are created with ``apps.inbox.services.create_reply_draft``
and marked with the agent's slug; nothing here sends a reply.
"""

from __future__ import annotations

import logging
from typing import Any

from django.urls import reverse
from django.utils import timezone
from django.utils.timesince import timesince

from .. import budget, engine
from ..brand_defaults import ensure_profile
from ..models import AgencyJob
from ..roles import publishing

logger = logging.getLogger(__name__)

MAX_REPLY = 2000
_STARS = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}


def _messages(job: AgencyJob, kinds) -> list:
    from apps.inbox.models import InboxMessage

    ids = [str(i) for i in (job.input or {}).get("message_ids", []) or []]
    if not ids:
        return []
    return list(
        InboxMessage.objects.filter(workspace_id=job.workspace_id, pk__in=ids, message_type__in=kinds)
        .filter(replies__isnull=True)
        .select_related("social_account", "related_post__post")
        .order_by("received_at")
        .distinct()
    )


def rating(message) -> int | None:
    """A review's star rating from the provider's extra data, when known."""
    extra = message.extra or {}
    value = extra.get("star_rating", extra.get("rating", extra.get("starRating")))
    if isinstance(value, str):
        value = _STARS.get(value.strip().upper(), value)
    if value is None:
        return None
    try:
        stars = int(value)
    except (TypeError, ValueError):
        return None
    return stars if 1 <= stars <= 5 else None


def _item(ref: str, message) -> dict[str, Any]:
    account = message.social_account
    caption = ""
    if message.related_post_id and message.related_post is not None:
        pp = message.related_post
        caption = pp.platform_specific_caption or (pp.post.caption if pp.post_id else "")
    return {
        "ref": ref,
        "kind": message.get_message_type_display().lower(),
        "platform": account.get_platform_display(),
        "sender": message.sender_name,
        "body": message.body,
        "age": f"{timesince(message.received_at, timezone.now()).split(',')[0]} ago",
        "post_caption": caption,
        "rating": rating(message),
    }


def _save_draft(message, body: str, agent: str):
    from apps.inbox.models import InboxReply
    from apps.inbox.services import create_reply_draft

    if message.replies.exists():
        return None
    draft = create_reply_draft(message=message, body=body[:MAX_REPLY], author=None)
    InboxReply.objects.filter(pk=draft.pk).update(drafted_by=agent)
    draft.drafted_by = agent
    return draft


def _inbox_people(workspace) -> list:
    """Who looks after the inbox here: members with inbox access who are not plain clients."""
    from apps.members.models import WorkspaceMembership

    people = []
    for membership in WorkspaceMembership.objects.filter(workspace=workspace).select_related("user", "custom_role"):
        if not membership.user.is_active:
            continue
        if membership.workspace_role == "client" and membership.custom_role_id is None:
            continue
        if membership.effective_permissions.get("use_inbox"):
            people.append(membership.user)
    return people


def _flag(job: AgencyJob, flagged: list[tuple[Any, str]], *, what: str) -> None:
    """Tell the inbox's people, once per job, about messages a person should handle first."""
    from apps.notifications.engine import notify
    from apps.notifications.models import EventType

    if not flagged:
        return
    first, reason = flagged[0]
    if len(flagged) == 1:
        title = f"A {what} needs a person: {first.sender_name}"[:255]
        path = reverse("inbox:message_detail", kwargs={"workspace_id": job.workspace_id, "message_id": first.pk})
        body = f"{reason or 'Flagged by the team.'} A draft reply is waiting for you to check — nothing was sent."
    else:
        title = f"{len(flagged)} {what}s need a person"
        path = reverse("inbox:feed", kwargs={"workspace_id": job.workspace_id})
        body = "The team drafted replies and flagged these for you to handle first. Nothing was sent."
    from ..chat import absolute_url

    for user in _inbox_people(job.workspace):
        try:
            notify(
                user=user,
                event_type=EventType.ENGAGEMENT_ALERT,
                title=title,
                body=body[:500],
                data={"workspace_id": str(job.workspace_id), "action_url": absolute_url(path), "job_id": str(job.pk)},
            )
        except Exception:
            logger.exception("Inbox job %s: could not notify %s", job.pk, user.pk)


def _draft(job: AgencyJob, *, agent: str, kinds, ask, effort: str, what: str, urgent_field: str) -> dict[str, Any]:
    """One agent's turn over the messages of ``kinds``: drafts saved, flags raised. Returns counts."""
    messages = _messages(job, kinds)
    if not messages:
        return {"drafted": 0, "skipped": 0, "flagged": 0}
    if not budget.can_spend(job.workspace):
        return {"drafted": 0, "skipped": len(messages), "flagged": 0, "over_budget": True}
    by_ref = {f"m{index}": message for index, message in enumerate(messages, start=1)}
    items = [_item(ref, message) for ref, message in by_ref.items()]
    profile = ensure_profile(job.workspace)
    run, result = engine.call(job, agent, lambda: ask(profile, items), effort=effort)
    drafted, skipped, flagged = [], [], []
    seen = set()
    for answer in result.output.replies:
        message = by_ref.get(answer.ref.strip())
        if message is None or answer.ref in seen:
            continue  # a reference we didn't give, or a second answer to the same one
        seen.add(answer.ref)
        urgent = bool(getattr(answer, urgent_field))
        stars = rating(message)
        if stars is not None and stars <= 2:
            urgent = True
        if urgent:
            flagged.append((message, answer.reason))
        text = (answer.reply or "").strip()
        if answer.skip or not text:
            skipped.append(str(message.pk))
            continue
        if _save_draft(message, text, agent) is not None:
            drafted.append(str(message.pk))
    engine.end(
        run,
        summary=(
            f"Drafted {len(drafted)} repl{'y' if len(drafted) == 1 else 'ies'}"
            + (f", skipped {len(skipped)}" if skipped else "")
            + (f", flagged {len(flagged)} for a person" if flagged else "")
            + f". {result.output.notes}".rstrip(". ")
            + "."
        ),
        # Ids and counts only: message text is the public's, and stays in the inbox.
        output={"drafted": drafted, "skipped": skipped, "flagged": [str(m.pk) for m, _r in flagged]},
        result=result,
    )
    _flag(job, flagged, what=what)
    return {"drafted": len(drafted), "skipped": len(skipped), "flagged": len(flagged)}


def community(job: AgencyJob) -> str:
    from apps.inbox.models import InboxMessage

    types = InboxMessage.MessageType
    counts = _draft(
        job,
        agent="community_manager",
        kinds=(types.COMMENT, types.MENTION, types.DM),
        ask=publishing.community_manager,
        effort=publishing.COMMUNITY_MANAGER_EFFORT,
        what="message",
        urgent_field="needs_person",
    )
    engine.update_state(job, community=counts)
    return "reviews"


def reviews(job: AgencyJob) -> None:
    from apps.inbox.models import InboxMessage

    counts = _draft(
        job,
        agent="reputation_manager",
        kinds=(InboxMessage.MessageType.REVIEW,),
        ask=publishing.reputation_manager,
        effort=publishing.REPUTATION_MANAGER_EFFORT,
        what="review",
        urgent_field="urgent",
    )
    community_counts = (job.state or {}).get("community", {})
    engine.finish(job, result={"community": community_counts, "reviews": counts})
    return None


JOB = engine.JobType(
    kind="inbox",
    stages=(
        engine.Stage("community", "community_manager", community),
        engine.Stage("reviews", "reputation_manager", reviews),
    ),
    priority=engine.PRIORITY_DEFAULT,
)
