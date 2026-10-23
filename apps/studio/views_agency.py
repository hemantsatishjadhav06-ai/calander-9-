"""The agency's own pages: the Team tab (drawn live by ``views_live``) and one job's timeline.

Under ``/workspace/<id>/studio/`` like the rest of the Studio, and for the
agency's staff only (see ``views._workspace``). Retrying or cancelling a job
needs ``create_posts``.
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST
from django_ratelimit.decorators import ratelimit

from apps.members.decorators import require_permission

from . import chat, dashboard, engine, opendots, team
from .models import AgencyJob, AgentRun
from .views import _perms, _workspace
from .views_live import team_page


@login_required
@require_GET
def team_roster(request, workspace_id):
    """The Team tab: the team at work, live (``views_live``); every agent of the roster stays on it."""
    return team_page(request, workspace_id)


def _get_job(request, workspace_id, job_id):
    workspace = _workspace(request, workspace_id)
    job = get_object_or_404(
        chat.web_jobs(AgencyJob.objects.select_related("requested_by")), pk=job_id, workspace=workspace
    )
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
        "assistant_task": opendots.task_record(job),
        "tabs": dashboard.tabs(workspace, "overview", perms=_perms(request)),
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
    from .opendots_views import apply_control

    workspace, job = _get_job(request, workspace_id, job_id)
    apply_control(request, workspace, job.pk, "retry")
    return redirect("studio:job", workspace_id=workspace.id, job_id=job.pk)


@login_required
@require_permission("create_posts")
@require_POST
def job_cancel(request, workspace_id, job_id):
    from .opendots_views import apply_control

    workspace, job = _get_job(request, workspace_id, job_id)
    apply_control(request, workspace, job.pk, "cancel")
    return redirect("studio:job", workspace_id=workspace.id, job_id=job.pk)


@login_required
@require_GET
def health(request, workspace_id):
    """A tiny status line for the sidebar or a monitor: how many agents are busy here."""
    workspace = _workspace(request, workspace_id)
    busy = chat.web_agent_runs(AgentRun.objects.filter(workspace=workspace, status=AgentRun.Status.RUNNING)).count()
    return HttpResponse(f"{busy} working", content_type="text/plain")
