"""The guided idea flow's endpoints. The page itself is Home now; these keep deep links and tests working."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET, require_POST
from django_ratelimit.decorators import ratelimit

from . import chat, customer_workflow
from .views_chat import _staff_workspace

#: The compact "In progress" rows, shared by Home and the status endpoint.
ROWS_TEMPLATE = "studio/partials/customer_workflow_journeys.html"


def _home(workspace):
    return redirect("studio:index", workspace_id=workspace.pk)


@login_required
@require_GET
def workflow(request, workspace_id):
    """The old guided page: Home is the one place to start and follow work."""
    workspace = _staff_workspace(request, workspace_id)
    return _home(workspace)


@login_required
@ratelimit(key="user", rate="10/m", method="POST", block=True)
@require_POST
def workflow_create(request, workspace_id):
    workspace = _staff_workspace(request, workspace_id)
    form = customer_workflow.IdeaForm(request.POST)
    if not form.is_valid():
        if "request_id" in form.errors:
            messages.error(request, "Refresh this page before saving your idea.")
        else:
            messages.error(request, " ".join(" ".join(errors) for errors in form.errors.values()))
        return _home(workspace)
    try:
        conversation = customer_workflow.save_idea(workspace, request.user, **form.cleaned_data)
        result = customer_workflow.start_idea(workspace, request.user, conversation.pk)
    except (customer_workflow.WorkflowError, chat.ChatError) as exc:
        messages.error(request, str(exc))
        return _home(workspace)
    messages.info(request, result.note)
    return _home(workspace)


@login_required
@ratelimit(key="user", rate="10/m", method="POST", block=True)
@require_POST
def workflow_resume(request, workspace_id, conversation_id):
    workspace = _staff_workspace(request, workspace_id)
    try:
        result = customer_workflow.start_idea(workspace, request.user, conversation_id)
    except (customer_workflow.WorkflowError, chat.ChatError) as exc:
        messages.error(request, str(exc))
        return _home(workspace)
    messages.info(request, result.note)
    if result.job is None:
        return _home(workspace)
    return redirect(customer_workflow._thread_url(workspace, result.conversation))


@login_required
@require_GET
def workflow_status(request, workspace_id):
    """The In progress rows, read-only, for a page that wants to refresh them."""
    workspace = _staff_workspace(request, workspace_id)
    context = customer_workflow.context(workspace, request.user)
    response = JsonResponse(
        {
            "html": render_to_string(ROWS_TEMPLATE, context, request=request),
            "active": context["active"],
            "polling": context["polling"],
            "checked_at": context["checked_at"].isoformat(),
        }
    )
    response["Cache-Control"] = "no-store, private"
    return response
