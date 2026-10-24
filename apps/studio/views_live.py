"""The Team tab as a live view of the team at work, and the refresh behind it.

``team_page`` renders the whole tab (``studio:team``, reached through
``views_agency.team_roster``); ``team_board`` returns just the board for the
HTMX refresh every few seconds, or Home's "Right now" card with
``?part=strip``. Both are GET only, read-only and for the agency's staff
(``views._workspace``: clients get a 403 and use the portal). The numbers come
from ``apps.studio.live.snapshot``, cached for a few seconds per workspace, and
``live.for_viewer`` trims them for staff without ``create_posts``.
"""

from __future__ import annotations

import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET

from . import dashboard, live
from .views import _perms, _workspace

logger = logging.getLogger(__name__)


def _context(request, workspace) -> dict:
    perms = _perms(request)
    can_create = bool(perms.get("create_posts"))
    return {
        "workspace": workspace,
        # Cached per workspace, then trimmed per person: routines, autopilot and the composer need create_posts.
        "live": live.for_viewer(live.snapshot(workspace), workspace, can_create=can_create),
        "can_create": can_create,
        "can_approve": bool(perms.get("approve_posts")),
    }


def team_page(request, workspace_id):
    """The Team tab (the caller has already applied login_required and require_GET)."""
    workspace = _workspace(request, workspace_id)
    context = _context(request, workspace)
    context["tabs"] = dashboard.tabs(workspace, "team", perms=_perms(request))
    return render(request, "studio/team.html", context)


@login_required
@require_GET
def team_board(request, workspace_id):
    """The board alone, for the refresh; ``?part=strip`` returns Home's "Right now" card instead."""
    workspace = _workspace(request, workspace_id)
    template = (
        "studio/partials/live_strip.html" if request.GET.get("part") == "strip" else "studio/partials/team_board.html"
    )
    # A snapshot that fails never turns into an error page on screen: answer 204 so the board
    # keeps what it shows, and the next refresh tries again (Home's _live_strip does the same).
    try:
        context = _context(request, workspace)
    except Exception:
        logger.exception("Studio: could not build the live team snapshot for the refresh")
        response = HttpResponse(status=204)
        response["Cache-Control"] = "no-store"
        return response
    # Rendered without the request: a refresh every few seconds needs none of the page's context
    # processors (sidebar counts, channels), only the snapshot.
    response = HttpResponse(render_to_string(template, {**context, "refresh": True}))
    response["Cache-Control"] = "no-store"
    return response
