"""Staff-only manual campaign outcome tracking, with fresh write authorization."""

from datetime import datetime, time, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django_ratelimit.decorators import ratelimit

from apps.members.models import WorkspaceMembership

from . import dashboard, outcomes
from .forms_outcomes import OutcomeForm
from .jobtypes.plan import zone_of
from .models import CampaignOutcome
from .views import _perms, _workspace


@login_required
@require_http_methods(["GET", "POST"])
@ratelimit(key="user", rate="30/m", method="POST", block=True)
def outcome_page(request, workspace_id):
    workspace = _workspace(request, workspace_id)
    membership = request.workspace_membership
    if membership is None or membership.workspace_role == WorkspaceMembership.WorkspaceRole.CLIENT:
        raise PermissionDenied("Campaign outcomes are for the agency team.")
    writable = outcomes.can_record(membership)
    if not writable and not membership.effective_permissions.get("view_analytics", False):
        raise PermissionDenied("You do not have access to campaign outcomes.")
    form = OutcomeForm(request.POST if request.method == "POST" else None, workspace=workspace, user=request.user)
    if request.method == "POST":
        if not writable:
            raise PermissionDenied("You do not have permission to record campaign outcomes.")
        if form.is_valid():
            try:
                _, created = outcomes.record(
                    workspace,
                    request.user,
                    token=form.cleaned_data["submission_token"],
                    campaign_name=form.cleaned_data["campaign_name"],
                    occurred_on=form.cleaned_data["occurred_on"],
                    kind=form.cleaned_data["kind"],
                    count=form.cleaned_data["count"],
                    post=form.cleaned_data["post"],
                )
            except ValueError as exc:
                form.add_error(None, str(exc))
            else:
                messages.success(
                    request,
                    "Campaign outcome recorded."
                    if created
                    else "This entry was already recorded; no duplicate was added.",
                )
                return redirect("studio:outcomes", workspace_id=workspace.pk)
    zone = zone_of(workspace)
    today = timezone.now().astimezone(zone).date()
    start = datetime.combine(today - timedelta(days=29), time.min, tzinfo=zone)
    end = datetime.combine(today + timedelta(days=1), time.min, tzinfo=zone)
    rows = (
        CampaignOutcome.objects.filter(workspace=workspace)
        .filter(Q(post__isnull=True) | Q(post__workspace=workspace))
        .select_related("post", "recorded_by")[:50]
    )
    return render(
        request,
        "studio/outcomes.html",
        {
            "workspace": workspace,
            "tabs": dashboard.tabs(workspace, "outcomes", perms=_perms(request)),
            "form": form,
            "can_record": writable,
            "outcomes": rows,
            "totals": outcomes.totals(workspace, start, end),
        },
        status=400 if request.method == "POST" else 200,
    )
