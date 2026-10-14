"""Authenticated task controls; canonical jobs and approvals remain authoritative."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from apps.members.decorators import require_permission

from . import opendots
from .views import _workspace


def _revision(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


@login_required
@require_permission("create_posts")
@ratelimit(key="user", rate="20/m", method="POST", block=True)
@require_POST
def job_control(request, workspace_id, job_id):
    workspace = _workspace(request, workspace_id)
    action = request.POST.get("action", "")
    apply_control(request, workspace, job_id, action)
    return redirect("studio:job", workspace_id=workspace.pk, job_id=job_id)


def apply_control(request, workspace, job_id, action):
    """Also fence the existing Retry/Stop forms, so they cannot bypass review."""
    try:
        opendots.control_job(
            workspace,
            request.user,
            job_id,
            action,
            expected_revision=_revision(request.POST.get("revision")),
            review_receipt=request.POST.get("review_receipt", ""),
            reviewed=request.POST.get("reviewed") == "1",
        )
    except opendots.CoworkerControlError as exc:
        messages.error(request, str(exc))
    else:
        notices = {
            "pause": "Paused future steps. A provider request already in progress may still finish; review saved work before resuming.",
            "resume": "Your assistant will continue from the paused step.",
            "retry": "Your assistant will retry the unfinished step. Previously saved work is retained.",
            "cancel": "Stopped future steps. Saved drafts and work already sent to a provider are retained.",
        }
        messages.success(request, notices[action])
