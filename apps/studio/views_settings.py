"""Settings (spec D5): one screen at ``/workspace/<id>/settings/`` with a tab per settings page.

``TABS`` is the registry, in the screen's order: Brand, Accounts, Team & clients,
Approvals, then Autopilot, Notifications and Advanced. Each entry names its key
(``?tab=<key>``), its label, the check its own page makes, the builder of its
context and the partial it shows. Adding a tab is adding an entry.

- **Who gets in:** staff of the workspace in the URL, like the agency's pages
  (``views._workspace``: a plain client gets 403; the membership middleware has
  already refused anyone else). The tab strip lists only the tabs this person
  may use; asking for another one by ``?tab=`` answers 403, an unknown key
  shows the first tab.
- **Only the active tab is built:** the strip needs the checks, never the
  builders, so a tab costs nothing until it is opened.
- **Saving stays where it was:** every panel includes its page's own body, and
  every form in it posts to that page's handler with an explicit ``action=``,
  so a save behaves exactly as before. Nothing is posted to this screen.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET

from apps.members.decorators import require_org_role, require_permission, require_workspace_role
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.members.views import is_internal_to_org
from apps.social_accounts.views import account_list_context
from apps.workspaces.views import approvals_settings_context, can_manage_approvals

from .brand_defaults import ensure_profile
from .forms import BrandProfileForm
from .views import _workspace, brand_profile_context


@dataclass(frozen=True)
class Tab:
    """One tab: ``allowed(request)`` is the check its page makes; ``build(request, workspace)``
    returns the panel's context and runs only for the open tab; ``template`` is the panel.
    ``no_store`` marks a panel whose page answers ``Cache-Control: no-store``."""

    key: str
    label: str
    allowed: Callable[[HttpRequest], bool]
    build: Callable[[HttpRequest, object], dict]
    template: str
    no_store: bool = False


def _passes(check, request) -> bool:
    """Whether *check*, a page's own permission decorator, lets *request* through."""
    try:
        check(lambda request: None)(request)
    except PermissionDenied:
        return False
    return True


# --- Brand: read by every staff member; saving needs approve_posts or manage_workspace_settings,
# which the brand page decides through can_edit, as it does on its own page.


def _brand_allowed(request) -> bool:
    return True


def _brand(request, workspace) -> dict:
    profile = ensure_profile(workspace)
    return brand_profile_context(request, workspace, profile, BrandProfileForm(instance=profile))


# --- Accounts: the accounts page's manage_social_accounts.


def _accounts_allowed(request) -> bool:
    return _passes(require_permission("manage_social_accounts"), request)


def _accounts(request, workspace) -> dict:
    return account_list_context(request, workspace.id)


# --- Team & clients: the roster is the organisation's (org member, not only a client); client
# access needs a workspace manager. Each section shows only for someone its page lets in.


def _roster_allowed(request) -> bool:
    org_membership = getattr(request, "org_membership", None)
    if org_membership is None or org_membership.organization_id != request.workspace.organization_id:
        return False
    return _passes(require_org_role("member"), request) and is_internal_to_org(request)


def _clients_allowed(request) -> bool:
    return _passes(require_workspace_role("manager"), request)


def _team_allowed(request) -> bool:
    return _roster_allowed(request) or _clients_allowed(request)


def _team(request, workspace) -> dict:
    show_members, show_clients = _roster_allowed(request), _clients_allowed(request)
    return {
        "show_members": show_members,
        "member_count": (
            OrgMembership.objects.filter(organization_id=workspace.organization_id).count() if show_members else 0
        ),
        "show_clients": show_clients,
        "client_count": (
            WorkspaceMembership.objects.filter(
                workspace=workspace, workspace_role=WorkspaceMembership.WorkspaceRole.CLIENT
            ).count()
            if show_clients
            else 0
        ),
    }


# --- Approvals: changing the workflow needs a workspace owner or manager.


def _approvals_allowed(request) -> bool:
    return can_manage_approvals(request.workspace_membership)


def _approvals(request, workspace) -> dict:
    return approvals_settings_context(workspace, request.workspace_membership)


#: The tabs, in the screen's order. Autopilot, Notifications and Advanced follow Approvals.
TABS: tuple[Tab, ...] = (
    Tab("brand", "Brand", _brand_allowed, _brand, "settings/tabs/brand.html"),
    Tab("accounts", "Accounts", _accounts_allowed, _accounts, "settings/tabs/accounts.html"),
    Tab("team", "Team & clients", _team_allowed, _team, "settings/tabs/team.html"),
    Tab("approvals", "Approvals", _approvals_allowed, _approvals, "settings/tabs/approvals.html"),
)


@login_required
@require_GET
def index(request, workspace_id):
    workspace = _workspace(request, workspace_id)
    usable = [tab for tab in TABS if tab.allowed(request)]
    asked = request.GET.get("tab", "")
    if asked in {tab.key for tab in TABS}:
        active = next((tab for tab in usable if tab.key == asked), None)
        if active is None:
            raise PermissionDenied("This part of Settings is for someone else on the team.")
    elif usable:
        active = usable[0]
    else:
        raise PermissionDenied("There is nothing in Settings for you to change.")

    url = reverse("settings:index", kwargs={"workspace_id": workspace.id})
    response: HttpResponse = render(
        request,
        "settings/index.html",
        {
            **active.build(request, workspace),
            "workspace": workspace,
            "settings_tabs": [
                {"key": tab.key, "label": tab.label, "url": f"{url}?tab={tab.key}", "active": tab is active}
                for tab in usable
            ],
            "settings_tab": active.key,
            "settings_tab_label": active.label,
            "settings_panel": active.template,
        },
    )
    if active.no_store:
        response["Cache-Control"] = "no-store, private"
    return response
