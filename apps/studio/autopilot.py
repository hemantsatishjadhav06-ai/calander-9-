"""The agency's heartbeat (``tasks.run_agency_cycle``, every 15 minutes).

Each part only reads the database and queues one-shot tasks, so the whole
cycle stays quick at the recurring tasks' priority; an error in one part is
logged and never stops the others:

1. ``plan_due_workspaces`` — autopilot plans next week where it is due;
2. ``feed_planned_briefs`` — planned briefs are handed to the team a few at a time;
3. ``refresh_memory_due`` — creative memory is refreshed after new analytics;
4. ``draft_inbox_replies_due`` — new comments and reviews get reply drafts;
5. ``announce_planned_weeks`` — once a planned week's posts are all made, the
   people who approve hear about it once;
6. ``queue_weekly_reports`` — the client report for last week, on Monday morning.

Nothing here approves, schedules or publishes: a plan makes PLANNED briefs,
the team turns them into posts that wait in Approvals with a proposed time,
and only a person turns that time into a schedule. Archived workspaces and
organisations waiting for deletion are left alone, and no new model work
starts in a workspace that has used its monthly budget.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.conf import settings as django_settings
from django.db import transaction
from django.db.models import Count, F, Max, Q
from django.utils import timezone

logger = logging.getLogger(__name__)

#: At most this many active (queued or working) briefs per workspace, so one
#: workspace's week can't hold the single worker for everyone else.
MAX_ACTIVE_PER_WORKSPACE = 2
#: Creative memory is refreshed at most this often per workspace...
MEMORY_EVERY = timedelta(hours=24)
#: ...and for at most this many workspaces per cycle.
MEMORY_PER_CYCLE = 3
#: The weekly report is written from this hour on Monday (workspace time); a
#: Monday the worker missed is caught up on Tuesday.
REPORT_HOUR = 8


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def eligible_workspaces():
    """Workspaces the agency may work in on its own: not archived, organisation not being deleted."""
    from apps.workspaces.models import Workspace

    return Workspace.objects.filter(
        is_archived=False,
        organization__deletion_requested_at__isnull=True,
        organization__deleted_at__isnull=True,
    )


def autopilot_settings():
    """Autopilot-on settings rows of eligible workspaces."""
    from .models import AgencySettings

    return AgencySettings.objects.filter(
        autopilot_enabled=True,
        workspace__in=eligible_workspaces(),
    ).select_related("workspace", "workspace__organization", "lead")


def local_now(workspace, now: datetime | None = None) -> datetime:
    from .jobtypes.plan import zone_of

    return (now or timezone.now()).astimezone(zone_of(workspace))


def next_week_start(workspace, now: datetime | None = None) -> date:
    """The Monday after this one, in the workspace's timezone."""
    local = local_now(workspace, now)
    return local.date() - timedelta(days=local.weekday()) + timedelta(days=7)


def plan_is_due(settings_row, now: datetime | None = None) -> bool:
    """True once this week's plan day and hour have passed (workspace time)."""
    local = local_now(settings_row.workspace, now)
    return (local.weekday(), local.hour) >= (settings_row.plan_weekday, settings_row.plan_hour)


def plan_blocker(settings_row) -> str:
    """Why a plan can't start for this workspace now, for people; "" when it can."""
    from . import budget
    from .jobtypes.plan import plan_accounts, valid_lead

    workspace = settings_row.workspace
    lead, reason = valid_lead(settings_row, workspace)
    if lead is None:
        return reason
    if not plan_accounts(workspace, settings_row):
        return (
            "None of the autopilot accounts is connected right now. Reconnect one, or choose others under "
            "Agency → Autopilot."
        )
    if not budget.can_spend(workspace):
        return budget.over_budget_message(workspace)
    return ""


@dataclass
class PlanOutcome:
    started: bool
    message: str
    week: object | None = None


def plan_week(settings_row, week_start: date, *, manual: bool = False) -> PlanOutcome:
    """Start the plan job for ``week_start`` — the tick and "Plan next week now" both come here.

    The week's :class:`~apps.studio.models.AutopilotWeek` row is unique per
    workspace and week, and it is created under a lock on the workspace's
    settings row, so a double tick (or a person pressing the button as the
    tick runs) starts one plan, not two. The tick records a week it can't
    plan as SKIPPED with the reason, so it doesn't try again every 15 minutes;
    a person pressing the button may re-plan a skipped or failed week, and is
    simply told the reason otherwise.
    """
    from . import engine
    from .models import AgencyJob, AgencySettings, AutopilotWeek

    workspace = settings_row.workspace
    with transaction.atomic():
        row = (
            AgencySettings.objects.select_for_update(of=("self",))
            .select_related("workspace", "workspace__organization", "lead")
            .get(pk=settings_row.pk)
        )
        week = AutopilotWeek.objects.filter(workspace=workspace, week_start=week_start).select_related("job").first()
        if week is not None:
            if not manual:
                return PlanOutcome(False, "", week)
            job = week.job
            retryable = week.status in (AutopilotWeek.Status.SKIPPED, AutopilotWeek.Status.FAILED) and not (
                job is not None and job.is_active
            )
            if not retryable:
                if job is not None and job.is_active:
                    return PlanOutcome(False, "The team is already planning that week.", week)
                return PlanOutcome(
                    False,
                    "That week is already planned. Brief the team for anything extra.",
                    week,
                )
        blocker = plan_blocker(row)
        if blocker:
            if not manual:
                AutopilotWeek.objects.create(
                    workspace=workspace, week_start=week_start, status=AutopilotWeek.Status.SKIPPED, note=blocker[:500]
                )
            return PlanOutcome(False, blocker, week)
        if week is None:
            week = AutopilotWeek.objects.create(workspace=workspace, week_start=week_start)
        job = engine.create(
            workspace,
            AgencyJob.Kind.PLAN,
            title=f"Plan for the week of {week_start:%d %b}",
            input={"week_start": week_start.isoformat(), "week_id": str(week.pk), "posts": row.posts_per_week},
            requested_by=row.lead,
        )
        AutopilotWeek.objects.filter(pk=week.pk).update(
            status=AutopilotWeek.Status.PLANNING, job=job, note="", updated_at=timezone.now()
        )
        week.refresh_from_db()
    return PlanOutcome(True, f"The planner is working on the week of {week_start:%d %b}.", week)


# ---------------------------------------------------------------------------
# 1. Plan the week
# ---------------------------------------------------------------------------


def plan_due_workspaces(now: datetime | None = None) -> int:
    """Start next week's plan for every autopilot workspace whose plan time has passed. Returns plans started."""
    from .models import AutopilotWeek

    started = 0
    now = now or timezone.now()
    for row in autopilot_settings():
        if not plan_is_due(row, now):
            continue
        week_start = next_week_start(row.workspace, now)
        if AutopilotWeek.objects.filter(workspace=row.workspace, week_start=week_start).exists():
            continue
        try:
            outcome = plan_week(row, week_start)
        except Exception:
            logger.exception("Autopilot: could not plan workspace %s", row.workspace_id)
            continue
        started += outcome.started
    return started


# ---------------------------------------------------------------------------
# 2. Feed planned briefs to the team
# ---------------------------------------------------------------------------


def feed_planned_briefs() -> int:
    """Start PLANNED briefs, oldest proposed time first, within the active-brief caps. Returns briefs started.

    Across all workspaces at most ``AGENCY_MAX_ACTIVE_BRIEFS`` briefs are queued
    or working at once (the single worker publishes between them), and at most
    :data:`MAX_ACTIVE_PER_WORKSPACE` per workspace. A workspace over its budget
    waits. Briefs of a plan someone cancelled are dropped.
    """
    from . import budget, services
    from .models import AgencyJob, StudioBrief

    StudioBrief.objects.filter(status=StudioBrief.Status.PLANNED, job__status=AgencyJob.Status.CANCELLED).update(
        status=StudioBrief.Status.DISCARDED, updated_at=timezone.now()
    )
    cap = int(getattr(django_settings, "AGENCY_MAX_ACTIVE_BRIEFS", 3) or 3)
    active = StudioBrief.objects.filter(status__in=StudioBrief.ACTIVE_STATUSES)
    room = cap - active.count()
    if room <= 0:
        return 0
    per_workspace = {
        row["workspace_id"]: row["n"] for row in active.values("workspace_id").annotate(n=Count("id")).order_by()
    }
    candidates = (
        StudioBrief.objects.filter(status=StudioBrief.Status.PLANNED, workspace__in=eligible_workspaces())
        .select_related("workspace", "workspace__organization")
        .order_by(F("proposed_publish_at").asc(nulls_last=True), "created_at")[:100]
    )
    started = 0
    spendable: dict[object, bool] = {}
    for brief in candidates:
        if started >= room:
            break
        workspace_id = brief.workspace_id
        if per_workspace.get(workspace_id, 0) >= MAX_ACTIVE_PER_WORKSPACE:
            continue
        if workspace_id not in spendable:
            spendable[workspace_id] = budget.can_spend(brief.workspace)
        if not spendable[workspace_id]:
            continue
        if services.start_planned(brief):
            started += 1
            per_workspace[workspace_id] = per_workspace.get(workspace_id, 0) + 1
    return started


# ---------------------------------------------------------------------------
# 3. Creative memory
# ---------------------------------------------------------------------------


def memory_has_news(workspace, since: datetime | None, now: datetime | None = None) -> bool:
    """New material for the curator since ``since`` (the last learn job).

    "New published posts" means posts that became old enough to rank
    (``performance.MIN_AGE``) since the last refresh; "new references" are
    picked creatives the curator hasn't described yet.
    """
    from apps.composer.models import PlatformPost

    from . import performance
    from .models import CreativeInsight

    now = now or timezone.now()
    posts = PlatformPost.objects.filter(
        post__workspace=workspace,
        status=PlatformPost.Status.PUBLISHED,
        published_at__lte=now - performance.MIN_AGE,
        published_at__gte=now - performance.LOOKBACK,
    )
    if since is not None:
        posts = posts.filter(published_at__gt=since - performance.MIN_AGE)
    if posts.exists():
        return True
    return CreativeInsight.objects.filter(
        workspace=workspace, is_reference=True, described_at__isnull=True, media_asset__isnull=False
    ).exists()


def refresh_memory_due(now: datetime | None = None) -> int:
    """Queue a learn job where the last one is a day old and something new happened. Returns jobs queued.

    Only workspaces that use the Studio (they have a brand profile) are
    considered, oldest refresh first, a few per cycle, each within its budget.
    """
    from . import budget, engine
    from .models import AgencyJob, BrandProfile

    now = now or timezone.now()
    learn = Q(agency_jobs__kind=AgencyJob.Kind.LEARN)
    workspaces = (
        eligible_workspaces()
        .filter(brand_profile__isnull=False)
        .annotate(
            last_learn=Max("agency_jobs__created_at", filter=learn),
            active_learn=Count(
                "agency_jobs", filter=learn & Q(agency_jobs__status__in=AgencyJob.ACTIVE_STATUSES), distinct=True
            ),
        )
        .filter(active_learn=0)
        .filter(Q(last_learn__isnull=True) | Q(last_learn__lt=now - MEMORY_EVERY))
        .select_related("organization")
        .order_by(F("last_learn").asc(nulls_first=True))
    )
    queued = 0
    for workspace in workspaces[:50]:
        if queued >= MEMORY_PER_CYCLE:
            break
        try:
            if not memory_has_news(workspace, workspace.last_learn, now) or not budget.can_spend(workspace):
                continue
            with transaction.atomic():
                # Lock the brand profile so two ticks can't both queue a refresh.
                BrandProfile.objects.select_for_update().filter(workspace=workspace).first()
                recent = AgencyJob.objects.filter(
                    workspace=workspace, kind=AgencyJob.Kind.LEARN, created_at__gte=now - MEMORY_EVERY
                ).exists()
                if recent:
                    continue
                engine.create(workspace, AgencyJob.Kind.LEARN, title="Refresh creative memory")
            queued += 1
        except Exception:
            logger.exception("Autopilot: could not queue a memory refresh for workspace %s", workspace.pk)
    return queued


# ---------------------------------------------------------------------------
# 4. Inbox drafts (apps.studio.inbox_team)
# ---------------------------------------------------------------------------


def draft_inbox_replies_due() -> int:
    from . import inbox_team

    return inbox_team.draft_due()


# ---------------------------------------------------------------------------
# 5. Tell people when the week is ready
# ---------------------------------------------------------------------------


def _approvers(workspace) -> list:
    """Internal approvers of ``workspace``: approve_posts, active, and not a client."""
    from apps.members.models import WorkspaceMembership

    people = []
    for membership in WorkspaceMembership.objects.filter(workspace=workspace).select_related("user", "custom_role"):
        if membership.workspace_role == WorkspaceMembership.WorkspaceRole.CLIENT and membership.custom_role is None:
            continue
        if membership.effective_permissions.get("approve_posts", False) and membership.user.is_active:
            people.append(membership.user)
    return people


def notify_week_ready(week, ready: int) -> int:
    """One AUTOPILOT_PLANNED notification per internal approver, linking to the agency page."""
    from django.urls import reverse

    from apps.notifications.engine import notify
    from apps.notifications.models import EventType

    workspace = week.workspace
    path = reverse("studio:index", kwargs={"workspace_id": workspace.id})
    url = f"{(getattr(django_settings, 'APP_URL', '') or '').rstrip('/')}{path}"
    title = f"Next week is ready for you: {ready} post{'s' if ready != 1 else ''} in {workspace.name}"
    body = (
        f"Autopilot planned the week of {week.week_start:%d %b} and the team has made {ready} "
        f"post{'s' if ready != 1 else ''}, each with a proposed time. Nothing goes out until you approve it."
    )
    sent = 0
    for user in _approvers(workspace):
        try:
            notify(
                user=user,
                event_type=EventType.AUTOPILOT_PLANNED,
                title=title,
                body=body,
                data={"workspace_id": str(workspace.id), "week_id": str(week.pk), "action_url": url},
            )
            sent += 1
        except Exception:
            logger.exception("Autopilot: could not notify user %s", user.pk)
    return sent


def announce_planned_weeks() -> int:
    """Settle each planning week once its plan and posts are finished. Returns weeks announced.

    A week stays PLANNING while its plan job runs and while its briefs are
    planned, queued or being made. Then it becomes PLANNED and the approvers
    get one notification (a conditional update makes a double tick send one,
    not two). A plan that failed or was cancelled marks the week FAILED; a
    person retrying the plan puts it back to PLANNING.
    """
    from .models import AgencyJob, AutopilotWeek, StudioBrief

    announced = 0
    weeks = AutopilotWeek.objects.filter(
        status__in=(AutopilotWeek.Status.PLANNING, AutopilotWeek.Status.FAILED),
        job__isnull=False,
        week_start__gte=timezone.now().date() - timedelta(days=21),
    ).select_related("job", "workspace")
    for week in weeks:
        job = week.job
        if job is None:
            continue
        if job.is_active:
            if week.status == AutopilotWeek.Status.FAILED:
                AutopilotWeek.objects.filter(pk=week.pk, status=AutopilotWeek.Status.FAILED).update(
                    status=AutopilotWeek.Status.PLANNING, updated_at=timezone.now()
                )
            continue
        if job.status in (AgencyJob.Status.FAILED, AgencyJob.Status.CANCELLED):
            note = "The plan was stopped." if job.status == AgencyJob.Status.CANCELLED else job.error
            AutopilotWeek.objects.filter(pk=week.pk, status=AutopilotWeek.Status.PLANNING).update(
                status=AutopilotWeek.Status.FAILED, note=(note or "The plan failed.")[:500], updated_at=timezone.now()
            )
            continue
        if job.status != AgencyJob.Status.DONE:
            continue
        statuses = list(StudioBrief.objects.filter(job=job, workspace=week.workspace).values_list("status", flat=True))
        busy = {StudioBrief.Status.PLANNED, StudioBrief.Status.QUEUED, StudioBrief.Status.WORKING}
        if any(status in busy for status in statuses):
            continue
        ready = sum(1 for status in statuses if status in (StudioBrief.Status.READY, StudioBrief.Status.APPROVED))
        if not ready:
            AutopilotWeek.objects.filter(pk=week.pk, status=AutopilotWeek.Status.PLANNING).update(
                status=AutopilotWeek.Status.FAILED,
                note="The team couldn't finish any of the week's posts. Open the plan to see why.",
                updated_at=timezone.now(),
            )
            continue
        moved = AutopilotWeek.objects.filter(pk=week.pk, status=week.status).update(
            status=AutopilotWeek.Status.PLANNED, updated_at=timezone.now()
        )
        if moved:
            notify_week_ready(week, ready)
            announced += 1
    return announced


# ---------------------------------------------------------------------------
# 6. The weekly client report
# ---------------------------------------------------------------------------


def report_is_due(settings_row, now: datetime | None = None) -> bool:
    local = local_now(settings_row.workspace, now)
    return local.weekday() == 1 or (local.weekday() == 0 and local.hour >= REPORT_HOUR)


def queue_report(workspace, week_start: date, *, requested_by=None, manual: bool = False):
    """Queue the report for the week starting ``week_start``. Returns the job, or None when one exists.

    The cycle writes one report per week, even if it failed (a person can
    press Retry; the cycle never re-bills on its own). A person asking for it
    again gets a fresh one unless one is being written right now.
    """
    from . import engine
    from .jobtypes.report import period_label
    from .models import AgencyJob, AgencySettings

    with transaction.atomic():
        AgencySettings.objects.select_for_update().filter(workspace=workspace).first()
        existing = AgencyJob.objects.filter(
            workspace=workspace,
            kind=AgencyJob.Kind.REPORT,
            input__week_start=week_start.isoformat(),
        )
        if manual:
            existing = existing.filter(status__in=AgencyJob.ACTIVE_STATUSES)
        if existing.exists():
            return None
        start = datetime.combine(week_start, datetime.min.time())
        label = period_label(start, start + timedelta(days=7))
        return engine.create(
            workspace,
            AgencyJob.Kind.REPORT,
            title=f"Weekly report: {label}",
            input={"week_start": week_start.isoformat()},
            requested_by=requested_by,
        )


def queue_weekly_reports(now: datetime | None = None) -> int:
    """On Monday morning (workspace time), queue last week's report where autopilot is on. Returns jobs queued."""
    from . import budget

    queued = 0
    now = now or timezone.now()
    for row in autopilot_settings():
        if not report_is_due(row, now):
            continue
        local = local_now(row.workspace, now)
        week_start = local.date() - timedelta(days=local.weekday()) - timedelta(days=7)
        try:
            if not budget.can_spend(row.workspace):
                continue
            queued += queue_report(row.workspace, week_start) is not None
        except Exception:
            logger.exception("Autopilot: could not queue the weekly report for workspace %s", row.workspace_id)
    return queued


PARTS = (
    "plan_due_workspaces",
    "feed_planned_briefs",
    "refresh_memory_due",
    "draft_inbox_replies_due",
    "announce_planned_weeks",
    "queue_weekly_reports",
)


def run_cycle() -> dict[str, int]:
    done: dict[str, int] = {}
    for name in PARTS:
        try:
            done[name] = int(globals()[name]() or 0)
        except Exception:
            logger.exception("Agency cycle: %s failed", name)
            done[name] = -1
    return done
