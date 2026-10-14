"""Authenticated workspace entry point for the canonical guided post workflow."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET, require_POST
from django_ratelimit.decorators import ratelimit

from . import chat, customer_workflow
from .views_chat import _staff_workspace


@login_required
@require_GET
def workflow(request, workspace_id):
    workspace = _staff_workspace(request, workspace_id)
    response = render(request, "studio/customer_workflow.html", customer_workflow.context(workspace, request.user))
    response["Cache-Control"] = "no-store, private"
    return response


@login_required
@ratelimit(key="user", rate="10/m", method="POST", block=True)
@require_POST
def workflow_create(request, workspace_id):
    workspace = _staff_workspace(request, workspace_id)
    form = customer_workflow.IdeaForm(request.POST)
    if "request_id" in form.errors:
        form.add_error(None, "Refresh this page before saving your idea.")
    if form.is_valid():
        try:
            conversation = customer_workflow.save_idea(workspace, request.user, **form.cleaned_data)
            result = customer_workflow.start_idea(workspace, request.user, conversation.pk)
        except (customer_workflow.WorkflowError, chat.ChatError) as exc:
            form.add_error(None, str(exc))
        else:
            messages.info(request, result.note)
            return redirect("studio:workflow", workspace_id=workspace.pk)
    response = render(
        request,
        "studio/customer_workflow.html",
        customer_workflow.context(workspace, request.user, form=form),
        status=400,
    )
    response["Cache-Control"] = "no-store, private"
    return response


@login_required
@ratelimit(key="user", rate="10/m", method="POST", block=True)
@require_POST
def workflow_resume(request, workspace_id, conversation_id):
    workspace = _staff_workspace(request, workspace_id)
    try:
        result = customer_workflow.start_idea(workspace, request.user, conversation_id)
    except (customer_workflow.WorkflowError, chat.ChatError) as exc:
        messages.error(request, str(exc))
        return redirect("studio:workflow", workspace_id=workspace.pk)
    messages.info(request, result.note)
    if result.job is None:
        return redirect("studio:workflow", workspace_id=workspace.pk)
    return redirect(customer_workflow._thread_url(workspace, result.conversation))


@login_required
@require_GET
def workflow_status(request, workspace_id):
    workspace = _staff_workspace(request, workspace_id)
    context = customer_workflow.context(workspace, request.user)
    response = JsonResponse(
        {
            "html": render_to_string("studio/partials/customer_workflow_journeys.html", context, request=request),
            "active": context["active"],
            "polling": context["polling"],
            "checked_at": context["checked_at"].isoformat(),
        }
    )
    response["Cache-Control"] = "no-store, private"
    return response
