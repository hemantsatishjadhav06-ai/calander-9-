"""Steps for the Phase 3 specs (docs/specs/phase-3.md).

Fixtures:

- ``dark_ready``: declares pages dark-ready in this process, the way ``fakes.py`` puts its stand-ins in
  place: it replaces ``apps.common.screens.DARK_READY``, which ``context_processors.theme_context``
  reads on every render, so the next request for a declared page carries ``data-theme-ready`` on
  ``<html>``. ``{"add": ["app_name:url_name", …]}`` adds pages to the set; ``{"clear": true}`` puts
  back the registry's own set (the pages the code declares, as the server started with them);
  both together clear first. Answers the set as ``{"ready": ["app_name:url_name", …]}``, sorted.
  A spec that adds a page clears it after each test (``test.afterEach``), so no other spec meets it.
- ``workspace_over_budget``: spends this month's allowance of a workspace a test made for itself
  (``{"workspace_id"}``), the way the team spends it: one finished report job with one run of this
  month whose reported cost is what was left of the budget, so ``budget.can_spend`` answers False and
  ``studio:create`` refuses with the New post sheet's own sentence. A workspace already spent gets no
  second run. The seeded workspaces A and B are refused: every spec shares them, and a spent month
  there would stop every other spec's team. Answers ``{"workspace_id", "budget", "spent",
  "can_spend"}`` (the amounts as strings).

Probe:

- ``new_post_outcome``: what the New post sheet made in a workspace (``?workspace_id&since=<epoch
  seconds>``; without ``since``, everything the workspace holds): its conversations, its messages
  counted by kind, its thread's (chat) jobs, its briefs, its ideas and its tags, each made at or after
  ``since``. A message's kind is the kind of request it was sent as (``create`` from Ask the team,
  ``question`` from Home's thread: the ``kind`` of the chat job asked about it), else its action
  (``workflow_idea``: the saved idea), else who wrote it (``agent``, ``system``, ``staff``, ``client``).
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from apps.common import screens

from .. import seed
from ..registry import PayloadError, fixture, optional_number, probe, require_str

#: The registry's own declared pages, as this process started with them.
DECLARED: frozenset[screens.Page] = screens.DARK_READY

_KEYS = frozenset({"add", "clear"})


def _page(name: Any) -> screens.Page:
    """``"app_name:url_name"`` as a page, refused unless the URL conf has that name."""
    from django.urls import get_resolver

    if not isinstance(name, str) or name.count(":") < 1:
        raise PayloadError(f"Each page in 'add' is 'app_name:url_name', like 'accounts:settings'; got {name!r}.")
    app_name, _, url_name = name.rpartition(":")
    resolver = get_resolver()
    for namespace in app_name.split(":"):
        if namespace not in resolver.namespace_dict:
            raise PayloadError(f"No URL namespace {namespace!r} (in {name!r}).")
        resolver = resolver.namespace_dict[namespace][1]
    if not url_name or url_name not in resolver.reverse_dict:
        raise PayloadError(f"No URL named {name!r}.")
    return (app_name, url_name)


@fixture("dark_ready")
def dark_ready(payload: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(payload) - _KEYS)
    if unknown:
        raise PayloadError(f"Unknown key(s) {', '.join(unknown)}; use 'add' and 'clear'.")
    clear = payload.get("clear", False)
    if not isinstance(clear, bool):
        raise PayloadError("'clear' must be true or false.")
    add = payload.get("add")
    if add is not None and (not isinstance(add, list) or not add):
        raise PayloadError("'add' must be a non-empty list of 'app_name:url_name'.")
    if not clear and add is None:
        raise PayloadError('Say what to do: {"add": ["app_name:url_name", …]} or {"clear": true}.')
    pages = frozenset(_page(name) for name in add or ())

    ready = (DECLARED if clear else screens.DARK_READY) | pages
    screens.DARK_READY = ready
    return {"ready": sorted(f"{app_name}:{url_name}" for app_name, url_name in ready)}


def _workspace(value: Any) -> Any:
    """The workspace named by ``value``; a missing, malformed or unknown id is a PayloadError."""
    from apps.workspaces.models import Workspace

    given = require_str({"workspace_id": value}, "workspace_id")
    try:
        workspace_id = uuid.UUID(given)
    except ValueError as exc:
        raise PayloadError("'workspace_id' must be a UUID.") from exc
    workspace = Workspace.objects.filter(pk=workspace_id).first()
    if workspace is None:
        raise PayloadError(f"No workspace {workspace_id}.")
    return workspace


@fixture("workspace_over_budget")
def workspace_over_budget(payload: dict[str, Any]) -> dict[str, Any]:
    from django.utils import timezone

    from apps.studio import budget
    from apps.studio.models import AgencyJob, AgentRun

    unknown = sorted(set(payload) - {"workspace_id"})
    if unknown:
        raise PayloadError(f"Unknown key(s) {', '.join(unknown)}; send only 'workspace_id'.")
    workspace = _workspace(payload.get("workspace_id"))
    if workspace.pk in (seed.WORKSPACE_A_ID, seed.WORKSPACE_B_ID):
        raise PayloadError("The seeded workspaces are shared by every spec: make a workspace for this test first.")
    left = budget.remaining(workspace)
    if left > 0:
        now = timezone.now()
        job = AgencyJob.objects.create(
            workspace=workspace,
            kind=AgencyJob.Kind.REPORT,
            status=AgencyJob.Status.DONE,
            title="This month's work",
            started_at=now,
            finished_at=now,
        )
        AgentRun.objects.create(
            workspace=workspace,
            job=job,
            agent="reporter",
            status=AgentRun.Status.SUCCEEDED,
            summary="This month's work",
            output={"provider_cost_usd": str(left)},
            started_at=now,
            finished_at=now,
        )
    return {
        "workspace_id": str(workspace.pk),
        "budget": str(budget.monthly_budget(workspace)),
        "spent": str(budget.month_spend(workspace)),
        "can_spend": budget.can_spend(workspace),
    }


def _message_kind(message: Any, asked: dict[str, str]) -> str:
    """What a message was: the request it was sent as, else its action, else who wrote it."""
    return asked.get(str(message.pk)) or message.action or message.author_kind


@probe("new_post_outcome")
def new_post_outcome(params: dict[str, Any]) -> dict[str, Any]:
    from apps.composer.models import Idea, Tag
    from apps.studio.models import AgencyJob, Conversation, Message, StudioBrief

    workspace = _workspace(params.get("workspace_id"))
    since = optional_number(params, "since")
    made: dict[str, Any] = {} if since is None else {"created_at__gte": datetime.fromtimestamp(since, tz=UTC)}

    conversations = Conversation.objects.filter(workspace=workspace, **made).select_related("created_by")
    chat_jobs = AgencyJob.objects.filter(workspace=workspace, kind=AgencyJob.Kind.CHAT, **made)
    every_ask = AgencyJob.objects.filter(workspace=workspace, kind=AgencyJob.Kind.CHAT).values_list("input", flat=True)
    asked = {
        str(given["message_id"]): str(given.get("kind") or "request")
        for given in every_ask
        if isinstance(given, dict) and given.get("message_id")
    }
    messages = Message.objects.filter(conversation__workspace=workspace, **made)
    ideas = Idea.objects.filter(workspace=workspace, **made).select_related("group", "author")
    return {
        "conversations": [
            {
                "id": str(row.pk),
                "audience": row.audience,
                "created_by": row.created_by.email if row.created_by else None,
            }
            for row in conversations.order_by("created_at", "pk")
        ],
        "messages": dict(sorted(Counter(_message_kind(row, asked) for row in messages).items())),
        "chat_jobs": [
            {
                "id": str(job.pk),
                "status": job.status,
                "kind": str((job.input or {}).get("kind") or ""),
                "conversation_id": str(job.conversation_id) if job.conversation_id else None,
            }
            for job in chat_jobs.order_by("created_at", "pk")
        ],
        "briefs": [
            {"id": str(brief.pk), "status": brief.status, "origin": brief.origin}
            for brief in StudioBrief.objects.filter(workspace=workspace, **made).order_by("created_at", "pk")
        ],
        "ideas": [
            {
                "id": str(idea.pk),
                "title": idea.title,
                "description": idea.description,
                "group": idea.group.name if idea.group else None,
                "tags": list(idea.tags) if isinstance(idea.tags, list) else [],
                "author": idea.author.email if idea.author else None,
            }
            for idea in ideas.order_by("created_at", "pk")
        ],
        "tags": sorted(Tag.objects.filter(workspace=workspace, **made).values_list("name", flat=True)),
    }
