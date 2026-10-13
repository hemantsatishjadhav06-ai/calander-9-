"""Human-only account inspection actions. These never call a social provider."""

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from apps.members.decorators import require_permission
from apps.workspaces.models import Workspace

from . import delivery


def _act(request, workspace_id, platform_post_id, *, existing: bool):
    workspace = get_object_or_404(Workspace, pk=workspace_id, organization=request.org)
    kwargs = {
        "confirmed": request.POST.get("confirmed") == "1",
        "expected_attempt_id": request.POST.get("expected_attempt_id", ""),
        "expected_fingerprint": request.POST.get("expected_fingerprint", ""),
    }
    try:
        if existing:
            delivery.reconcile_existing(
                platform_post_id,
                workspace,
                request.user,
                native_post_id=request.POST.get("native_post_id", ""),
                url=request.POST.get("url", ""),
                **kwargs,
            )
        else:
            delivery.checked_absent(
                platform_post_id, workspace, request.user, reason=request.POST.get("reason", ""), **kwargs
            )
    except delivery.DeliveryActionError as exc:
        return HttpResponse(str(exc), status=400, content_type="text/plain")
    response = HttpResponse("Account check recorded. No publishing request was sent.", content_type="text/plain")
    response["HX-Refresh"] = "true"
    return response


@login_required
@require_permission("approve_posts")
@require_POST
def reconcile_existing(request, workspace_id, platform_post_id):
    return _act(request, workspace_id, platform_post_id, existing=True)


@login_required
@require_permission("approve_posts")
@require_POST
def checked_absent(request, workspace_id, platform_post_id):
    return _act(request, workspace_id, platform_post_id, existing=False)
