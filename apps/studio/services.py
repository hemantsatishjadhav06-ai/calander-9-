"""What people can do with a brief, and the rules for when they may.

Views call these; the agents never do. Approving goes through
``apps.approvals.services`` and scheduling through
``apps.composer.services.transition_platform_post`` — the same code the
Approvals page and the composer use — so the approval gate, the audit trail
and the notifications behave exactly as they do everywhere else.
"""

from __future__ import annotations

import logging
import zoneinfo
from typing import Any

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
    if has_unconfirmed_delivery(brief):
        return False
    return post_statuses(brief) <= pipeline.REVISABLE_STATUSES


def has_unconfirmed_delivery(brief: StudioBrief) -> bool:
    """Unknown outcomes and expired approvals retain their recovery evidence."""
    if brief.post_id is None:
        return False
    from apps.composer.models import PlatformPost, Post
    from apps.publisher import delivery

    post = Post.objects.filter(pk=brief.post_id, workspace_id=brief.workspace_id).first()
    if post is None:
        return True
    if delivery.has_unresolved_holds(post):
        return True
    rows = PlatformPost.objects.filter(post=post).select_related("post__workspace", "social_account")
    return any(delivery.state(row).get("kind") in delivery.UNRESOLVED for row in rows)


def reopen(brief: StudioBrief) -> bool:
    """Make an approved brief revisable again once its post is back in the team's hands.

    A brief counts as approved as soon as its post reaches the client stage
    (:func:`sync_status`). When the client then asks for a change in the
    portal, every channel goes back to ``changes_requested``, and the team
    should be able to revise the post — so the brief returns to READY. Only
    when every channel is in a revisable status (draft, pending review,
    changes requested, rejected); an approved, scheduled or published channel
    keeps it closed, and a person must put the post on hold first. True when
    the brief can now be revised.
    """
    if has_unconfirmed_delivery(brief):
        return False
    if brief.status != StudioBrief.Status.APPROVED:
        return can_revise(brief)
    statuses = post_statuses(brief)
    if not statuses or not statuses <= pipeline.REVISABLE_STATUSES:
        return False
    updated = StudioBrief.objects.filter(pk=brief.pk, status=StudioBrief.Status.APPROVED).update(
        status=StudioBrief.Status.READY, updated_at=timezone.now()
    )
    if updated:
        brief.status = StudioBrief.Status.READY
    else:
        brief.refresh_from_db(fields=["status"])
    return can_revise(brief)


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
        from . import trust

        brief.trust_snapshot = trust.capture(brief)
        brief.save(update_fields=["trust_snapshot", "updated_at"])
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
    from . import trust

    brief.trust_snapshot = trust.capture(brief)
    brief.save()


def _revision_context(
    brief: StudioBrief, requested_by, *, staff_only: bool = False, allow_reopen: bool = False
) -> StudioBrief:
    """Recheck current access, then lock the fresh creative and channel rows."""
    from apps.accounts.models import User
    from apps.approvals.actor import current_actor
    from apps.composer.models import PlatformPost, Post
    from apps.members.models import CustomRole, WorkspaceMembership
    from apps.workspaces.models import Workspace

    from . import chat

    workspace = Workspace.objects.select_for_update().filter(pk=brief.workspace_id, is_archived=False).first()
    if workspace is None:
        raise StudioActionError("This workspace is unavailable for revisions.")
    person_requesting = requested_by if requested_by is not None else current_actor().user
    if person_requesting is not None:
        person = User.objects.select_for_update().filter(pk=person_requesting.pk, is_active=True).first()
        membership = (
            WorkspaceMembership.objects.select_for_update().filter(workspace=workspace, user=person).first()
            if person is not None
            else None
        )
        if membership is not None and membership.custom_role_id:
            membership.custom_role = CustomRole.objects.select_for_update().get(pk=membership.custom_role_id)
        allowed = chat.is_staff_membership(membership) or (not staff_only and chat.is_client_membership(membership))
        if not allowed:
            raise StudioActionError("Your current workspace permissions do not allow this revision.")
    current = (
        StudioBrief.objects.select_for_update(of=("self",))
        .select_related("workspace")
        .filter(pk=brief.pk, workspace=workspace)
        .first()
    )
    if current is None:
        raise StudioActionError("This draft is unavailable for revisions.")
    if current.post_id:
        post = Post.objects.select_for_update().filter(pk=current.post_id, workspace=workspace).first()
        if post is None:
            raise StudioActionError("This draft's post is unavailable in this workspace.")
        list(PlatformPost.objects.select_for_update().filter(post=post).order_by("pk"))
        current.post = post
    if allow_reopen:
        reopen(current)
    if not can_revise(current):
        if has_unconfirmed_delivery(current):
            raise StudioActionError(
                "Resolve the previous delivery record before changing this post or its photo. "
                "Check an unknown outcome, or use Return for review after an expired publishing time."
            )
        raise StudioActionError("This post can't be revised now — it is in progress, approved or already out.")
    return current


def _revision_choices(
    brief: StudioBrief,
    *,
    source_picture_mode: str = "keep",
    source_picture=None,
    style_mode: str = "",
    new_picture: bool = False,
    regenerate_picture: bool = False,
) -> dict[str, Any]:
    """Apply explicit keep/clear/replace choices before any creative work."""
    from apps.media_library.models import MediaAsset

    if source_picture_mode not in {"keep", "clear", "replace"} or style_mode not in {"", "brand", "fresh"}:
        raise StudioActionError("Choose whether to keep, clear or replace the photo, and choose a supported look.")
    if source_picture_mode != "replace" and source_picture is not None:
        raise StudioActionError("Choose Replace photo when supplying a new photo.")
    # A human's replacement wins over the account manager's generation action.
    # Otherwise an explicit new-picture request must not reuse a supplied photo.
    if source_picture_mode == "keep" and new_picture:
        source_picture_mode = "clear"
    changes: dict[str, Any] = {"regenerate_picture": regenerate_picture}
    if source_picture_mode == "replace" or (source_picture_mode == "keep" and brief.source_picture_id):
        selected = getattr(source_picture, "pk", None) if source_picture_mode == "replace" else brief.source_picture_id
        if selected is None:
            raise StudioActionError("Choose an available photo from this workspace's media library.")
        asset = (
            MediaAsset.objects.select_for_update()
            .filter(
                pk=selected,
                workspace_id=brief.workspace_id,
                organization_id=brief.workspace.organization_id,
                media_type=MediaAsset.MediaType.IMAGE,
            )
            .first()
        )
        if asset is None:
            raise StudioActionError("Choose an available photo from this workspace's media library.")
        if source_picture_mode == "replace":
            changes.update(source_picture=asset, picture=None, regenerate_picture=False)
    elif source_picture_mode == "clear":
        changes.update(source_picture=None, picture=None, regenerate_picture=True)
    if style_mode:
        changes["style_lock"] = style_mode == "brand"
    return changes


def _withdraw_revision_review(brief: StudioBrief, feedback: str, requested_by) -> None:
    """Take the old draft out of review while its replacement is being prepared."""
    if brief.post_id is None:
        return
    from apps.approvals import services as approval_services
    from apps.approvals.actor import current_actor
    from apps.composer.models import PlatformPost

    # The normal transition records the human's change request and prevents
    # the old pending-review version being approved while the team revises it.
    actor = requested_by or current_actor().user or brief.author
    approval_services.request_changes(brief.post, actor, brief.workspace, comment=feedback)
    PlatformPost.objects.filter(post_id=brief.post_id).update(
        approved_fingerprint="",
        approved_revision=None,
        approved_by=None,
        approved_at=None,
        approved_publish_at=None,
        updated_at=timezone.now(),
    )


def request_changes(
    brief: StudioBrief,
    feedback: str,
    *,
    new_picture: bool = False,
    requested_by=None,
    source_picture_mode: str = "keep",
    source_picture=None,
    style_mode: str = "",
    allow_reopen: bool = False,
) -> None:
    """Send the post back with notes. ``requested_by`` is set when the notes came through the team thread
    (a client's words, or the account manager's relay of them): the agents then read them as untrusted."""
    feedback = (feedback or "").strip()
    if not feedback:
        raise StudioActionError("Say what should change, so the team knows what to do.")
    extra = {"requested_by": requested_by} if requested_by is not None else {}
    with transaction.atomic():
        current = _revision_context(
            brief,
            requested_by,
            staff_only=source_picture_mode != "keep" or bool(style_mode),
            allow_reopen=allow_reopen,
        )
        choices = _revision_choices(
            current,
            source_picture_mode=source_picture_mode,
            source_picture=source_picture,
            style_mode=style_mode,
            new_picture=new_picture,
            regenerate_picture=new_picture,
        )
        _withdraw_revision_review(current, feedback, requested_by)
        _new_revision(current, feedback=feedback[:4000], **choices, **extra)
        pipeline.start(current, "copy")
        brief.refresh_from_db()


def new_angles(
    brief: StudioBrief,
    feedback: str = "",
    *,
    requested_by=None,
    source_picture_mode: str = "keep",
    source_picture=None,
    style_mode: str = "",
    allow_reopen: bool = False,
) -> None:
    extra = {"requested_by": requested_by} if requested_by is not None else {}
    with transaction.atomic():
        current = _revision_context(
            brief,
            requested_by,
            staff_only=source_picture_mode != "keep" or bool(style_mode),
            allow_reopen=allow_reopen,
        )
        choices = _revision_choices(
            current,
            source_picture_mode=source_picture_mode,
            source_picture=source_picture,
            style_mode=style_mode,
            regenerate_picture=True,
        )
        _withdraw_revision_review(current, (feedback or "").strip() or "Try new creative angles.", requested_by)
        _new_revision(current, feedback=(feedback or "").strip()[:4000], chosen_concept=None, **choices, **extra)
        pipeline.start(current, "strategy")
        brief.refresh_from_db()


def use_concept(brief: StudioBrief, concept: StudioConcept) -> None:
    if concept.brief_id != brief.pk:
        raise StudioActionError("That angle belongs to another brief.")
    with transaction.atomic():
        current = _revision_context(brief, None)
        choices = _revision_choices(current, regenerate_picture=True)
        _withdraw_revision_review(current, "Use the selected creative angle.", None)
        _new_revision(current, feedback="", chosen_concept=concept, **choices)
        pipeline.start(current, "copy")
        brief.refresh_from_db()


def retry(brief: StudioBrief) -> None:
    with transaction.atomic():
        current = StudioBrief.objects.select_for_update().get(pk=brief.pk, workspace_id=brief.workspace_id)
        if current.status != StudioBrief.Status.FAILED:
            raise StudioActionError("Only a brief that failed can be retried.")
        if has_unconfirmed_delivery(current):
            raise StudioActionError("Resolve the previous delivery record before retrying this brief.")
        if post_statuses(current) & _APPROVED_STATUSES:
            raise StudioActionError("This post was approved, so the team cannot retry its creative work.")
        stage = current.stage if current.stage in pipeline.STAGES else "strategy"
        # An interrupted paid call can still finish after the person retries.
        # Give the new execution a different revision so that old callbacks
        # cannot satisfy its status/revision write guard. Preserve the reviewed
        # source stamps; a retry must not silently accept changed evidence.
        current.revision += 1
        if isinstance(current.trust_snapshot, dict) and current.trust_snapshot:
            current.trust_snapshot = {**current.trust_snapshot, "revision": current.revision}
        current.finished_at = None
        current.save(update_fields=["revision", "trust_snapshot", "finished_at", "updated_at"])
        pipeline.start(current, stage)
        brief.refresh_from_db()


def discard(brief: StudioBrief) -> None:
    """Stop the team and drop the draft — unless the post was already approved or sent."""
    from apps.composer.models import PlatformPost, Post

    with transaction.atomic():
        current = StudioBrief.objects.select_for_update().get(pk=brief.pk, workspace_id=brief.workspace_id)
        if current.post_id is not None:
            post = (
                Post.objects.select_for_update().filter(pk=current.post_id, workspace_id=current.workspace_id).first()
            )
            if post is None:
                raise StudioActionError("This draft's post is unavailable in this workspace.")
            list(PlatformPost.objects.select_for_update().filter(post=post).order_by("pk"))
            current.post = post
        if has_unconfirmed_delivery(current):
            raise StudioActionError("Resolve the previous delivery record before discarding this brief.")
        if post_statuses(current) & _APPROVED_STATUSES:
            raise StudioActionError("This post was approved, so it can't be discarded here. Manage it in the composer.")
        if current.post is not None:
            current.post.delete()
        current.status = StudioBrief.Status.DISCARDED
        current.post = None
        current.save(update_fields=["status", "post", "updated_at"])
        brief.refresh_from_db()


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
    statuses = post_statuses(brief)
    if "pending_client" in statuses:
        # An internal approval already happened on the Approvals page; the
        # client's sign-off is theirs to give in the portal, never ours to skip.
        sync_status(brief)
        raise StudioActionError("This post is with the client for sign-off — it's theirs to approve in the portal.")
    if statuses & _APPROVED_STATUSES:
        sync_status(brief)
        raise StudioActionError("This post was already approved. Schedule it from the calendar or the composer.")
    try:
        moved = approval_services.approve_post(post, user, workspace, comment="Approved on the post page in Agency.")
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
        message = f"Approved and queued for publishing now to {scheduled} account(s). Follow publishing status in the calendar."
    else:
        try:
            zone = zoneinfo.ZoneInfo(workspace.effective_timezone or "UTC")
        except (zoneinfo.ZoneInfoNotFoundError, ValueError):
            zone = zoneinfo.ZoneInfo("UTC")
        local = timezone.localtime(when, zone)
        message = f"Approved and scheduled for {local:%a %d %b, %H:%M} ({zone.key}) on {scheduled} account(s)."
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
