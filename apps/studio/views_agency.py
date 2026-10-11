"""The agency's own pages: the team roster and one job's timeline.

Under ``/workspace/<id>/studio/`` like the rest of the Studio, and for the
agency's staff only (see ``views._workspace``). Retrying or cancelling a job
needs ``create_posts``.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Max, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST
from django_ratelimit.decorators import ratelimit

from apps.members.decorators import require_permission

from . import budget, dashboard, engine, team
from .models import AgencyJob, AgentRun
from .views import _perms, _workspace


@login_required
@require_GET
def team_roster(request, workspace_id):
    workspace = _workspace(request, workspace_id)
    runs = (
        AgentRun.objects.filter(workspace=workspace)
        .values("agent")
        .annotate(
            total=Count("id"),
            working=Count("id", filter=Q(status=AgentRun.Status.RUNNING)),
            last=Max("started_at"),
        )
    )
    by_agent = {row["agent"]: row for row in runs}
    latest = {}
    for run in AgentRun.objects.filter(workspace=workspace).exclude(summary="").order_by("-started_at")[:300]:
        latest.setdefault(run.agent, run)
    departments = []
    for department, agents in team.by_department():
        rows = []
        for agent in agents:
            stats = by_agent.get(agent.slug, {})
            rows.append(
                {
                    "agent": agent,
                    "working": bool(stats.get("working")),
                    "total": stats.get("total", 0),
                    "last": stats.get("last"),
                    "latest": latest.get(agent.slug),
                }
            )
        departments.append({"department": department, "agents": rows})
    working_now = sum(1 for d in departments for row in d["agents"] if row["working"])
    return render(
        request,
        "studio/team.html",
        {
            "workspace": workspace,
            "departments": departments,
            "agent_count": len(team.AGENTS),
            "working_now": working_now,
            "tabs": dashboard.tabs(workspace, "team"),
        },
    )


def _get_job(request, workspace_id, job_id):
    workspace = _workspace(request, workspace_id)
    job = get_object_or_404(AgencyJob.objects.select_related("requested_by"), pk=job_id, workspace=workspace)
    return workspace, job


def _job_context(request, workspace, job):
    runs = list(job.runs.order_by("started_at"))
    stages = []
    try:
        jt = engine.job_type(job.kind)
        names = [s.name for s in jt.stages]
    except KeyError:
        jt, names = None, []
    current = names.index(job.stage) if job.stage in names else len(names)
    for index, stage in enumerate(jt.stages if jt else ()):
        stage_runs = [r for r in runs if r.stage == stage.name and r.revision == job.revision]
        if stage_runs and any(r.status == AgentRun.Status.RUNNING for r in stage_runs):
            state = "working"
        elif job.status == AgencyJob.Status.FAILED and index == current:
            state = "failed"
        elif index < current or job.status == AgencyJob.Status.DONE:
            state = "done"
        elif job.is_active and index == current:
            state = "working" if job.status == AgencyJob.Status.WORKING else "queued"
        else:
            state = "pending"
        stages.append({"stage": stage, "agent": team.get(stage.agent), "runs": stage_runs, "state": state})
    return {
        "workspace": workspace,
        "job": job,
        "stages": stages,
        "runs": runs,
        "can_act": _perms(request).get("create_posts", False),
        "tabs": dashboard.tabs(workspace, "overview"),
    }


@login_required
@require_GET
def job_detail(request, workspace_id, job_id):
    workspace, job = _get_job(request, workspace_id, job_id)
    return render(request, "studio/job_detail.html", _job_context(request, workspace, job))


@login_required
@require_GET
def job_progress(request, workspace_id, job_id):
    workspace, job = _get_job(request, workspace_id, job_id)
    response = render(request, "studio/partials/job_progress.html", _job_context(request, workspace, job))
    if not job.is_active:
        response["HX-Refresh"] = "true"
    return response


@login_required
@require_permission("create_posts")
@ratelimit(key="user", rate="10/m", method="POST", block=True)
@require_POST
def job_retry(request, workspace_id, job_id):
    workspace, job = _get_job(request, workspace_id, job_id)
    if job.status != AgencyJob.Status.FAILED:
        messages.error(request, "Only a job that failed can be retried.")
    elif not budget.can_spend(workspace):
        messages.error(request, budget.over_budget_message(workspace))
    else:
        engine.restart(job)
        messages.success(request, "The team is trying again from where it stopped.")
    return redirect("studio:job", workspace_id=workspace.id, job_id=job.pk)


@login_required
@require_permission("create_posts")
@require_POST
def job_cancel(request, workspace_id, job_id):
    workspace, job = _get_job(request, workspace_id, job_id)
    if job.is_active:
        engine.cancel(job)
        messages.success(request, "Stopped. Nothing the team had made so far was sent anywhere.")
    return redirect("studio:job", workspace_id=workspace.id, job_id=job.pk)


@login_required
@require_GET
def health(request, workspace_id):
    """A tiny status line for the sidebar or a monitor: how many agents are busy here."""
    workspace = _workspace(request, workspace_id)
    busy = AgentRun.objects.filter(workspace=workspace, status=AgentRun.Status.RUNNING).count()
    return HttpResponse(f"{busy} working", content_type="text/plain")
