"""The approval gate: nothing goes out in an enforced workspace unless an
internal approver approved exactly that content, for exactly that time, in the
dashboard.

A workspace opts in with ``Workspace.require_dashboard_approval``. From then on:

* Approving a channel (``→ approved``) stamps the row with a fingerprint of
  what will be published — text, title, first comment, media files and their
  order and alt text, per-channel overrides and format, and the destination
  account — plus the publish time the approver saw. Only an internal approver
  acting in the dashboard can do that (:mod:`apps.approvals.actor`). The Agent
  API, MCP clients, the client portal and the background worker cannot.
* Entering ``scheduled`` or ``publishing`` requires a stamp that still matches
  the content and the time. An approver who reschedules in the dashboard
  approves the new time as they do it; anyone else moving the time needs a
  fresh approval.
* Editing anything the fingerprint covers, or moving the time without an
  approver, withdraws the approval and sends the channel back to review
  (:func:`revalidate_post`, run when the edit commits).
* The publisher calls :func:`publish_blocker` under its row lock, right before
  it claims a row, so a stale approval can never reach the platform, whatever
  path put the row on the schedule.

Every stamp, re-stamp, withdrawal and block is written to ``ApprovalAction``
with the fingerprint, version number, publish time and channel.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .actor import current_actor, dashboard_approver

logger = logging.getLogger(__name__)

#: Statuses that put a row on the path to the platform.
GATED_STATUSES = frozenset({"scheduled", "publishing"})
# Statuses only a person (or the publisher acting on a person's approval) may
# move a post into. Agency code is refused these outright (apps.studio.guards).
AGENT_FORBIDDEN_STATUSES = frozenset({"approved", "pending_client", "scheduled", "publishing", "published"})
#: Statuses whose approval is re-checked when content or time changes.
REVALIDATED_STATUSES = frozenset({"approved", "pending_client", "scheduled"})
#: Statuses that end an approval: the reviewer asked for changes or rejected.
CLEARING_STATUSES = frozenset({"changes_requested", "rejected"})
#: Two times within this window are the same publish time.
_SAME_TIME = timedelta(seconds=59)

#: ``platform_extra`` keys the publisher writes back after a publish. They are
#: results, not inputs, so they are not part of what was approved.
_RESULT_EXTRA_KEYS = frozenset({"permalink", "url", "post_url", "publish_id", "container_id", "media_id"})


class ApprovalRequired(ValueError):
    """The content may not be scheduled or published without (fresh) approval."""


# ---------------------------------------------------------------------------
# What was approved
# ---------------------------------------------------------------------------


def enforced(workspace) -> bool:
    return bool(getattr(workspace, "require_dashboard_approval", False))


def _iso(value):
    return value.isoformat() if value else None


def fingerprint(pp) -> str:
    """Hash of everything that will be published for this channel."""
    post = pp.post
    media = []
    for pm in post.media_attachments.select_related("media_asset").order_by("position", "id"):
        asset = pm.media_asset
        media.append(
            {
                "asset": str(pm.media_asset_id),
                "file": getattr(getattr(asset, "file", None), "name", "") or "",
                "position": pm.position,
                "alt": pm.alt_text or "",
                "overrides": pm.platform_overrides or {},
            }
        )
    extra = {k: v for k, v in (pp.platform_extra or {}).items() if k not in _RESULT_EXTRA_KEYS}
    payload = {
        "destination": str(pp.social_account_id),
        "title": post.title or "",
        "caption": post.caption or "",
        "first_comment": post.first_comment or "",
        "title_override": pp.platform_specific_title,
        "caption_override": pp.platform_specific_caption,
        "first_comment_override": pp.platform_specific_first_comment,
        "media_override": pp.platform_specific_media,
        "format": extra,
        "media": media,
    }
    blob = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def effective_publish_at(pp):
    return pp.scheduled_at or pp.post.scheduled_at


def _same_time(a, b) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= _SAME_TIME


def _current_revision(post):
    from django.db.models import Max

    return post.versions.aggregate(n=Max("version_number"))["n"]


def _record(pp, action, *, user=None, comment="", fp=None):
    from .models import ApprovalAction

    return ApprovalAction.objects.create(
        post_id=pp.post_id,
        platform_post_id=pp.pk,
        user=user,
        action=action,
        comment=comment,
        fingerprint=fp if fp is not None else (pp.approved_fingerprint or ""),
        revision=pp.approved_revision,
        publish_at=pp.approved_publish_at,
        channel=current_actor().channel,
    )


# ---------------------------------------------------------------------------
# Called by PlatformPost
# ---------------------------------------------------------------------------


def on_transition(pp, new_status) -> None:
    """Enforce the gate for ``pp.transition_to(new_status)``.

    Mutates the approval fields in memory; the caller persists them with
    ``PlatformPost.TRANSITION_FIELDS``. Agency work (the AI team) may never
    move a post to approved, scheduled or later, enforced or not.
    """
    if new_status in AGENT_FORBIDDEN_STATUSES:
        from apps.studio.guards import forbid_in_agent_work

        forbid_in_agent_work(f"move a post to {new_status}")
    workspace = pp.post.workspace
    if not enforced(workspace):
        return
    if new_status == "approved":
        _stamp_on_approve(pp, workspace)
    elif new_status in CLEARING_STATUSES:
        _clear(pp)
    elif new_status in GATED_STATUSES:
        _require_for_schedule(pp, workspace)


def check_write(pp, loaded_status) -> None:
    """Backstop for writes that set ``status`` directly (``save``/``save_guarded``).

    Only a move *into* a gated status is checked. The publisher's own writes
    out of ``publishing`` (a retry dropping back to ``scheduled``) are exempt:
    the row was checked when it was claimed, and nothing about it can change
    while it is in flight.
    """
    if pp.status in AGENT_FORBIDDEN_STATUSES and loaded_status != pp.status:
        from apps.studio.guards import forbid_in_agent_work

        forbid_in_agent_work(f"write status {pp.status}")
    if pp.status not in GATED_STATUSES or loaded_status in GATED_STATUSES:
        return
    if pp.pk is None or loaded_status != pp.status:
        workspace = pp.post.workspace
        if enforced(workspace):
            _require_for_schedule(pp, workspace)


def _stamp_on_approve(pp, workspace) -> None:
    approver = dashboard_approver(workspace)
    current = fingerprint(pp)
    if approver is None:
        # The client's sign-off in a two-stage workflow confirms an internal
        # approval of this same content; it cannot originate one.
        if pp.status == "pending_client" and pp.approved_fingerprint == current:
            return
        raise ApprovalRequired("Only an approver signed in to the dashboard can approve content in this workspace.")
    pp.approved_fingerprint = current
    pp.approved_revision = _current_revision(pp.post)
    pp.approved_by = approver
    pp.approved_at = timezone.now()
    pp.approved_publish_at = effective_publish_at(pp) or pp.post.proposed_publish_at


def _clear(pp) -> None:
    pp.approved_fingerprint = ""
    pp.approved_revision = None
    pp.approved_by = None
    pp.approved_at = None
    pp.approved_publish_at = None


def _require_for_schedule(pp, workspace) -> None:
    if not pp.approved_fingerprint:
        raise ApprovalRequired("This post has not been approved. Submit it for approval first.")
    if fingerprint(pp) != pp.approved_fingerprint:
        raise ApprovalRequired("This post changed after it was approved. It needs a fresh approval.")
    when = effective_publish_at(pp)
    if _same_time(when, pp.approved_publish_at):
        return
    approver = dashboard_approver(workspace)
    if approver is None or when is None:
        raise ApprovalRequired(
            "The publish time differs from the approved one. An approver must approve the new time in the dashboard."
        )
    # An approver choosing the time in the dashboard approves that time.
    pp.approved_publish_at = when
    pp.approved_by = approver
    pp.approved_at = timezone.now()
    pp._time_approved = True  # recorded by the post_save hook


# ---------------------------------------------------------------------------
# Publisher
# ---------------------------------------------------------------------------


def publish_blocker(pp) -> str | None:
    """Why the publisher must not send *pp* now, or None when it may.

    Pure check — no actor, no re-stamping: the worker is never an approver.
    """
    if not enforced(pp.post.workspace):
        return None
    if not pp.approved_fingerprint:
        return "Not published: this post was never approved. Approve it in the dashboard, then schedule it again."
    if fingerprint(pp) != pp.approved_fingerprint:
        return "Not published: the content changed after approval. Review and approve it again."
    if not _same_time(effective_publish_at(pp), pp.approved_publish_at):
        return "Not published: the publish time is not the approved one. Approve the new time in the dashboard."
    return None


def block_publish(pp, reason, *, from_status="scheduled") -> bool:
    """Take a due (or just-claimed) row out of the publish path, recording why.

    The row lands in ``failed`` with the reason as its error, so it shows up
    under failed posts with the action that fixes it. Returns True if blocked.
    """
    from apps.composer.models import PlatformPost

    moved = PlatformPost.objects.filter(pk=pp.pk, status=from_status).update(
        status=PlatformPost.Status.FAILED,
        publish_error=reason[:2000],
        updated_at=timezone.now(),
    )
    pp.status = PlatformPost.Status.FAILED if moved else pp.status
    if moved:
        from .models import ApprovalAction

        _record(pp, ApprovalAction.ActionType.BLOCKED, comment=reason, fp=fingerprint(pp))
        logger.warning("Approval gate blocked PlatformPost %s: %s", pp.pk, reason)
    return bool(moved)


# ---------------------------------------------------------------------------
# Edits after approval
# ---------------------------------------------------------------------------


class _Revalidate:
    """An on_commit callback that remembers which post it is for, so one
    transaction schedules each post once however many rows it touched."""

    def __init__(self, post_id):
        self.post_id = post_id
        self.done = False

    def __call__(self):
        self.done = True
        try:
            revalidate_post(self.post_id)
        except Exception:
            logger.exception("Approval revalidation failed for post %s", self.post_id)


def schedule_revalidation(post_id) -> None:
    if post_id is None:
        return
    connection = transaction.get_connection()
    if connection.in_atomic_block:
        for entry in connection.run_on_commit:
            func = entry[1]
            if isinstance(func, _Revalidate) and func.post_id == post_id and not func.done:
                return
    transaction.on_commit(_Revalidate(post_id))


def revalidate_post(post_id) -> list:
    """Withdraw or confirm approvals on *post_id*'s channels after an edit.

    Returns the rows whose approval was withdrawn.
    """
    from apps.composer.models import PlatformPost, Post

    post = Post.objects.select_related("workspace").filter(pk=post_id).first()
    if post is None or not enforced(post.workspace):
        return []
    withdrawn = []
    rows = PlatformPost.objects.filter(post=post, status__in=REVALIDATED_STATUSES).select_related("post__workspace")
    for pp in rows:
        reason = None
        if not pp.approved_fingerprint:
            reason = "it was never approved in the dashboard"
        elif fingerprint(pp) != pp.approved_fingerprint:
            reason = "the content changed after approval"
        elif pp.status == "scheduled" and not _same_time(effective_publish_at(pp), pp.approved_publish_at):
            approver = dashboard_approver(post.workspace)
            if approver is not None and effective_publish_at(pp) is not None:
                _approve_time(pp, approver)
                continue
            reason = "the publish time changed after approval"
        if reason and _withdraw(pp, reason):
            withdrawn.append(pp)
    if withdrawn:
        _notify_withdrawn(post, withdrawn)
    return withdrawn


def _approve_time(pp, approver) -> None:
    from apps.composer.models import PlatformPost

    from .models import ApprovalAction

    when = effective_publish_at(pp)
    now = timezone.now()
    PlatformPost.objects.filter(pk=pp.pk).update(approved_publish_at=when, approved_by=approver, approved_at=now)
    pp.approved_publish_at, pp.approved_by, pp.approved_at = when, approver, now
    _record(pp, ApprovalAction.ActionType.TIME_APPROVED, user=approver)


def _withdraw(pp, reason) -> bool:
    from apps.composer.models import PlatformPost

    from .models import ApprovalAction

    previous_fp = pp.approved_fingerprint
    moved = PlatformPost.objects.filter(pk=pp.pk, status=pp.status).update(
        status=PlatformPost.Status.PENDING_REVIEW,
        approved_fingerprint="",
        approved_revision=None,
        approved_by=None,
        approved_at=None,
        approved_publish_at=None,
        updated_at=timezone.now(),
    )
    if not moved:
        return False
    actor = current_actor()
    _record(
        pp,
        ApprovalAction.ActionType.WITHDRAWN,
        user=actor.user,
        comment=f"Approval withdrawn: {reason}. Sent back for review.",
        fp=previous_fp,
    )
    return True


def _notify_withdrawn(post, rows) -> None:
    try:
        from apps.notifications.models import EventType

        from .services import _notify_reviewers

        actor = current_actor().user
        names = ", ".join(sorted({pp.social_account.account_name or pp.social_account.platform for pp in rows}))
        _notify_reviewers(
            post.workspace,
            actor,
            post=post,
            event_type=EventType.POST_SUBMITTED,
            title="Approval withdrawn — needs review again",
            body=f'"{post.caption_snippet}" changed after it was approved ({names}). Review it again before it can go out.',
        )
    except Exception:
        logger.exception("Could not notify reviewers about a withdrawn approval on post %s", post.pk)


def record_time_approval_if_any(pp) -> None:
    """Write the audit row for a time an approver approved during a transition."""
    if getattr(pp, "_time_approved", False):
        from .models import ApprovalAction

        pp._time_approved = False
        _record(pp, ApprovalAction.ActionType.TIME_APPROVED, user=pp.approved_by)
