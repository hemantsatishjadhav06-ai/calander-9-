"""Connecting a website to Google Search Console, so the blog pages show how its articles rank.

Only someone who may manage the workspace's settings (and is on the agency's
own team, not a client) connects, picks the property or disconnects. The
connect button sends them to Google; Google sends them back to the one fixed
callback (:func:`oauth_callback`, outside ``/workspace/``), which re-checks who
they are and which website the signed ``state`` names before storing anything.
Syncing the numbers happens in the worker (``apps.blog.tasks``).
"""

from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django_ratelimit.decorators import ratelimit

from apps.members.decorators import require_permission

from . import search_console
from .models import BlogSite, SearchConsoleConnection, SearchPerformance
from .views import _staff_workspace

logger = logging.getLogger(__name__)

NOT_CONFIGURED = (
    "Google Search Console isn't set up on this server yet. Ask your admin to connect Google Search Console."
)


def _site(request, workspace_id, site_id):
    workspace = _staff_workspace(request, workspace_id)
    return workspace, get_object_or_404(BlogSite, pk=site_id, workspace=workspace)


def _back_to_blog(workspace):
    return redirect("blog:list", workspace_id=workspace.id)


def _queue_sync(connection: SearchConsoleConnection) -> None:
    from .tasks import PRIORITY_SEO, sync_search_console_site

    transaction.on_commit(lambda: sync_search_console_site(str(connection.pk), priority=PRIORITY_SEO))


@login_required
@require_POST
@require_permission("manage_workspace_settings")
@ratelimit(key="user", rate="10/m", method="POST", block=True)
def connect(request, workspace_id, site_id):
    """Send the manager to Google to grant read-only access to this website's Search Console data."""
    workspace, site = _site(request, workspace_id, site_id)
    if not search_console.is_configured():
        messages.error(request, NOT_CONFIGURED)
        return _back_to_blog(workspace)
    return redirect(search_console.authorization_url(request.user, site))


@login_required
@require_GET
@ratelimit(key="user", rate="10/m", method="GET", block=True)
def oauth_callback(request):
    """Google's answer to :func:`connect`. One fixed address for every workspace and website."""
    from apps.members.models import WorkspaceMembership
    from apps.studio.views import is_plain_client

    try:
        state = search_console.read_state(request.GET.get("state", ""), request.user)
    except search_console.SearchConsoleError as exc:
        messages.error(request, str(exc))
        return redirect("dashboard")
    membership = (
        WorkspaceMembership.objects.filter(user=request.user, workspace_id=state.workspace_id)
        .select_related("custom_role", "workspace")
        .first()
    )
    if (
        membership is None
        or is_plain_client(membership)
        or not membership.effective_permissions.get("manage_workspace_settings")
    ):
        raise PermissionDenied("You can't connect Search Console for this workspace.")
    site = get_object_or_404(BlogSite, pk=state.site_id, workspace_id=membership.workspace_id)
    workspace = membership.workspace

    if request.GET.get("error"):
        # e.g. access_denied when the person pressed Cancel at Google.
        messages.info(request, "Search Console wasn't connected: Google said the request was cancelled or refused.")
        return _back_to_blog(workspace)
    if not search_console.is_configured():
        messages.error(request, NOT_CONFIGURED)
        return _back_to_blog(workspace)
    try:
        token = search_console.exchange_code(request.GET.get("code", ""), state)
    except search_console.SearchConsoleError as exc:
        messages.error(request, str(exc))
        return _back_to_blog(workspace)

    connection = search_console.connection_for(site)
    if connection is None:
        connection = SearchConsoleConnection(site=site, property_url="")
    connection.refresh_token = token
    connection.connected_by = request.user
    connection.last_error = ""
    connection.save()
    messages.success(request, f"Google gave read-only access. Now pick the Search Console property for {site.name}.")
    return redirect("blog:search_console_property", workspace_id=workspace.id, site_id=site.pk)


@login_required
@require_http_methods(["GET", "POST"])
@require_permission("manage_workspace_settings")
# Each view asks Google for the property list.
@ratelimit(key="user", rate="20/m", method=["GET", "POST"], block=True)
def choose_property(request, workspace_id, site_id):
    """Pick which Search Console property is this website (only ones the Google account can read)."""
    workspace, site = _site(request, workspace_id, site_id)
    connection = search_console.connection_for(site)
    if connection is None or not search_console.has_token(connection):
        messages.info(request, "Connect Search Console for this website first.")
        return _back_to_blog(workspace)
    try:
        properties = search_console.list_properties(connection)
    except search_console.SearchConsoleError as exc:
        messages.error(request, str(exc))
        return _back_to_blog(workspace)

    error = ""
    if request.method == "POST":
        chosen = (request.POST.get("property") or "").strip()
        # Only a property Google just listed for this account can be saved.
        if chosen not in {p["url"] for p in properties}:
            error = "Pick one of the properties listed."
        else:
            changed = chosen != connection.property_url
            connection.property_url = chosen
            connection.last_error = ""
            if changed:
                connection.last_sync_at = None
            connection.save(update_fields=["property_url", "last_error", "last_sync_at"])
            if changed:
                # Numbers from another property don't belong to this website.
                SearchPerformance.objects.filter(site=site).delete()
            _queue_sync(connection)
            messages.success(
                request,
                f"Connected {site.name} to {chosen}. The last 90 days of rankings arrive in a few minutes, "
                "then refresh every day.",
            )
            return _back_to_blog(workspace)

    suggested = connection.property_url or search_console.matching_property(properties, site)
    return render(
        request,
        "blog/search_console_property.html",
        {
            "workspace": workspace,
            "site": site,
            "properties": properties,
            "suggested": suggested,
            "error": error,
        },
        status=400 if error else 200,
    )


@login_required
@require_POST
@require_permission("manage_workspace_settings")
@ratelimit(key="user", rate="10/m", method="POST", block=True)
def sync_now(request, workspace_id, site_id):
    """Fetch the latest rankings now instead of waiting for the daily sync."""
    workspace, site = _site(request, workspace_id, site_id)
    connection = search_console.connection_for(site)
    if connection is None or not search_console.is_connected(connection):
        messages.info(request, "Connect Search Console and pick the property first.")
        return _back_to_blog(workspace)
    _queue_sync(connection)
    messages.success(request, "Fetching the latest rankings from Google. Refresh this page in a minute.")
    return _back_to_blog(workspace)


@login_required
@require_POST
@require_permission("manage_workspace_settings")
@ratelimit(key="user", rate="10/m", method="POST", block=True)
def disconnect(request, workspace_id, site_id):
    """Drop SM Bean's access to this website's Search Console data, and the numbers copied from it."""
    workspace, site = _site(request, workspace_id, site_id)
    connection = search_console.connection_for(site)
    if connection is not None:
        search_console.revoke(connection)
        with transaction.atomic():
            SearchPerformance.objects.filter(site=site).delete()
            connection.delete()
    messages.success(request, f"Disconnected {site.name} from Google Search Console and removed its rankings.")
    return _back_to_blog(workspace)
