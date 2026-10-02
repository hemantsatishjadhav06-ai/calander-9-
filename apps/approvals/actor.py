"""Who is acting on content right now.

The approval gate needs to know whether a change comes from a person in the
dashboard or from something else: the Agent API, an MCP client, the client
portal, or the background worker. Only a person in the dashboard who holds an
internal approver role may approve content, or approve a change to when it
goes out. Everything else may prepare drafts and ask for review, nothing more.

``ApprovalActorMiddleware`` records the channel for every request. Code that
runs outside a request (the worker, management commands, tests) sees the
``system`` actor unless it opts in with :func:`acting_as`.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

DASHBOARD = "dashboard"
API = "api"
PORTAL = "portal"
SYSTEM = "system"

# Paths that never act as the dashboard, whatever cookie came with them.
# ``/api/`` serves both the Agent API and the MCP endpoint; ``/oauth/`` is the
# MCP authorization server; ``/portal/`` is the client approval portal.
_NON_DASHBOARD_PREFIXES = (
    ("/api/", API),
    ("/oauth/", API),
    ("/portal/", PORTAL),
)


@dataclass(frozen=True)
class Actor:
    user: Any | None
    channel: str

    @property
    def is_dashboard(self) -> bool:
        return self.channel == DASHBOARD and self.user is not None and getattr(self.user, "is_authenticated", False)


_SYSTEM_ACTOR = Actor(user=None, channel=SYSTEM)
_current: contextvars.ContextVar[Actor | None] = contextvars.ContextVar("approval_actor", default=None)


def current_actor() -> Actor:
    return _current.get() or _SYSTEM_ACTOR


@contextmanager
def acting_as(user, channel: str = DASHBOARD):
    """Run a block as *user* on *channel* (tests, management commands)."""
    token = _current.set(Actor(user=user, channel=channel))
    try:
        yield
    finally:
        _current.reset(token)


def channel_for_path(path: str) -> str:
    for prefix, channel in _NON_DASHBOARD_PREFIXES:
        if path.startswith(prefix):
            return channel
    return DASHBOARD


class ApprovalActorMiddleware:
    """Record who is acting for the length of the request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and not getattr(user, "is_authenticated", False):
            user = None
        token = _current.set(Actor(user=user, channel=channel_for_path(request.path)))
        try:
            return self.get_response(request)
        finally:
            _current.reset(token)


def is_internal_approver(user, workspace) -> bool:
    """True when *user* may approve content in *workspace*.

    An internal approver is a workspace member whose role grants
    ``approve_posts`` and who is not an external client. Clients sign off in
    the client stage of a two-stage workflow; they do not originate the
    approval the publisher checks.
    """
    if user is None or not getattr(user, "is_authenticated", False) or workspace is None:
        return False
    from apps.members.models import WorkspaceMembership

    membership = (
        WorkspaceMembership.objects.filter(user=user, workspace=workspace).select_related("custom_role").first()
    )
    if membership is None:
        return False
    if membership.workspace_role == WorkspaceMembership.WorkspaceRole.CLIENT and membership.custom_role is None:
        return False
    return bool(membership.effective_permissions.get("approve_posts", False))


def dashboard_approver(workspace):
    """The current actor's user if they are an internal approver in the dashboard, else None."""
    actor = current_actor()
    if actor.is_dashboard and is_internal_approver(actor.user, workspace):
        return actor.user
    return None
