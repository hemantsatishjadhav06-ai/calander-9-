"""Routines: standing instructions in plain words, on their own schedule.

``/workspace/<id>/studio/routines/``. For the agency's staff who may create
posts (never a plain client — see ``views._workspace``): anyone on the team
may write a routine and press Run now; pausing or deleting one is for the
person who wrote it or someone who manages the workspace's settings. Every
POST only changes rows or queues the same work a person could start by
typing in the team thread; nothing here approves, schedules or publishes.
"""

from __future__ import annotations

import datetime as dt

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST
from django_ratelimit.decorators import ratelimit

from apps.members.decorators import require_permission

from . import dashboard, routines
from .models import Routine
from .views import _perms, _workspace

CADENCES = tuple((value, label) for value, label in Routine.Cadence.choices)
WEEKDAYS = tuple(enumerate(routines.WEEKDAY_NAMES))
#: Field values the form posts back unchanged after an error.
FORM_FIELDS = ("title", "instruction", "cadence", "weekday", "time")


def _routine(workspace, routine_id) -> Routine:
    routine = (
        Routine.objects.filter(workspace=workspace, pk=routine_id).select_related("workspace", "created_by").first()
    )
    if routine is None:
        raise Http404("No such routine.")
    return routine


def _back(request, workspace):
    """Where a control returns to: the page it was pressed on (Home or Routines) when it is ours."""
    destination = request.POST.get("next", "")
    if destination and url_has_allowed_host_and_scheme(destination, allowed_hosts={request.get_host()}):
        return redirect(destination)
    return redirect("studio:routines", workspace_id=workspace.id)


def _context(request, workspace, *, form=None, error="") -> dict:
    perms = _perms(request)
    return {
        "workspace": workspace,
        "tabs": dashboard.tabs(workspace, "routines", perms=perms),
        "routines": routines.rows(workspace, viewer=request.user, perms=perms),
        "suggestions": [{"key": key, **preset} for key, preset in routines.SUGGESTIONS.items()],
        "cadences": CADENCES,
        "weekdays": WEEKDAYS,
        "form": form
        or {"title": "", "instruction": "", "cadence": Routine.Cadence.WEEKDAYS, "weekday": "0", "time": "08:30"},
        "error": error,
        "tzname": workspace.effective_timezone or "UTC",
        "can_manage": bool(perms.get("manage_workspace_settings")),
    }


@login_required
@require_permission("create_posts")
@require_GET
def routines_page(request, workspace_id):
    workspace = _workspace(request, workspace_id)
    return render(request, "studio/routines.html", _context(request, workspace))


def _parse_time(value: str) -> dt.time | None:
    try:
        return dt.time.fromisoformat((value or "").strip())
    except ValueError:
        return None


def _parse_weekday(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@login_required
@require_permission("create_posts")
@ratelimit(key="user", rate="10/m", method="POST", block=True)
@require_POST
def routines_create(request, workspace_id):
    """Write a routine from the form, or take one of the suggestions in one tap."""
    workspace = _workspace(request, workspace_id)
    suggestion = request.POST.get("suggestion", "")
    form = {name: request.POST.get(name, "") for name in FORM_FIELDS}
    try:
        if suggestion:
            routine = routines.suggestion(workspace, request.user, suggestion)
        else:
            routine = routines.create(
                workspace,
                request.user,
                title=form["title"],
                instruction=form["instruction"],
                cadence=form["cadence"],
                weekday=_parse_weekday(form["weekday"]),
                time=_parse_time(form["time"]),
            )
    except routines.RoutineError as exc:
        return render(
            request, "studio/routines.html", _context(request, workspace, form=form, error=str(exc)), status=400
        )
    when = routines.cadence_words(routine).lower()
    messages.success(request, f"Saved. “{routine.display_title}” runs {when}; the result lands in the team thread.")
    return _back(request, workspace)


def _changeable(request, workspace, routine_id) -> Routine:
    routine = _routine(workspace, routine_id)
    if not routines.can_change(routine, request.user, _perms(request)):
        raise PermissionDenied(
            "Only the person who wrote this routine, or someone who manages this workspace, can change it."
        )
    return routine


@login_required
@require_permission("create_posts")
@require_POST
def routines_toggle(request, workspace_id, routine_id):
    workspace = _workspace(request, workspace_id)
    routine = _changeable(request, workspace, routine_id)
    routines.set_enabled(routine, not routine.enabled)
    if routine.enabled:
        messages.success(request, f"On. Next run {routines.when_words(routine.next_run_at, workspace)}.")
    else:
        messages.success(request, "Paused. It keeps its words and schedule until you turn it back on.")
    return _back(request, workspace)


@login_required
@require_permission("create_posts")
@ratelimit(key="user", rate="10/m", method="POST", block=True)
@require_POST
def routines_run_now(request, workspace_id, routine_id):
    """Run it now: the same path the minute tick takes, started by a person."""
    workspace = _workspace(request, workspace_id)
    routine = _routine(workspace, routine_id)
    outcome = routines.run_now(routine)
    (messages.success if outcome.started else messages.error)(request, outcome.message)
    return _back(request, workspace)


@login_required
@require_permission("create_posts")
@require_POST
def routines_delete(request, workspace_id, routine_id):
    workspace = _workspace(request, workspace_id)
    routine = _changeable(request, workspace, routine_id)
    title = routine.display_title
    routine.delete()
    messages.success(request, f"Deleted “{title}”. Work it already started finishes as usual.")
    return _back(request, workspace)
