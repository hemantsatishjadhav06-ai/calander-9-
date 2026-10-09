"""Autopilot: how often the team plans on its own, for which accounts, within what budget.

``/workspace/<id>/studio/autopilot/``. The agency's staff see the settings
and the last run (``create_posts``, never a client — see ``views._workspace``);
only people who manage the workspace's settings may change them, because they
decide what the team spends. "Plan next week now" (an owner or manager) and
"Write last week's report" only queue a job — the model work runs in the
worker, rate-limited and within the monthly budget. Autopilot never approves,
schedules or publishes: every post waits in Approvals for a person.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST
from django_ratelimit.decorators import ratelimit

from apps.members.decorators import require_permission

from . import autopilot, budget, dashboard, llm, reports
from .forms_agency import WEEKDAYS, AgencySettingsForm
from .models import AgencySettings, AgentRun, AutopilotWeek, StudioBrief
from .views import _perms, _workspace

_APPROVED_POST_STATUSES = ("approved", "pending_client", "scheduled", "publishing", "published", "on_hold")


def _settings_row(workspace) -> AgencySettings:
    """The saved settings, or an unsaved row with the defaults (a page view never writes)."""
    row = AgencySettings.objects.filter(workspace=workspace).select_related("lead", "blog_site").first()
    return row or AgencySettings(workspace=workspace)


def _can_plan(request, workspace) -> bool:
    from apps.approvals.actor import is_internal_approver

    return bool(_perms(request).get("create_posts")) and is_internal_approver(request.user, workspace)


def next_plan_at(row: AgencySettings) -> datetime:
    """When the tick next plans (workspace time), for the page to say so."""
    workspace = row.workspace
    local = autopilot.local_now(workspace)
    monday = local.date() - timedelta(days=local.weekday())
    week_start = monday + timedelta(days=7)
    when = datetime.combine(monday + timedelta(days=row.plan_weekday), time(row.plan_hour)).replace(tzinfo=local.tzinfo)
    if when <= local and AutopilotWeek.objects.filter(workspace=workspace, week_start=week_start).exists():
        when += timedelta(days=7)
    return when


def last_run(workspace) -> dict | None:
    """The newest planned week: what was planned, made, approved and changed, and what it cost."""
    week = AutopilotWeek.objects.filter(workspace=workspace).select_related("job").order_by("-week_start").first()
    if week is None:
        return None
    job = week.job
    briefs = list(StudioBrief.objects.filter(job=job, workspace=workspace).select_related("post")) if job else []
    approved = 0
    for brief in briefs:
        post = brief.post
        if brief.status == StudioBrief.Status.APPROVED or (
            post is not None and post.platform_posts.filter(status__in=_APPROVED_POST_STATUSES).exists()
        ):
            approved += 1
    runs = list(AgentRun.objects.filter(job=job)) if job else []
    runs += list(AgentRun.objects.filter(brief__in=briefs))
    notes = []
    for agent in ("performance_analyst", "audience_listener", "trend_scout"):
        run = next(
            (r for r in reversed(runs) if r.job_id and r.agent == agent and r.status == AgentRun.Status.SUCCEEDED),
            None,
        )
        if run and run.summary:
            notes.append({"agent": run.agent_name, "summary": run.summary})
    return {
        "week": week,
        "job": job,
        "planned": len(briefs),
        "made": sum(1 for b in briefs if b.status in (StudioBrief.Status.READY, StudioBrief.Status.APPROVED)),
        "approved": approved,
        "changed": sum(1 for b in briefs if b.revision > 1),
        "working": sum(1 for b in briefs if b.status in (*StudioBrief.ACTIVE_STATUSES, StudioBrief.Status.PLANNED)),
        "notes": notes,
        "cost": llm.estimate_cost(runs),
    }


def _context(request, workspace, form=None) -> dict:
    row = _settings_row(workspace)
    perms = _perms(request)
    if form is None:
        initial: dict[str, str] = {}
        if row.pk is None:
            from .forms_agency import eligible_leads

            leads = {str(user.pk) for user, _role in eligible_leads(workspace)}
            if str(request.user.pk) in leads:
                initial["lead"] = str(request.user.pk)
        form = AgencySettingsForm(instance=row, workspace=workspace, initial=initial)
    next_plan = next_plan_at(row) if row.pk and row.autopilot_enabled else None
    return {
        "workspace": workspace,
        "row": row,
        "form": form,
        "tzname": workspace.effective_timezone or "UTC",
        "tabs": dashboard.tabs(workspace, "autopilot"),
        "can_save": perms.get("manage_workspace_settings", False),
        "can_plan": _can_plan(request, workspace),
        "can_report": perms.get("create_posts", False),
        "weekdays": WEEKDAYS,
        "next_plan": next_plan,
        "plan_due_now": bool(next_plan and next_plan <= autopilot.local_now(workspace)),
        "last": last_run(workspace),
        "spend": budget.month_spend(workspace),
        "budget": budget.monthly_budget(workspace),
        "reports": reports.recent_reports(workspace, limit=3),
        "claude_ready": llm.is_configured(),
    }


@login_required
@require_permission("create_posts")
@require_http_methods(["GET", "POST"])
def settings_page(request, workspace_id):
    workspace = _workspace(request, workspace_id)
    if request.method == "POST":
        if not _perms(request).get("manage_workspace_settings", False):
            raise PermissionDenied("Only someone who manages this workspace's settings can change autopilot.")
        form = AgencySettingsForm(request.POST, instance=_settings_row(workspace), workspace=workspace)
        if not form.is_valid():
            return render(request, "studio/autopilot.html", _context(request, workspace, form), status=400)
        row = form.save()
        if row.autopilot_enabled:
            day = dict(WEEKDAYS)[row.plan_weekday]
            messages.success(
                request,
                f"Saved. The planner prepares next week every {day} at {row.plan_hour:02d}:00; "
                "every post still waits for your approval.",
            )
        else:
            messages.success(request, "Saved. Autopilot is off: the team only works when someone briefs it.")
        return redirect("studio:autopilot", workspace_id=workspace.id)
    return render(request, "studio/autopilot.html", _context(request, workspace))


@login_required
@require_permission("create_posts")
@ratelimit(key="user", rate="10/m", method="POST", block=True)
@require_POST
def plan_now(request, workspace_id):
    """Plan next week now: the same planning the weekly tick does, started by an owner or manager."""
    workspace = _workspace(request, workspace_id)
    if not _can_plan(request, workspace):
        raise PermissionDenied("Only an owner or manager can start the weekly plan.")
    row = AgencySettings.objects.filter(workspace=workspace).first()
    if row is None:
        messages.error(request, "Save the autopilot settings first: the accounts, and whose name the drafts carry.")
        return redirect("studio:autopilot", workspace_id=workspace.id)
    if not llm.is_configured():
        messages.error(request, "ANTHROPIC_API_KEY is missing on the server, so the team can't plan.")
        return redirect("studio:autopilot", workspace_id=workspace.id)
    outcome = autopilot.plan_week(row, autopilot.next_week_start(workspace), manual=True)
    if outcome.started:
        messages.success(request, outcome.message + " The posts appear in Approvals as they are made.")
        job = getattr(outcome.week, "job_id", None)
        if job:
            return redirect("studio:job", workspace_id=workspace.id, job_id=job)
    else:
        messages.error(request, outcome.message)
    return redirect("studio:autopilot", workspace_id=workspace.id)


@login_required
@require_permission("create_posts")
@ratelimit(key="user", rate="10/m", method="POST", block=True)
@require_POST
def report_now(request, workspace_id):
    """Write last week's client report now (the cycle writes it on Monday morning when autopilot is on)."""
    workspace = _workspace(request, workspace_id)
    if not llm.is_configured():
        messages.error(request, "ANTHROPIC_API_KEY is missing on the server, so the reporter can't write.")
        return redirect("studio:autopilot", workspace_id=workspace.id)
    if not budget.can_spend(workspace):
        messages.error(request, budget.over_budget_message(workspace))
        return redirect("studio:autopilot", workspace_id=workspace.id)
    local = autopilot.local_now(workspace)
    week_start = local.date() - timedelta(days=local.weekday()) - timedelta(days=7)
    job = autopilot.queue_report(workspace, week_start, requested_by=request.user, manual=True)
    if job is None:
        messages.info(request, "The reporter is already writing last week's report.")
        return redirect("studio:autopilot", workspace_id=workspace.id)
    messages.success(request, "The client reporter is writing last week's report.")
    return redirect("studio:job", workspace_id=workspace.id, job_id=job.pk)
