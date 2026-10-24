"""The live team view: who is working on what right now, what just finished, what comes next.

``snapshot(workspace)`` gathers everything the Team tab and Home's "Right now"
card draw, as plain values (strings, numbers, datetimes and URLs, never model
rows), so it can be cached and rendered by any template.

Rules it keeps:

* Read-only. It never writes, never calls a model and never touches a provider.
* Bounded. A fixed number of queries whatever the number of rows
  (``tests/test_live.py`` holds the budget), every list capped.
* This workspace only. Private Telegram jobs and their turns stay out
  (``chat.web_jobs`` / ``chat.web_agent_runs``); the pages that show it are for
  the agency's staff only (``views._workspace``), never clients, and
  ``for_viewer`` trims it for staff without ``create_posts``.
* Cached for a few seconds per workspace, so a room of open tabs refreshing
  every five seconds costs one snapshot.

Copy follows CLAUDE.md: status in words, no model, vendor, worker or token
names, times in the workspace's timezone.
"""

from __future__ import annotations

import hashlib
import json
import re
import zoneinfo
from datetime import UTC, datetime, timedelta
from typing import Any

from django.core.cache import cache
from django.db.models import Case, Count, IntegerField, Max, Q, Value, When
from django.db.models.functions import Coalesce
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from . import chat, team
from .models import AgencyJob, AgencySettings, AgentRun, Routine, StudioBrief

CACHE_SECONDS = 3
CACHE_PREFIX = "studio:live:v1:"

#: At most this many tasks get a stage track; the rest are counted.
MAX_TRACKS = 8
#: Rows in "Recently finished".
RECENT_LIMIT = 10
#: Failed, paused and interrupted tasks count in "Needs you" for this long, so an old failure ages out.
NEEDS_YOU_DAYS = 7
#: A turn still marked running after this long is a leftover, not live work.
STALE_RUN = timedelta(hours=2)
#: An agent whose latest turn failed within this window shows as stopped.
STOPPED_WINDOW = timedelta(hours=24)
#: No check-in for this long means the team is offline (the publishing cycle checks in every minute).
OFFLINE_AFTER = 10 * 60
#: Timeline events closer than this (percent of the 24 hours) share one marker.
CLUSTER_PCT = 3.0
#: A timeline caption is at most this wide (percent of the timeline; the template caps it the same way).
CAPTION_PCT = 16.0

#: The post pipeline's ten stages, shown as six steps a person recognises (DESIGN_SYSTEM.md 14.2).
POST_STEPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Brief", ()),
    ("Angles", ("strategy",)),
    ("Copy", ("copy",)),
    ("Design", ("art", "picture", "render")),
    ("Check", ("review", "channel", "qa")),
    ("For you", ("schedule", "handoff")),
)
_POST_STEP_OF = {stage: index for index, (_label, stages) in enumerate(POST_STEPS) for stage in stages}

#: The post pipeline's stage -> the agent at work during it (the picture stage starts with the prompt engineer).
STAGE_AGENT = {
    "strategy": "strategist",
    "copy": "copywriter",
    "art": "art_director",
    "picture": "prompt_engineer",
    "render": "designer",
    "review": "reviewer",
    "channel": "channel_editor",
    "qa": "qa_inspector",
    "schedule": "scheduler",
    "handoff": "producer",
}

#: Short step names for job stages whose job type has no labels of its own.
JOB_STAGE_LABELS = {
    "plan": {"listen": "Read results", "moments": "Moments", "plan": "Plan", "brief": "Briefs"},
    "chat": {"answer": "Answer"},
    "inbox": {"community": "Comments", "reviews": "Reviews"},
    "learn": {"rank": "Rank", "describe": "House style"},
    "report": {"listen": "Listen", "write": "Write"},
    "seo": {"check": "Check-up"},
}

#: What each agent is doing while it works, as the end of "Copywriter is writing the caption".
DOING = {
    "account_manager": "is replying in the thread",
    "reporter": "is writing the report",
    "strategist": "is finding three angles",
    "planner": "is planning next week's posts",
    "trend_scout": "is looking for timely moments",
    "performance_analyst": "is reading your results",
    "audience_listener": "is reading comments and reviews",
    "creative_curator": "is studying your best creatives",
    "copywriter": "is writing the caption",
    "channel_editor": "is writing each network's version",
    "art_director": "is choosing the layout and picture",
    "prompt_engineer": "is describing the picture",
    "illustrator": "is painting the picture",
    "designer": "is setting the graphic",
    "reviewer": "is checking facts and brand rules",
    "qa_inspector": "is checking lengths, links and alt text",
    "fact_checker": "is checking every claim",
    "editor_in_chief": "is giving it a final read",
    "scheduler": "is proposing a time",
    "producer": "is putting it together for you",
    "community_manager": "is drafting replies",
    "reputation_manager": "is drafting review replies",
    "seo_strategist": "is picking the keyword",
    "outline_editor": "is planning the headings",
    "blog_writer": "is writing the article",
    "seo_editor": "is writing the search title",
    "repurposer": "is turning the article into posts",
    "seo_monitor": "is scoring your articles",
}

#: Roles whose roster sentence names a vendor; the team view never does (CLAUDE.md invariant 9).
ROLE_COPY = {
    "illustrator": "Paints the picture for the post.",
    "account_manager": "Answers your questions and turns requests into work for the right teammate.",
}

_JOB_WORD = {
    "running": "Working",
    "queued": "Queued",
    "waiting_policy": "Paused: autopilot is off",
    "waiting_setup": "Waiting for Set up",
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _zone(workspace) -> zoneinfo.ZoneInfo:
    try:
        return zoneinfo.ZoneInfo(workspace.effective_timezone or "UTC")
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return zoneinfo.ZoneInfo("UTC")


def _url(name: str, **kwargs) -> str:
    try:
        return reverse(name, kwargs=kwargs)
    except NoReverseMatch:
        return ""


def ago(seconds: float | None) -> str:
    """A short age such as 12 s, 4 min, 3 h or 2 d (the caller adds the word "ago")."""
    if seconds is None:
        return ""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min"
    if seconds < 86400:
        return f"{seconds // 3600} h"
    return f"{seconds // 86400} d"


def elapsed(seconds: float) -> str:
    """How long a task has been going: under a minute, 4 min, 1 h 20 min, 2 d."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return "under a minute"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} h {minutes} min" if minutes else f"{hours} h"
    return f"{hours // 24} d"


def _day_label(when: datetime, local_now: datetime) -> str:
    """The time alone today (10:10), "Tomorrow 09:00", else "Mon 26 Oct, 10:10"."""
    if when.date() == local_now.date():
        return when.strftime("%H:%M")
    if when.date() == (local_now + timedelta(days=1)).date():
        return f"Tomorrow {when:%H:%M}"
    return f"{when:%a} {when.day} {when:%b}, {when:%H:%M}"


#: A setting's name (FAL_KEY) or a vendor's: never in the team view's copy (CLAUDE.md invariant 9).
_SETTING_NAME = re.compile(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b")
_VENDOR_NAME = re.compile(r"\b(?:fal(?:\.ai)?|anthropic|claude|openrouter|openai)\b", re.IGNORECASE)


def safe_summary(text: str | None) -> str:
    """A turn's summary as the roster shows it: one line, and a plain stand-in if it names a setting or a vendor."""
    summary = " ".join((text or "").split())
    if _SETTING_NAME.search(summary) or _VENDOR_NAME.search(summary):
        return "Finished a turn. Open it to see the details."
    return summary


def _agent_ref(slug: str) -> dict[str, str]:
    spec = team.get(slug)
    return {"slug": spec.slug, "name": spec.name, "initials": spec.initials}


def _doing(slug: str) -> str:
    return f"{team.name(slug)} {DOING.get(slug, 'is working')}"


def _num(value: float) -> str:
    """A number for an SVG or CSS attribute: a dot for decimals whatever the locale, at most three places."""
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return text or "0"


def _nice_max(value: int) -> int:
    """The top of the hour chart's scale: a clean number at or above the busiest hour."""
    for step in (2, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 60, 80, 100, 150, 200, 250, 300, 400, 500):
        if value <= step:
            return step
    return ((value + 99) // 100) * 100


# ---------------------------------------------------------------------------
# Worker health
# ---------------------------------------------------------------------------


def _health(now: datetime) -> dict[str, Any]:
    """Online, delayed or offline, from the recurring tasks' check-ins (one query)."""
    from apps.common.background import task_health

    rows = task_health(now=now)
    checkins = [datetime.fromisoformat(row["last_success_at"]) for row in rows.values() if row.get("last_success_at")]
    last = max(checkins) if checkins else None
    age = max(0, int((now - last).total_seconds())) if last else None
    if age is None or age > OFFLINE_AFTER:
        state = "offline"
    elif all(row.get("healthy") for row in rows.values()):
        state = "online"
    else:
        state = "delayed"
    since = f"last check-in {ago(age)} ago" if age is not None else "no check-in yet"
    if state == "online":
        label, detail, sentence = "Online", f"checked {ago(age)} ago", ""
    elif state == "delayed":
        label, detail = "Running late", since
        sentence = "Your team is behind schedule, so new work may start a few minutes late. It catches up on its own."
    else:
        label, detail = "Offline", since
        sentence = (
            "Your team has not checked in recently, so nothing new starts until it is back. The owner can check Set up."
        )
    return {
        "state": state,
        "label": label,
        "detail": detail,
        "sentence": sentence,
        "age_seconds": age,
        "last_checkin": last,
    }


# ---------------------------------------------------------------------------
# Tracks: one per active task
# ---------------------------------------------------------------------------


def _post_track(brief: StudioBrief, running: dict, now: datetime, zone) -> dict[str, Any]:
    current = _POST_STEP_OF.get(brief.stage, 1 if brief.stage != "done" else len(POST_STEPS) - 1)
    working = brief.status == StudioBrief.Status.WORKING
    stages = []
    for index, (label, _names) in enumerate(POST_STEPS):
        if index < current or index == 0:
            state = "done"
        elif index == current:
            state = "working" if working else "waiting"
        else:
            state = "waiting"
        stages.append({"label": label, "state": state})
    run = running.get(("brief", brief.pk))
    agent_slug = run["agent"] if run else STAGE_AGENT.get(brief.stage, "strategist")
    started = brief.started_at or brief.created_at
    step_label = POST_STEPS[current][0]
    if working:
        status, word = "working", "Working"
        doing = _doing(agent_slug)
        step_text = f"Step {current + 1} of {len(POST_STEPS)}: {step_label}, working"
    else:
        status, word = "queued", "Queued"
        doing = f"Waiting its turn. {team.name(agent_slug)} is next."
        step_text = f"Queued. Next step {current + 1} of {len(POST_STEPS)}: {step_label}"
    return {
        "key": f"brief-{brief.pk}",
        "kind": "post",
        "kind_label": "Post",
        "title": brief.title,
        "url": _url("studio:detail", workspace_id=brief.workspace_id, brief_id=brief.pk),
        "status": status,
        "status_word": word,
        "policy_url": "",
        "policy_link": "",
        "agent": _agent_ref(agent_slug),
        "doing": doing,
        "platforms": sorted({account.get_platform_display() for account in brief.social_accounts.all()}),
        "started_at": started.astimezone(zone) if started else None,
        "started_text": f"{started.astimezone(zone):%H:%M}" if started else "",
        "elapsed_text": elapsed((now - started).total_seconds()) if started else "",
        "stages": stages,
        "current_index": current,
        "current_label": step_label,
        "step_text": step_text,
        "long": False,
        "sort": (0 if working else 1, started or now),
    }


def _job_stage_label(job_type, stage) -> str:
    return (
        (job_type.labels or {}).get(stage.name)
        or JOB_STAGE_LABELS.get(job_type.kind, {}).get(stage.name)
        or stage.name.replace("_", " ").capitalize()
    )


def _job_track(job: AgencyJob, running: dict, now: datetime, zone) -> dict[str, Any] | None:
    from .jobs import JOB_TYPES
    from .opendots import task_status

    job_type = JOB_TYPES.get(job.kind)
    if job_type is None:
        return None
    names = [stage.name for stage in job_type.stages]
    current = names.index(job.stage) if job.stage in names else 0
    record = task_status(job)
    working = record["status"] == "running"
    stages = []
    for index, stage in enumerate(job_type.stages):
        if index < current:
            state = "done"
        elif index == current:
            state = "working" if working else "waiting"
        else:
            state = "waiting"
        stages.append({"label": _job_stage_label(job_type, stage), "state": state})
    run = running.get(("job", job.pk))
    agent_slug = run["agent"] if run else job_type.stages[current].agent
    started = job.started_at or job.created_at
    step_label = stages[current]["label"]
    total = len(stages)
    if working:
        doing = _doing(agent_slug)
        step_text = f"Step {current + 1} of {total}: {step_label}, working"
    elif record["status"] in ("waiting_policy", "waiting_setup"):
        doing = record["policy_note"] + "."
        step_text = f"{record['label']}. Next step {current + 1} of {total}: {step_label}"
    else:
        doing = f"Waiting its turn. {team.name(agent_slug)} is next."
        step_text = f"Queued. Next step {current + 1} of {total}: {step_label}"
    return {
        "key": f"job-{job.pk}",
        "kind": job.kind,
        "kind_label": job.get_kind_display(),
        "title": job.title or job.get_kind_display(),
        "url": _url("studio:job", workspace_id=job.workspace_id, job_id=job.pk),
        "status": "working" if working else ("paused" if record["status"].startswith("waiting_") else "queued"),
        "status_word": _JOB_WORD.get(record["status"], record["label"]),
        "policy_url": record["policy_url"],
        "policy_link": (record["policy_link"][:1].upper() + record["policy_link"][1:]) if record["policy_link"] else "",
        "agent": _agent_ref(agent_slug),
        "doing": doing,
        "platforms": [],
        "started_at": started.astimezone(zone) if started else None,
        "started_text": f"{started.astimezone(zone):%H:%M}" if started else "",
        "elapsed_text": elapsed((now - started).total_seconds()) if started else "",
        "stages": stages,
        "current_index": current,
        "current_label": step_label,
        "step_text": step_text,
        "long": total > 5,
        "sort": (0 if working else 1, started or now),
    }


# ---------------------------------------------------------------------------
# The roster
# ---------------------------------------------------------------------------


def _roster(workspace, visible_runs, running_agents: set, track_agents: dict, day_start, now):
    per_agent = {
        row["agent"]: row
        for row in visible_runs.values("agent").annotate(
            total=Count("id"),
            today=Count("id", filter=Q(started_at__gte=day_start)),
            last=Max("started_at"),
        )
    }
    latest: dict[str, dict] = {}
    for row in visible_runs.order_by("-started_at").values(
        "agent", "status", "summary", "started_at", "brief_id", "job_id"
    )[:400]:
        latest.setdefault(row["agent"], row)

    def run_url(row) -> str:
        if row.get("brief_id"):
            return _url("studio:detail", workspace_id=workspace.id, brief_id=row["brief_id"])
        if row.get("job_id"):
            return _url("studio:job", workspace_id=workspace.id, job_id=row["job_id"])
        return ""

    departments = []
    totals = {"working": 0, "stopped": 0, "idle": 0}
    for department, agents in team.by_department():
        rows = []
        for agent in agents:
            stats = per_agent.get(agent.slug, {})
            last_row = latest.get(agent.slug)
            track = track_agents.get(agent.slug)
            if agent.slug in running_agents or track is not None:
                state = "working"
            elif (
                last_row is not None
                and last_row["status"] == AgentRun.Status.FAILED
                and last_row["started_at"] >= now - STOPPED_WINDOW
            ):
                state = "stopped"
            else:
                state = "idle"
            totals[state] += 1
            last_at = None
            if state == "working" and track is not None:
                last_text, last_url = f"On “{track['title']}”", track["url"]
            elif last_row is not None:
                if last_row["status"] == AgentRun.Status.FAILED:
                    last_text = "Stopped part-way. Open the task to look."
                elif last_row["status"] == AgentRun.Status.RUNNING:
                    last_text = "Started a turn"
                else:
                    summary = safe_summary(last_row["summary"])
                    last_text = (summary[:117] + "…") if len(summary) > 118 else (summary or "Took a turn")
                last_url, last_at = run_url(last_row), last_row["started_at"]
            elif stats.get("last"):
                last_text, last_url, last_at = "Took a turn", "", stats["last"]
            elif agent.kind == "code":
                last_text, last_url = "Works by rules, so it costs nothing.", ""
            else:
                last_text, last_url = "Not needed yet.", ""
            last_ago = ago((now - last_at).total_seconds()) if last_at else ""
            rows.append(
                {
                    "slug": agent.slug,
                    "name": agent.name,
                    "initials": agent.initials,
                    "does": ROLE_COPY.get(agent.slug, agent.does),
                    "kind": agent.kind,
                    "state": state,
                    "state_word": {"working": "Working", "stopped": "Stopped", "idle": "Idle"}[state],
                    "last_text": last_text,
                    "last_url": last_url,
                    "last_ago": last_ago,
                    "last_at": last_at,
                    "turns_today": stats.get("today", 0),
                    "turns_total": stats.get("total", 0),
                }
            )
        working = sum(1 for row in rows if row["state"] == "working")
        stopped = sum(1 for row in rows if row["state"] == "stopped")
        departments.append(
            {
                "slug": department.slug,
                "name": department.name,
                "does": department.does,
                "agents": rows,
                "working": working,
                "stopped": stopped,
            }
        )
    return departments, totals


# ---------------------------------------------------------------------------
# Activity: the last 24 hours, hour by hour, in workspace time
# ---------------------------------------------------------------------------

CHART_HEIGHT = 96


def hour_buckets(now: datetime, zone) -> list[datetime]:
    """The starts (UTC) of the 24 local hours ending with the current one.

    Each bucket is one real hour, starting on a local hour boundary, so a day
    with a clock change still shows 24 real hours (one label repeats in
    autumn, one is skipped in spring) and a half-hour zone such as India's
    gets its own hours, not UTC's.
    """
    local = now.astimezone(zone)
    current = local.replace(minute=0, second=0, microsecond=0).astimezone(UTC)
    return [current - timedelta(hours=23 - index) for index in range(24)]


def _activity(visible_runs, now: datetime, zone) -> dict[str, Any]:
    starts = hour_buckets(now, zone)
    end = starts[-1] + timedelta(hours=1)
    aggregates: dict[str, Any] = {}
    for index, start in enumerate(starts):
        window = Q(started_at__gte=start, started_at__lt=start + timedelta(hours=1))
        aggregates[f"t{index}"] = Count("id", filter=window)
        aggregates[f"f{index}"] = Count("id", filter=window & Q(status=AgentRun.Status.FAILED))
    counts = visible_runs.filter(started_at__gte=starts[0], started_at__lt=end).aggregate(**aggregates)
    totals = [counts[f"t{i}"] or 0 for i in range(24)]
    failed = [counts[f"f{i}"] or 0 for i in range(24)]
    peak = max(totals)
    scale = _nice_max(peak) if peak else 4
    hours: list[dict[str, Any]] = []
    slot = 100 / 24
    gap = 0.6
    for index, start in enumerate(starts):
        local = start.astimezone(zone)
        local_end = (start + timedelta(hours=1)).astimezone(zone)
        height = round(totals[index] / scale * CHART_HEIGHT) if totals[index] else 0
        if totals[index] and height < 3:
            height = 3
        hours.append(
            {
                "index": index,
                "label": f"{local:%H:%M}",
                "range": f"{local:%H:%M}–{local_end:%H:%M}",
                "total": totals[index],
                "failed": failed[index],
                "is_now": index == 23,
                "height": height,
                "y": CHART_HEIGHT - height,
                "x": _num(index * slot + gap / 2),
                "slot_x": _num(index * slot),
                "width": _num(slot - gap),
                "slot": _num(slot),
            }
        )
    total, total_failed = sum(totals), sum(failed)
    if total:
        busiest = max(hours, key=lambda h: (h["total"], h["index"]))
        summary = f"Busiest at {busiest['label']} with {busiest['total']} {_plural(busiest['total'], 'turn')}."
        failed_hours = [h for h in hours if h["failed"]]
        if failed_hours:
            where = ", ".join(str(h["label"]) for h in failed_hours[:3])
            summary += f" {total_failed} {_plural(total_failed, 'turn')} stopped ({where})."
        else:
            summary += " None stopped."
    else:
        summary = "No turns in the last 24 hours."
    axis = []
    for index in (0, 6, 12, 18):
        axis.append({"label": hours[index]["label"], "pct": _num((index + 0.5) * slot), "align": "center"})
    axis[0]["align"] = "start"
    axis[0]["pct"] = "0"
    axis.append({"label": "Now", "pct": "100", "align": "end"})
    return {
        "hours": hours,
        "total": total,
        "failed": total_failed,
        "peak": peak,
        "scale": scale,
        "height": CHART_HEIGHT,
        "baseline": _num(CHART_HEIGHT + 0.5),
        "summary": f"Turns your team took each hour, last 24 hours. {summary}",
        "axis": axis,
    }


def _plural(count: int, word: str) -> str:
    return word if count == 1 else f"{word}s"


# ---------------------------------------------------------------------------
# Coming up: the next 24 hours
# ---------------------------------------------------------------------------


def _pct(when: datetime, start: datetime) -> float:
    value = (when - start).total_seconds() / 86400 * 100
    return round(max(0.0, min(100.0, value)) * 2) / 2  # half-percent steps keep the HTML stable between refreshes


def _lay_out(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Place the timeline's captions so none overlap.

    Events closer than ``CLUSTER_PCT`` share one marker. Each marker's caption
    (at most ``CAPTION_PCT`` of the timeline wide) goes below the line, or above
    it when below is taken; when both sides are taken it joins the previous
    marker, which becomes a numbered cluster that opens a list.
    """
    clusters: list[dict[str, Any]] = []
    for event in events:
        if clusters and event["pct"] - clusters[-1]["pct"] < CLUSTER_PCT:
            clusters[-1]["events"].append(event)
        else:
            clusters.append({"pct": event["pct"], "events": [event]})
    placed: list[dict[str, Any]] = []
    reach = {"down": -100.0, "up": 5.0}  # the "Now" label sits above the line at the far left
    for cluster in clusters:
        end = cluster["pct"] + CAPTION_PCT > 100
        if end:
            start, stop = cluster["pct"] - CAPTION_PCT, cluster["pct"] + 1
        else:
            start, stop = cluster["pct"] - 1, cluster["pct"] + CAPTION_PCT
        prefer = ("up", "down") if placed and not placed[-1]["up"] else ("down", "up")
        side = next((name for name in prefer if start >= reach[name]), None)
        if side is None and placed:
            placed[-1]["events"].extend(cluster["events"])
            continue
        side = side or "down"
        reach[side] = stop + 1
        placed.append({**cluster, "up": side == "up", "end": end})
    for index, cluster in enumerate(placed):
        cluster["id"] = f"tl-cluster-{index}"
        cluster["left"] = _num(cluster["pct"])
        cluster["single"] = len(cluster["events"]) == 1
        cluster["first"] = cluster["events"][0]
        cluster["count"] = len(cluster["events"])
    return placed


def _upcoming(workspace, now: datetime, zone, queued_count: int) -> dict[str, Any]:
    from apps.composer.models import PlatformPost

    end = now + timedelta(hours=24)
    local_now = now.astimezone(zone)
    events: list[dict[str, Any]] = []

    for routine in Routine.objects.filter(
        workspace=workspace, enabled=True, next_run_at__gte=now, next_run_at__lt=end
    ).order_by("next_run_at")[:20]:
        if routine.next_run_at is None:  # excluded by the filter; keeps the type checker sure
            continue
        when = routine.next_run_at.astimezone(zone)
        events.append(
            {
                "kind": "routine",
                "title": routine.display_title,
                "caption": "Routine",
                "at": when,
                "url": _url("studio:routines", workspace_id=workspace.id),
                "platforms": [],
            }
        )

    row = AgencySettings.objects.filter(workspace=workspace).first()
    if row is not None and row.autopilot_enabled:
        from .views_autopilot import next_plan_at

        row.workspace = workspace  # next_plan_at reads it; no second query
        when = next_plan_at(row)
        if now <= when < end:
            events.append(
                {
                    "kind": "routine",
                    "title": "Plan next week",
                    "caption": "Autopilot",
                    "at": when.astimezone(zone),
                    "url": _url("studio:autopilot", workspace_id=workspace.id),
                    "platforms": [],
                }
            )

    posts: dict[Any, dict[str, Any]] = {}
    for pp in (
        PlatformPost.objects.filter(post__workspace=workspace, status="scheduled")
        # A channel without its own time goes out at the post's, as the publisher and the calendar read it.
        .annotate(effective_at=Coalesce("scheduled_at", "post__scheduled_at"))
        .filter(effective_at__gte=now, effective_at__lt=end)
        .select_related("post", "social_account")
        .order_by("effective_at")[:40]
    ):
        if pp.effective_at is None:  # excluded by the filter; keeps the type checker sure
            continue
        when = pp.effective_at.astimezone(zone)
        key = (pp.post_id, when)
        if key not in posts:
            label = (pp.post.title or " ".join((pp.post.caption or "").split()) or "Your post")[:80]
            posts[key] = {
                "kind": "post",
                "title": label,
                "caption": "",
                "at": when,
                "url": _url("composer:compose_edit", workspace_id=workspace.id, post_id=pp.post_id),
                "platforms": [],
            }
        posts[key]["platforms"].append(pp.social_account.get_platform_display())
    for event in posts.values():
        event["platforms"] = sorted(set(event["platforms"]))
        event["caption"] = " · ".join(event["platforms"])
        events.append(event)

    for brief in (
        StudioBrief.objects.filter(
            workspace=workspace,
            status=StudioBrief.Status.READY,
            proposed_publish_at__gte=now,
            proposed_publish_at__lt=end,
        )
        .select_related("chosen_concept")
        .order_by("proposed_publish_at")[:20]
    ):
        if brief.proposed_publish_at is None:
            continue
        when = brief.proposed_publish_at.astimezone(zone)
        events.append(
            {
                "kind": "approve",
                "title": f"Approve by {when:%H:%M}",
                "caption": brief.title[:80],
                "at": when,
                "url": _url("studio:detail", workspace_id=workspace.id, brief_id=brief.pk),
                "platforms": [],
            }
        )

    if queued_count:
        events.append(
            {
                "kind": "queued",
                "title": f"{queued_count} queued",
                "caption": "Starts when a teammate is free",
                "at": local_now.replace(second=0, microsecond=0),  # stable between refreshes
                "url": "#team-working",
                "platforms": [],
            }
        )

    from apps.telegram.inbox import QUIET_END, QUIET_START

    events.sort(key=lambda event: (event["at"], event["kind"] != "queued"))
    in_quiet = False
    for event in events:
        # Never on top of the "Now" line: the first marker sits just after it.
        event["pct"] = max(1.5, _pct(event["at"], now))
        event["time_text"] = "Now" if event["kind"] == "queued" else _day_label(event["at"], local_now)
        # The timeline shows the clock time beside the caption; an approval's title already carries it.
        event["short_time"] = "" if event["kind"] in ("queued", "approve") else f"{event['at']:%H:%M}"
        quiet = event["kind"] != "queued" and (event["at"].hour >= QUIET_START or event["at"].hour < QUIET_END)
        # The phone list shows quiet hours as a divider before the first event inside them.
        event["quiet_before"] = quiet and not in_quiet
        in_quiet = quiet

    clusters = _lay_out(events)

    ticks = [{"label": "Now", "pct": "0", "align": "start"}]
    probe = local_now.replace(minute=0, second=0, microsecond=0).astimezone(UTC) + timedelta(hours=1)
    while probe < end:
        local = probe.astimezone(zone)
        if local.hour % 6 == 0:
            pct = _pct(probe, now)
            if 6 < pct < 94:
                ticks.append({"label": f"{local:%H:%M}", "pct": _num(pct), "align": "center"})
        probe += timedelta(hours=1)
    ticks.append({"label": f"{end.astimezone(zone):%H:%M}", "pct": "100", "align": "end"})

    quiet = []
    day = local_now.date() - timedelta(days=1)
    for _ in range(3):
        q_start = datetime.combine(day, datetime.min.time(), tzinfo=zone).replace(hour=QUIET_START)
        q_end = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=zone).replace(hour=QUIET_END)
        left, right = max(q_start, now), min(q_end, end)
        if left < right:
            l_pct, r_pct = _pct(left, now), _pct(right, now)
            quiet.append(
                {
                    "left": _num(l_pct),
                    "width": _num(r_pct - l_pct),
                }
            )
        day += timedelta(days=1)

    kinds = {event["kind"] for event in events}
    return {
        "events": events,
        "clusters": clusters,
        "ticks": ticks,
        "quiet": quiet,
        "kinds": sorted(kinds),
        "quiet_label": f"Quiet hours {QUIET_START:02d}:00–{QUIET_END:02d}:00",
        "next": next((event for event in events if event["kind"] != "queued"), None),
    }


# ---------------------------------------------------------------------------
# Recently finished and the latest post's receipt
# ---------------------------------------------------------------------------


def _recent(workspace, jobs, zone, local_now) -> list[dict[str, Any]]:
    from .opendots import task_status

    rows: list[dict[str, Any]] = []
    brief_words: dict[str, tuple[str, str]] = {
        StudioBrief.Status.READY.value: ("Ready for approval", "warning"),
        StudioBrief.Status.APPROVED.value: ("Approved", "success"),
        StudioBrief.Status.FAILED.value: ("Failed", "danger"),
    }
    for brief in (
        StudioBrief.objects.filter(workspace=workspace, status__in=tuple(brief_words))
        .select_related("chosen_concept")
        .order_by("-updated_at")[:RECENT_LIMIT]
    ):
        word, tone = brief_words[brief.status]
        when = brief.finished_at or brief.updated_at
        rows.append(
            {
                "title": brief.title,
                "kind_label": "Post",
                "url": _url("studio:detail", workspace_id=workspace.id, brief_id=brief.pk),
                "word": word,
                "tone": tone,
                "at": when,
            }
        )
    job_words = {
        "completed": ("Done", "success"),
        "failed": ("Failed", "danger"),
        "interrupted": ("Interrupted", "danger"),
        "paused": ("Paused", "neutral"),
        "cancelled": ("Cancelled", "neutral"),
    }
    for job in (
        jobs.filter(status__in=(AgencyJob.Status.DONE, AgencyJob.Status.FAILED, AgencyJob.Status.CANCELLED))
        .exclude(kind=AgencyJob.Kind.CHAT)
        .defer("input", "result")
        .order_by("-updated_at")[:RECENT_LIMIT]
    ):
        word, tone = job_words.get(task_status(job)["status"], ("Finished", "neutral"))
        rows.append(
            {
                "title": job.title or job.get_kind_display(),
                "kind_label": job.get_kind_display(),
                "url": _url("studio:job", workspace_id=workspace.id, job_id=job.pk),
                "word": word,
                "tone": tone,
                "at": job.finished_at or job.updated_at,
            }
        )
    rows.sort(key=lambda row: row["at"], reverse=True)
    rows = rows[:RECENT_LIMIT]
    for row in rows:
        local = row["at"].astimezone(zone)
        row["at"] = local
        row["time_text"] = local.strftime("%H:%M") if local.date() == local_now.date() else _day_label(local, local_now)
    return rows


#: A channel in any of these was approved, whether or not the gate stamped an approver.
_APPROVED_ROWS = frozenset({"approved", "scheduled", "publishing", "published", "failed"})


def _receipt(workspace, zone, local_now) -> dict[str, Any] | None:
    """The team's latest post, from draft to published: the delivery receipt (DESIGN_SYSTEM.md 14.3)."""
    from apps.approvals.gate import effective_publish_at
    from apps.composer.models import PlatformPost

    brief = (
        StudioBrief.objects.filter(
            workspace=workspace,
            post__isnull=False,
            status__in=(StudioBrief.Status.READY, StudioBrief.Status.APPROVED),
        )
        .select_related("chosen_concept")
        .order_by("-updated_at")
        .first()
    )
    if brief is None or brief.post_id is None:
        return None
    rows = list(
        PlatformPost.objects.filter(post_id=brief.post_id)
        .select_related("post", "social_account", "approved_by")
        .order_by("pk")
    )
    if not rows:
        return None

    def when(value) -> str:
        return _day_label(value.astimezone(zone), local_now) if value else ""

    platforms = " and ".join(sorted({row.social_account.get_platform_display() for row in rows}))
    statuses = {row.status for row in rows}
    steps = [{"state": "done", "text": "Draft ready", "meta": when(brief.finished_at)}]
    # Whether it was approved comes from what happened to the post: the gate stamps who approved
    # and when only where dashboard approval is enforced, and keeps the stamp while the client decides.
    if "pending_client" in statuses:
        steps.append({"state": "needs-you", "text": "Waiting for the client", "meta": ""})
    elif brief.status == StudioBrief.Status.APPROVED or statuses & _APPROVED_ROWS:
        stamped = next((row for row in rows if row.approved_at), None)
        who = ""
        if stamped is not None and stamped.approved_by is not None:
            who = (getattr(stamped.approved_by, "name", "") or "").split(" ")[0]
        steps.append(
            {
                "state": "done",
                "text": f"Approved by {who}" if who else "Approved",
                "meta": when(stamped.approved_at) if stamped is not None else "",
            }
        )
    else:
        steps.append({"state": "needs-you", "text": "Waiting for your approval", "meta": ""})
    scheduled = next(
        (
            row
            for row in rows
            if row.status in ("scheduled", "publishing", "published", "failed") and effective_publish_at(row)
        ),
        None,
    )
    if scheduled is not None:
        state = "current" if scheduled.status == "scheduled" else "done"
        steps.append(
            {"state": state, "text": f"Scheduled for {platforms}", "meta": when(effective_publish_at(scheduled))}
        )
    else:
        steps.append({"state": "pending", "text": f"Scheduled for {platforms}", "meta": "Pending"})
    published = next((row for row in rows if row.status == "published"), None)
    if published is not None:
        steps.append({"state": "done", "text": "Published", "meta": when(published.published_at)})
    elif "publishing" in statuses:
        steps.append({"state": "current", "text": "Publishing", "meta": "Now"})
    elif "failed" in statuses:
        steps.append({"state": "failed", "text": "Did not publish", "meta": "Open the post to look"})
    else:
        steps.append({"state": "pending", "text": "Published", "meta": "Pending"})
    return {
        "title": brief.title,
        "url": _url("studio:detail", workspace_id=workspace.id, brief_id=brief.pk),
        "steps": steps,
    }


# ---------------------------------------------------------------------------
# The snapshot
# ---------------------------------------------------------------------------


def snapshot(workspace, *, now: datetime | None = None) -> dict[str, Any]:
    """Everything the live team view draws for ``workspace``; cached for a few seconds unless ``now`` is given."""
    if now is None:
        key = f"{CACHE_PREFIX}{workspace.pk}"
        found = cache.get(key)
        if found is not None:
            return found
        data = _build(workspace, timezone.now())
        cache.set(key, data, CACHE_SECONDS)
        return data
    return _build(workspace, now)


def forget(workspace) -> None:
    """Drop the cached snapshot (tests, or after a change a person should see at once)."""
    cache.delete(f"{CACHE_PREFIX}{workspace.pk}")


def _build(workspace, now: datetime) -> dict[str, Any]:
    from apps.composer.models import PlatformPost

    from .opendots import task_status

    zone = _zone(workspace)
    local_now = now.astimezone(zone)
    day_start = datetime.combine(local_now.date(), datetime.min.time(), tzinfo=zone)
    since_24h = now - timedelta(hours=24)
    since_needs = now - timedelta(days=NEEDS_YOU_DAYS)

    health = _health(now)

    # Counts (exact, whatever the track cap).
    brief_counts = StudioBrief.objects.filter(workspace=workspace).aggregate(
        working=Count("id", filter=Q(status=StudioBrief.Status.WORKING)),
        queued=Count("id", filter=Q(status=StudioBrief.Status.QUEUED)),
        done_today=Count(
            "id",
            filter=Q(
                status__in=(StudioBrief.Status.READY, StudioBrief.Status.APPROVED),
                finished_at__gte=day_start,
                finished_at__lte=now,
            ),
        ),
        ready_24h=Count(
            "id",
            filter=Q(
                status__in=(StudioBrief.Status.READY, StudioBrief.Status.APPROVED),
                finished_at__gte=since_24h,
                finished_at__lte=now,
            ),
        ),
        failed_recent=Count("id", filter=Q(status=StudioBrief.Status.FAILED, updated_at__gte=since_needs)),
    )
    jobs = chat.web_jobs(AgencyJob.objects.filter(workspace=workspace))
    job_counts = jobs.aggregate(
        working=Count("id", filter=Q(status=AgencyJob.Status.WORKING)),
        queued=Count("id", filter=Q(status=AgencyJob.Status.QUEUED)),
        done_today=Count(
            "id",
            filter=Q(status=AgencyJob.Status.DONE, finished_at__gte=day_start, finished_at__lte=now)
            & ~Q(kind=AgencyJob.Kind.CHAT),
        ),
    )
    approvals = (
        PlatformPost.objects.filter(post__workspace=workspace, status="pending_review")
        .values("post_id")
        .distinct()
        .count()
    )
    try:
        from apps.blog.models import BlogPost

        approvals += BlogPost.objects.filter(workspace=workspace, status=BlogPost.Status.PENDING_REVIEW).count()
    except Exception:  # the blog is optional for a workspace; never break the team view over it
        pass
    attention = [
        job
        for job in jobs.filter(
            status__in=(AgencyJob.Status.FAILED, AgencyJob.Status.CANCELLED), updated_at__gte=since_needs
        )
        .defer("input", "result")
        .order_by("-updated_at")[:60]
        if task_status(job)["status"] in ("paused", "failed", "interrupted")
    ]
    stopped_tasks = len(attention) + (brief_counts["failed_recent"] or 0)

    # Live turns: who is mid-turn right now.
    visible_runs = chat.web_agent_runs(AgentRun.objects.filter(workspace=workspace))
    running: dict[tuple[str, Any], dict] = {}
    running_agents: set[str] = set()
    for row in (
        visible_runs.filter(status=AgentRun.Status.RUNNING, started_at__gte=now - STALE_RUN)
        .order_by("-started_at")
        .values("agent", "brief_id", "job_id")[:100]
    ):
        running_agents.add(row["agent"])
        if row["brief_id"]:
            running.setdefault(("brief", row["brief_id"]), row)
        if row["job_id"]:
            running.setdefault(("job", row["job_id"]), row)

    working_first = Case(When(status="working", then=Value(0)), default=Value(1), output_field=IntegerField())
    tracks: list[dict[str, Any]] = []
    for brief in (
        StudioBrief.objects.filter(workspace=workspace, status__in=StudioBrief.ACTIVE_STATUSES)
        .select_related("chosen_concept")
        .prefetch_related("social_accounts")
        .order_by(working_first, "created_at")[:MAX_TRACKS]
    ):
        tracks.append(_post_track(brief, running, now, zone))
    for job in (
        jobs.filter(status__in=AgencyJob.ACTIVE_STATUSES)
        .defer("input", "result")
        .order_by(working_first, "created_at")[:MAX_TRACKS]
    ):
        track = _job_track(job, running, now, zone)
        if track is not None:
            tracks.append(track)
    tracks.sort(key=lambda track: track["sort"])
    tracks = tracks[:MAX_TRACKS]
    for track in tracks:
        track.pop("sort", None)

    working_count = (brief_counts["working"] or 0) + (job_counts["working"] or 0)
    queued_count = (brief_counts["queued"] or 0) + (job_counts["queued"] or 0)
    hidden_tracks = max(0, working_count + queued_count - len(tracks))
    track_agents = {track["agent"]["slug"]: track for track in tracks if track["status"] == "working"}

    departments, agent_totals = _roster(workspace, visible_runs, running_agents, track_agents, day_start, now)
    activity = _activity(visible_runs, now, zone)
    paused_tracks = sum(1 for track in tracks if track["status"] == "paused")
    upcoming = _upcoming(workspace, now, zone, max(0, queued_count - paused_tracks))
    recent = _recent(workspace, jobs, zone, local_now)
    receipt = _receipt(workspace, zone, local_now)

    counts = {
        "working": working_count,
        "queued": queued_count,
        "done_today": (brief_counts["done_today"] or 0) + (job_counts["done_today"] or 0),
        "needs_you": approvals + stopped_tasks,
        "approvals": approvals,
        "stopped_tasks": stopped_tasks,
        "posts_ready_24h": brief_counts["ready_24h"] or 0,
    }
    busiest = next((track for track in tracks if track["status"] == "working"), tracks[0] if tracks else None)
    announce = (
        f"{counts['working']} working, {counts['queued']} queued, {counts['done_today']} done today, "
        f"{counts['needs_you']} {'needs' if counts['needs_you'] == 1 else 'need'} you. Team {health['label'].lower()}."
    )
    data = {
        "generated_at": now,
        "tzname": str(zone),
        "today_text": f"{local_now:%a} {local_now.day} {local_now:%b}",
        "health": health,
        "counts": counts,
        "agents": agent_totals,
        "agent_count": len(team.AGENTS),
        "tracks": tracks,
        "hidden_tracks": hidden_tracks,
        "busiest": busiest,
        "idle_text": _idle_text(upcoming["next"]),
        "departments": departments,
        "activity": activity,
        "upcoming": upcoming,
        "recent": recent,
        "receipt": receipt,
        "announce": announce,
        "approvals_url": _approvals_url(workspace),
        "team_url": _url("studio:team", workspace_id=workspace.id),
    }
    data["digest"] = digest(data)
    return data


def _idle_text(next_event: dict[str, Any] | None) -> str:
    if next_event is not None:
        return f"Nothing is running right now. Next: {next_event['title']}, {next_event['time_text']}."
    return "Nothing is running right now. Ask for something on Home and the team starts at once."


def for_viewer(data: dict[str, Any], workspace, *, can_create: bool) -> dict[str, Any]:
    """The snapshot as a person without ``create_posts`` may see it; the cached snapshot is left as it is.

    The Routines, Autopilot and composer pages refuse such a person, and Home
    leaves routines out for them, so a routine keeps its place on the timeline
    but not its title (its instruction), and nothing links to those pages.
    """
    if can_create:
        return data
    closed = {_url("studio:routines", workspace_id=workspace.id), _url("studio:autopilot", workspace_id=workspace.id)}
    events = []
    for original in data["upcoming"]["events"]:
        event = dict(original)
        if event["kind"] == "routine" and event["caption"] == "Routine":  # the autopilot plan's title is fixed copy
            event.update(title="Routine", caption="")
        if event["kind"] in ("routine", "post"):
            event["url"] = ""
        events.append(event)
    upcoming = {
        **data["upcoming"],
        "events": events,
        "clusters": _lay_out(events),  # placed by time alone, so where they were
        "next": next((event for event in events if event["kind"] != "queued"), None),
    }
    tracks = [{**track, "policy_url": ""} if track["policy_url"] in closed else track for track in data["tracks"]]
    busiest_key = data["busiest"]["key"] if data["busiest"] else None
    shown = {
        **data,
        "upcoming": upcoming,
        "tracks": tracks,
        "busiest": next((track for track in tracks if track["key"] == busiest_key), None),
        "idle_text": _idle_text(upcoming["next"]),
    }
    shown["digest"] = digest(shown)
    return shown


def _approvals_url(workspace) -> str:
    base = _url("calendar:calendar", workspace_id=workspace.id)
    return f"{base}?mode=list&tab=approvals" if base else ""


def digest(data: dict[str, Any]) -> str:
    """A short fingerprint of what the board shows, so a refresh that changes nothing swaps nothing.

    Relative times (the check-in age, how long a task has run, when an agent
    last worked) and the moment the snapshot was built are left out: they move
    on every refresh, and the page keeps them counting itself
    (static/js/live_board.js) from the absolute times that are in.
    """
    encoded = json.dumps(_stable(data), default=str, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(encoded.encode(), usedforsecurity=False).hexdigest()[:16]


_VOLATILE = frozenset({"generated_at", "digest", "age_seconds", "detail", "elapsed_text", "last_ago"})


def _stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _stable(item) for key, item in value.items() if key not in _VOLATILE}
    if isinstance(value, list):
        return [_stable(item) for item in value]
    return value
