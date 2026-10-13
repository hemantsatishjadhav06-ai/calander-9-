"""Portal authentication decorator."""

import functools

from django.contrib.auth import logout
from django.core.exceptions import ValidationError
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

from apps.members.models import WorkspaceMembership
from apps.workspaces.models import Workspace

from .models import MagicLinkToken


def portal_auth_required(view_func):
    """Decorator that enforces portal session authentication.

    Checks that the user is authenticated, has an active portal session,
    and resolves the portal workspace onto the request.
    """

    def _signed_out(request):
        if request.session.get("is_portal_session"):
            logout(request)
        return redirect(f"{reverse('client_portal:magic_link_expired')}?reason=signed_out")

    @functools.wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return _signed_out(request)

        if not request.session.get("is_portal_session"):
            return _signed_out(request)

        workspace_id = request.session.get("portal_workspace_id")
        token_id = request.session.get("portal_token_id")
        if not workspace_id or not token_id:
            return _signed_out(request)

        try:
            workspace = Workspace.objects.get(id=workspace_id, is_archived=False)
            authorized = MagicLinkToken.objects.filter(
                id=token_id,
                user=request.user,
                workspace=workspace,
                is_consumed=True,
                expires_at__gt=timezone.now(),
            ).exists()
        except (Workspace.DoesNotExist, ValidationError, ValueError):
            return _signed_out(request)
        if not authorized:
            return _signed_out(request)

        # Verify user has client membership in this workspace
        membership = (
            WorkspaceMembership.objects.filter(
                user=request.user,
                workspace=workspace,
                workspace_role=WorkspaceMembership.WorkspaceRole.CLIENT,
            )
            .select_related("custom_role")
            .first()
        )

        if not membership:
            return _signed_out(request)

        request.portal_workspace = workspace
        request.portal_membership = membership

        return view_func(request, *args, **kwargs)

    return _wrapped
