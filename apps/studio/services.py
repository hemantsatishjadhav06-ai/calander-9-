"""What people can do with a brief, and the rules for when they may.

Views call these; the agents never do. Approving goes through
``apps.approvals.services`` and scheduling through
``apps.composer.services.transition_platform_post`` — the same code the
Approvals page and the composer use — so the approval gate, the audit trail
and the notifications behave exactly as they do everywhere else.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from . import pipeline
from .models import StudioBrief, StudioConcept

logger = logging.getLogger(__name__)

#: Composer statuses after which the brief counts as approved.
_APPROVED_STATUSES = frozenset({"approved", "pending_client", "scheduled", "publishing", "published", "on_hold"})


class StudioActionError(Exception):
    """A person's action can't be done right now. The message is for them."""


def post_statuses(brief: StudioBrief) -> set[str]:
    post = brief.post if brief.post_id else None
    if post is None:
        return set()
    return set(post.platform_posts.values_list("status", flat=True))


def sync_status(brief: StudioBrief) -> StudioBrief:
    """Mark a ready brief approved once its post was approved anywhere (here or on the Approvals page)."""
    if brief.status == StudioBrief.Status.READY and post_statuses(brief) & _APPROVED_STATUSES:
        brief.status = StudioBrief.Status.APPROVED
        brief.save(update_fields=["status", "updated_at"])
    return brief


def can_revise(brief: StudioBrief) -> bool:
    if brief.status not in (StudioBrief.Status.READY, StudioBrief.Status.FAILED):
        return False
    return post_statuses(brief) <= pipeline.REVISABLE_STATUSES


def create_brief(
    workspace,
    author,
    *,
    idea,
    notes="",
    goal="",
    accounts=(),
    style_lock=True,
    source_picture=None,
    proposed_publish_at=None,
    origin=StudioBrief.Origin.MANUAL,
    job=None,
    requested_by=None,
    start=True,
):
    """Create a brief and put the team to work on it.

    With ``start=False`` the brief is PLANNED instead: it waits, outside the
    team's active work, until :func:`start_planned` hands it over (autopilot
    feeds a week of briefs a few at a time so the single worker keeps
    publishing on time and nothing looks stuck). ``proposed_publish_at`` is the
    time the plan reserved for it; the scheduler keeps it if it is still ahead.
    """
    with transaction.atomic():
        brief = StudioBrief.objects.create(
            workspace=workspace,
            author=author,
            idea=idea.strip(),
            notes=(notes or "").strip(),
            goal=goal or "",
            style_lock=style_lock,
            source_picture=source_picture,
            regenerate_picture=True,
            proposed_publish_at=proposed_publish_at,
            origin=origin,
            job=job,
            requested_by=requested_by,
            status=StudioBrief.Status.QUEUED if start else StudioBrief.Status.PLANNED,
        )
        brief.social_accounts.set(accounts)
        if start:
            pipeline.start(brief, "strategy")
    return brief


def start_planned(brief: StudioBrief) -> bool:
    """Hand a PLANNED brief to the team. False when it was already started or dropped."""
    with transaction.atomic():
        updated = StudioBrief.objects.filter(pk=brief.pk, status=StudioBrief.Status.PLANNED).update(
            status=StudioBrief.Status.QUEUED, stage="strategy", updated_at=timezone.now()
        )
        if updated:
            brief.refresh_from_db()
            pipeline.enqueue(brief, "strategy")
    return bool(updated)


def _new_revision(brief: StudioBrief, **changes) -> None:
    brief.revision += 1
    brief.auto_revisions = 0
    brief.review_notes = {}
    brief.error = ""
    for name, value in changes.items():
        setattr(brief, name, value)
    brief.save()


def request_changes(brief: StudioBrief, feedback: str, *, new_picture: bool = False) -> None:
    feedback = (feedback or "").strip()
    if not feedback:
        raise StudioActionError("Say what should change, so the team knows what to do.")
    if not can_revise(brief):
        raise StudioActionError("This post can't be revised now — it is in progress, approved or already out.")
    with transaction.atomic():
        _new_revision(brief, feedback=feedback[:4000], regenerate_picture=new_picture)
        pipeline.start(brief, "copy")


def new_angles(brief: StudioBrief, feedback: str = "") -> None:
    if not can_revise(brief):
        raise StudioActionError("This post can't be revised now — it is in progress, approved or already out.")
    with transaction.atomic():
        _new_revision(brief, feedback=(feedback or "").strip()[:4000], chosen_concept=None, regenerate_picture=True)
        pipeline.start(brief, "strategy")


def use_concept(brief: StudioBrief, concept: StudioConcept) -> None:
    if concept.brief_id != brief.pk:
        raise StudioActionError("That angle belongs to another brief.")
    if not can_revise(brief):
        raise StudioActionError("This post can't be revised now — it is in progress, approved or already out.")
    with transaction.atomic():
        _new_revision(brief, feedback="", chosen_concept=concept, regenerate_picture=True)
        pipeline.start(brief, "copy")


def retry(brief: StudioBrief) -> None:
    if brief.status != StudioBrief.Status.FAILED:
        raise StudioActionError("Only a brief that failed can be retried.")
    stage = brief.stage if brief.stage in pipeline.STAGES else "strategy"
    with transaction.atomic():
        pipeline.start(brief, stage)


def discard(brief: StudioBrief) -> None:
    """Stop the team and drop the draft — unless the post was already approved or sent."""
    statuses = post_statuses(brief)
    if statuses & _APPROVED_STATUSES:
        raise StudioActionError("This post was approved, so it can't be discarded here. Manage it in the composer.")
    with transaction.atomic():
        if brief.post is not None:
            brief.post.delete()
        brief.status = StudioBrief.Status.DISCARDED
        brief.post = None
        brief.save(update_fields=["status", "post", "updated_at"])


def approve(brief: StudioBrief, user, *, publish_now: bool = False, publish_at=None) -> str:
    """Approve the brief's post as ``user`` and, if asked, schedule or publish it.

    Returns a sentence for the person. Raises :class:`StudioActionError`.
    """
    from apps.approvals import gate
    from apps.approvals import services as approval_services
    from apps.approvals.actor import dashboard_approver, is_internal_approver
    from apps.composer.services import transition_platform_post

    post = brief.post
    if brief.status != StudioBrief.Status.READY or post is None:
        raise StudioActionError("There is nothing ready to approve.")
    workspace = brief.workspace
    if publish_at is not None and publish_at <= timezone.now():
        raise StudioActionError("Pick a time in the future, or use Publish now.")
    try:
        moved = approval_services.approve_post(post, user, workspace, comment="Approved in the AI Studio.")
    except ValueError as exc:
        raise StudioActionError(str(exc)) from exc
    if not moved:
        if gate.enforced(workspace) and (
            not is_internal_approver(user, workspace) or dashboard_approver(workspace) is None
        ):
            raise StudioActionError(
                "This workspace needs an internal approver (an owner or manager) signed in to the dashboard to approve."
            )
        raise StudioActionError("Nothing was approved — the post may already have been actioned.")

    brief.status = StudioBrief.Status.APPROVED
    brief.save(update_fields=["status", "updated_at"])
    if post.platform_posts.filter(status="pending_client").exists():
        return "Approved, and sent to the client for sign-off."
    if not (publish_now or publish_at):
        return "Approved. Schedule it from the calendar or the composer when you're ready."

    when = timezone.now() if publish_now else publish_at
    scheduled, problems = 0, []
    for pp in post.platform_posts.select_related("post__workspace", "social_account").filter(status="approved"):
        try:
            transition_platform_post(pp, "scheduled", scheduled_at=when)
            scheduled += 1
        except ValueError as exc:
            problems.append(f"{pp.social_account.account_name}: {exc}")
    if problems and not scheduled:
        raise StudioActionError("Approved, but it couldn't be scheduled: " + "; ".join(problems))
    if publish_now:
        message = f"Approved and publishing now to {scheduled} account(s) — it goes out within a minute."
    else:
        local = timezone.localtime(when)
        message = f"Approved and scheduled for {local:%a %d %b, %H:%M} on {scheduled} account(s)."
    if problems:
        message += " Not scheduled: " + "; ".join(problems)
    return message


def save_concept_as_idea(concept: StudioConcept, user):
    """Keep an angle the team didn't use on the workspace's idea board."""
    from apps.composer.models import Idea

    if concept.saved_idea_id:
        return concept.saved_idea
    points = "\n".join(f"• {point}" for point in concept.key_points or [])
    description = f"{concept.hook}\n\n{concept.angle}\n\n{points}".strip()
    idea = Idea.objects.create(
        workspace=concept.brief.workspace,
        author=user,
        title=concept.title[:255],
        description=description,
        tags=["ai-studio"],
        status=Idea.Status.TODO,
    )
    concept.saved_idea = idea
    concept.save(update_fields=["saved_idea"])
    return idea
