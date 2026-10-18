"""Background tasks for approval workflow reminders."""

import logging
import zoneinfo
from datetime import timedelta

from background_task import background
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.common.background import keep_schedule
from apps.composer.models import PlatformPost, Post
from apps.members.models import CustomRole, OrgMembership, WorkspaceMembership
from apps.notifications.engine import notify
from apps.notifications.models import EventType, Notification

from .models import ApprovalReminder

logger = logging.getLogger(__name__)

# Default reminder thresholds (overridable via settings_manager)
PENDING_REVIEW_HOURS = 24
PENDING_CLIENT_HOURS = 48
MAX_REMINDERS = 2
LEAD_DEADLINE_WINDOW = timedelta(hours=1)
BACKUP_DEADLINE_WINDOW = timedelta(minutes=30)
# Shared by age-based, deadline and escalation notices across every workspace.
# Notification preferences and delivery retries remain owned by the engine.
MAX_APPROVAL_ALERTS_PER_USER_DAY = 6
_ALERT_EVENTS = (EventType.APPROVAL_REMINDER, EventType.APPROVAL_STALLED)


def check_approval_reminders():
    """Check for stalled approvals and send reminders.

    Should be run every fifteen minutes, so the backup's thirty-minute
    window cannot fall between two hourly checks.
    """
    now = timezone.now()
    _process_deadlines(now)

    # 1. Posts stuck in pending_review
    _process_stage(
        stage="pending_review",
        status="pending_review",
        threshold_hours=PENDING_REVIEW_HOURS,
        now=now,
    )
    # 2. Posts stuck in pending_client
    _process_stage(
        stage="pending_client",
        status="pending_client",
        threshold_hours=PENDING_CLIENT_HOURS,
        now=now,
    )


def _pending_posts(status):
    """Only real pending destinations in a current workspace enter reminders."""
    return Post.objects.filter(
        workspace__is_archived=False,
        platform_posts__status=status,
        platform_posts__social_account__workspace_id=F("workspace_id"),
    ).distinct()


def _lock_workspace_users(workspace):
    # Every alert path takes user locks in one order, before notifying anyone.
    # This makes the shared daily cap survive overlapping sweeps and avoids
    # reversing lead/backup user lock order across different posts.
    return list(User.objects.select_for_update().filter(workspace_memberships__workspace=workspace).order_by("pk"))


def _pending_targets(post, status):
    return list(
        PlatformPost.objects.select_for_update()
        .filter(post=post, status=status, social_account__workspace_id=post.workspace_id)
        .order_by("pk")
    )


def _membership(post, user_id, *, client=False):
    """Revalidate current authority just before creating a recipient's notice."""
    membership = (
        WorkspaceMembership.objects.select_for_update().filter(workspace_id=post.workspace_id, user_id=user_id).first()
    )
    if membership is None:
        return None
    # Locking the user protects active-state checks and the per-person cap.
    user = User.objects.select_for_update().filter(pk=user_id, is_active=True).first()
    if user is None:
        return None
    membership.user = user
    if membership.custom_role_id:
        role = CustomRole.objects.select_for_update().filter(pk=membership.custom_role_id).first()
        if role is None or role.organization_id != post.workspace.organization_id:
            return None
        membership.custom_role = role
    plain_client = (
        membership.workspace_role == WorkspaceMembership.WorkspaceRole.CLIENT and membership.custom_role_id is None
    )
    if client != plain_client or not membership.effective_permissions.get("approve_posts", False):
        return None
    if (
        not client
        and not OrgMembership.objects.select_for_update()
        .filter(user_id=user_id, organization_id=post.workspace.organization_id)
        .exists()
    ):
        return None
    return membership


def _notify_members(
    post,
    user_ids,
    *,
    title,
    body,
    stage,
    now,
    event_type=EventType.APPROVAL_REMINDER,
    client=False,
    data=None,
    dedupe_recent=False,
):
    sent = 0
    configured_cap = getattr(settings, "APPROVAL_ALERTS_PER_USER_DAY", MAX_APPROVAL_ALERTS_PER_USER_DAY)
    cap = (
        configured_cap if isinstance(configured_cap, int) and configured_cap >= 0 else MAX_APPROVAL_ALERTS_PER_USER_DAY
    )
    for user_id in sorted(set(user_ids)):
        membership = _membership(post, user_id, client=client)
        if membership is None:
            continue
        recent = Notification.objects.filter(
            user_id=user_id, event_type__in=_ALERT_EVENTS, created_at__gte=now - timedelta(days=1)
        )
        earlier_stage = (data or {}).get("approval_stage", stage)
        if (
            dedupe_recent
            and recent.filter(
                event_type=event_type, data__post_id=str(post.pk), data__stage__in=(stage, earlier_stage)
            ).exists()
        ):
            # The earlier age reminder already reached this person. Record
            # that role as handled without creating a second copy of it.
            sent += 1
            continue
        if recent.count() >= cap:
            continue
        notice = notify(
            user=membership.user,
            event_type=event_type,
            title=title,
            body=body,
            data={
                "post_id": str(post.pk),
                "workspace_id": str(post.workspace_id),
                "stage": stage,
                "action_url": _review_url(post, client=client),
                **(data or {}),
            },
        )
        sent += notice is not None
    return sent


def _process_stage(stage, status, threshold_hours, now):
    """Process reminders for a specific approval stage."""
    threshold = now - timedelta(hours=threshold_hours)

    stalled_ids = _pending_posts(status).filter(updated_at__lte=threshold).values_list("pk", flat=True)
    for post_id in stalled_ids.iterator():
        with transaction.atomic():
            post = (
                Post.objects.select_for_update()
                .filter(pk=post_id, workspace__is_archived=False, updated_at__lte=threshold)
                .select_related("workspace")
                .first()
            )
            targets = _pending_targets(post, status) if post else []
            if not targets:
                continue
            deadline = _deadline(post, targets)
            if deadline is not None and deadline <= now + LEAD_DEADLINE_WINDOW:
                # Deadline notices explain the time-sensitive next action;
                # do not also mail the less useful age reminder this sweep.
                continue
            _lock_workspace_users(post.workspace)
            reminder, _ = ApprovalReminder.objects.get_or_create(post=post, stage=stage)
            if reminder.reminder_count >= MAX_REMINDERS:
                if not reminder.escalated and _escalate(post, stage, now=now):
                    reminder.escalated = True
                    reminder.save(update_fields=["escalated"])
                continue
            if reminder.last_reminder_at and now < reminder.last_reminder_at + timedelta(hours=threshold_hours):
                continue
            sent = _remind_reviewers(post, now=now) if stage == "pending_review" else _remind_clients(post, now=now)
            if not sent:
                continue
            reminder.reminder_count += 1
            reminder.last_reminder_at = now
            reminder.save(update_fields=["reminder_count", "last_reminder_at"])
            logger.info("Sent reminder #%d for post %s (stage: %s)", reminder.reminder_count, post.pk, stage)


def _remind_reviewers(post, *, now=None):
    """Send reminder to workspace members with approve_posts permission."""
    return _notify_members(
        post,
        WorkspaceMembership.objects.filter(workspace_id=post.workspace_id).values_list("user_id", flat=True),
        title="Post awaiting your review",
        body=f'A post in {post.workspace.name} has been waiting for review: "{post.caption_snippet}"',
        stage="pending_review",
        now=now or timezone.now(),
    )


def _remind_clients(post, *, now=None):
    """Send reminder to client members."""
    return _notify_members(
        post,
        WorkspaceMembership.objects.filter(
            workspace_id=post.workspace_id, workspace_role=WorkspaceMembership.WorkspaceRole.CLIENT
        ).values_list("user_id", flat=True),
        title="Posts waiting for your approval",
        body=f"Content in {post.workspace.name} is waiting for your review.",
        stage="pending_client",
        now=now or timezone.now(),
        client=True,
    )


def _manager_ids(post):
    return list(
        WorkspaceMembership.objects.filter(
            workspace_id=post.workspace_id,
            workspace_role__in=(WorkspaceMembership.WorkspaceRole.OWNER, WorkspaceMembership.WorkspaceRole.MANAGER),
        ).values_list("user_id", flat=True)
    )


def _review_url(post, *, client=False):
    if client:
        path = reverse("client_portal:approval_queue")
    else:
        path = reverse("calendar:calendar", kwargs={"workspace_id": post.workspace_id})
        path += "?mode=list&tab=approvals"
    return (getattr(settings, "APP_URL", "") or "http://localhost:8000").rstrip("/") + path


def _escalate(post, stage, *, now=None):
    """Notify workspace managers that a post is stalled."""
    stage_label = "internal review" if stage == "pending_review" else "client approval"
    return _notify_members(
        post,
        _manager_ids(post),
        event_type=EventType.APPROVAL_STALLED,
        title="Stalled post needs attention",
        body=f'A post in {post.workspace.name} has been stuck in {stage_label} after multiple reminders: "{post.caption_snippet}"',
        stage=stage,
        now=now or timezone.now(),
    )


def _deadline(post, targets):
    """A proposed time is a review deadline, never permission to publish."""
    if post.proposed_publish_at is not None:
        return post.proposed_publish_at
    scheduled = [target.scheduled_at or post.scheduled_at for target in targets]
    if any(scheduled):
        return min(when for when in scheduled if when is not None)
    # Only a current, same-workspace brief may supply the fallback suggestion.
    from apps.studio.models import StudioBrief

    return (
        StudioBrief.objects.filter(
            post=post,
            workspace_id=post.workspace_id,
            status__in=(StudioBrief.Status.READY, StudioBrief.Status.APPROVED),
        )
        .exclude(proposed_publish_at=None)
        .order_by("-created_at")
        .values_list("proposed_publish_at", flat=True)
        .first()
    )


def _deadline_recipients(post):
    from apps.studio.models import AgencySettings

    agency = AgencySettings.objects.filter(workspace_id=post.workspace_id).first()
    lead = _membership(post, agency.lead_id) if agency and agency.lead_id else None
    backup_id = getattr(agency, "backup_id", None)
    backup = _membership(post, backup_id) if backup_id else None
    lead_ids = [lead.user_id] if lead else [user_id for user_id in _manager_ids(post) if _membership(post, user_id)]
    backup_ids = (
        [backup.user_id] if backup else [user_id for user_id in _manager_ids(post) if _membership(post, user_id)]
    )
    return lead_ids, [user_id for user_id in backup_ids if user_id not in lead_ids]


def _local_deadline(post, deadline):
    try:
        zone = zoneinfo.ZoneInfo(post.workspace.effective_timezone or "UTC")
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        zone = zoneinfo.ZoneInfo("UTC")
    return f"{deadline.astimezone(zone):%d %b %Y, %H:%M} ({zone.key})"


def _process_deadlines(now):
    """Alert the current lead and backup before an imminent review deadline."""
    for status in (PlatformPost.Status.PENDING_REVIEW, PlatformPost.Status.PENDING_CLIENT):
        post_ids = _pending_posts(status).values_list("pk", flat=True)
        stage = "review_deadline" if status == PlatformPost.Status.PENDING_REVIEW else "client_deadline"
        for post_id in post_ids.iterator():
            with transaction.atomic():
                post = (
                    Post.objects.select_for_update()
                    .filter(pk=post_id, workspace__is_archived=False)
                    .select_related("workspace")
                    .first()
                )
                targets = _pending_targets(post, status) if post else []
                if not targets:
                    continue
                deadline = _deadline(post, targets)
                if deadline is None or deadline > now + LEAD_DEADLINE_WINDOW:
                    continue
                _lock_workspace_users(post.workspace)
                lead_ids, backup_ids = _deadline_recipients(post)
                reminder, _ = ApprovalReminder.objects.get_or_create(post=post, stage=stage)
                label = "internal review" if status == PlatformPost.Status.PENDING_REVIEW else "client approval"
                data = {"deadline": deadline.isoformat(), "approval_stage": status}
                local = _local_deadline(post, deadline)
                if deadline <= now:
                    if not reminder.escalated and _notify_members(
                        post,
                        [*lead_ids, *backup_ids],
                        event_type=EventType.APPROVAL_STALLED,
                        title="Post missed its proposed time",
                        body=f'"{post.caption_snippet}" in {post.workspace.name} still needs {label}. The proposed time was {local}. Review it and choose a new future time; it has not been scheduled by this reminder.',
                        stage=stage,
                        now=now,
                        data={**data, "deadline_role": "overdue"},
                    ):
                        reminder.escalated = True
                        reminder.save(update_fields=["escalated"])
                    continue
                if reminder.reminder_count == 0 and _notify_members(
                    post,
                    lead_ids,
                    title="Review needed before the proposed post time",
                    body=f'"{post.caption_snippet}" in {post.workspace.name} needs {label} before {local}. Review the exact draft and confirm a future publish time. Nothing is approved or scheduled automatically.',
                    stage=stage,
                    now=now,
                    data={**data, "deadline_role": "lead"},
                    dedupe_recent=True,
                ):
                    reminder.reminder_count = 1
                    reminder.last_reminder_at = now
                    reminder.save(update_fields=["reminder_count", "last_reminder_at"])
                if deadline <= now + BACKUP_DEADLINE_WINDOW and backup_ids:
                    # A separate role marker leaves a capped lead eligible
                    # after its backup has been notified, while keeping each
                    # counter an actual number of reminders rather than flags.
                    backup_stage = "review_backup" if status == PlatformPost.Status.PENDING_REVIEW else "client_backup"
                    backup_reminder, _ = ApprovalReminder.objects.get_or_create(post=post, stage=backup_stage)
                    if backup_reminder.reminder_count:
                        continue
                    sent = _notify_members(
                        post,
                        backup_ids,
                        title="Backup reviewer needed before the proposed post time",
                        body=f'"{post.caption_snippet}" in {post.workspace.name} is still waiting for {label}; the proposed time is {local}. Coordinate with the lead, review the exact draft and choose a future time.',
                        stage=stage,
                        now=now,
                        data={**data, "deadline_role": "backup"},
                        dedupe_recent=True,
                    )
                    if sent:
                        backup_reminder.reminder_count = 1
                        backup_reminder.last_reminder_at = now
                        backup_reminder.save(update_fields=["reminder_count", "last_reminder_at"])


# How often the recurring approval-reminder check runs; registered on a repeating
# schedule by apps.approvals.apps.ApprovalsConfig.
APPROVAL_REMINDER_INTERVAL_SECONDS = 15 * 60


@background(schedule=0)
@keep_schedule
def run_approval_reminders_cycle():
    """Send reminders/escalations for stalled approvals (every fifteen minutes).

    Wraps ``check_approval_reminders`` so the plain function stays callable
    synchronously from the ``run_approval_reminders`` command and from tests.
    """
    check_approval_reminders()
