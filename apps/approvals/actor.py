"""Who is acting on content right now.

The approval gate needs to know whether a change comes from a person in the
dashboard, a verified paired Telegram callback, the Agent API, an MCP client,
the client portal, or the background worker. Internal human approvers may
approve exact reviewed content and times through the dashboard or through an
authenticated, opted-in, one-use Telegram review. Automation only prepares
drafts and asks for review; clients only complete the client sign-off stage.

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
TELEGRAM = "telegram"

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
    telegram_proof: tuple | None = None

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
    from apps.accounts.models import User
    from apps.members.models import WorkspaceMembership

    if not User.objects.filter(pk=user.pk, is_active=True).exists():
        return False

    membership = (
        WorkspaceMembership.objects.filter(user=user, workspace=workspace).select_related("custom_role").first()
    )
    if membership is None:
        return False
    if membership.workspace_role == WorkspaceMembership.WorkspaceRole.CLIENT:
        return False
    if membership.custom_role and (
        membership.custom_role.organization_id != workspace.organization_id
        or (membership.custom_role.permissions or {}).get("client_facing")
    ):
        return False
    return bool(membership.effective_permissions.get("approve_posts", False))


def dashboard_approver(workspace):
    """The current actor's user if they are an internal approver in the dashboard, else None."""
    actor = current_actor()
    if actor.is_dashboard and is_internal_approver(actor.user, workspace):
        return actor.user
    return None


@contextmanager
def acting_as_telegram(action, *, nonce: str, telegram_user_id: int, chat_id: int, bot_id: int):
    """Use a validated one-use callback; the channel remains explicitly Telegram.

    This context alone is insufficient: the approval gate rechecks the active
    pairing, action, opt-in and exact reviewed content before every stamp.
    """
    from apps.studio.guards import forbid_in_agent_work

    forbid_in_agent_work("act as a verified Telegram approver")
    proof = (action.pk, nonce, telegram_user_id, chat_id, bot_id)
    token = _current.set(Actor(user=action.user_link.user, channel=TELEGRAM, telegram_proof=proof))
    try:
        yield
    finally:
        _current.reset(token)


def verified_human_approver(workspace):
    """A dashboard approver or a fresh, paired, explicitly opted-in Telegram human."""
    actor = current_actor()
    if actor.channel != TELEGRAM:
        return dashboard_approver(workspace)
    if actor.telegram_proof is None:
        return None
    from apps.telegram.actions import verified_approver

    return verified_approver(workspace, actor)
