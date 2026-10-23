"""The morning briefing: what is waiting, what goes out, what the team made, what needs a look.

Built from the same cheap queries as the agency home; no model is called. The
routine (area C) calls :func:`send_daily`; a person can also read
:func:`build` on the web. Telegram delivery goes through the manager inbox so
muted people still get this one message a day.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.utils import timezone

from . import chat, dashboard
from .models import AgencyJob, AgencySettings, StudioBrief

logger = logging.getLogger(__name__)

__all__ = ["build", "send_daily"]


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


def _task_counts(workspace) -> dict[str, int]:
    from .opendots import task_status

    counts = {"paused": 0, "failed": 0, "interrupted": 0}
    rows = chat.web_jobs(
        AgencyJob.objects.filter(
            workspace=workspace,
            status__in=(AgencyJob.Status.FAILED, AgencyJob.Status.CANCELLED),
            updated_at__gte=timezone.now() - timedelta(days=14),
        )
    ).order_by("-updated_at")[:200]
    for job in rows:
        status = task_status(job)["status"]
        if status in counts:
            counts[status] += 1
    return counts


def build(workspace) -> dict[str, Any]:
    """Plain lines for one workspace. ``waiting`` carries the dashboard rows for the posts a person must review."""
    from apps.telegram import inbox

    from .readiness import operational_readiness
    from .views_autopilot import next_plan_at

    zone = inbox.zone_of(workspace)
    now = timezone.now()
    pending = dashboard.waiting(workspace)
    waiting = [row for row in pending if row["kind"] == "post"]
    blogs = sum(1 for row in pending if row["kind"] == "blog")
    days = dashboard.week(workspace)
    today = days[0]["items"] if days else []
    going_out = [item for item in today if item["tone"] == "scheduled"]
    made = StudioBrief.objects.filter(
        workspace=workspace,
        status__in=(StudioBrief.Status.READY, StudioBrief.Status.APPROVED),
        finished_at__gte=now - timedelta(hours=24),
    ).count()
    working = [row for row in dashboard.at_work(workspace) if row["state"] in {"working", "queued"}]
    tasks = _task_counts(workspace)
    blockers = list(operational_readiness(workspace).get("blockers") or [])
    settings_row = AgencySettings.objects.filter(workspace=workspace).select_related("workspace").first()
    next_run = next_plan_at(settings_row) if settings_row is not None and settings_row.autopilot_enabled else None

    lines = [f"Good morning. Here is {workspace.name} today."]
    if waiting:
        titles = "; ".join(str(row["title"])[:60] for row in waiting[:3])
        more = f" and {len(waiting) - 3} more" if len(waiting) > 3 else ""
        lines.append(f"Waiting for you: {_plural(len(waiting), 'post')} — {titles}{more}.")
    else:
        lines.append("Nothing is waiting for your approval.")
    if blogs:
        lines.append(f"Also waiting: {_plural(blogs, 'blog article')}.")
    if going_out:
        when = ", ".join(f"{item['time']:%H:%M} {str(item['label'])[:40]}" for item in going_out[:3])
        lines.append(f"Going out today: {_plural(len(going_out), 'post')} — {when}.")
    else:
        lines.append("Nothing is scheduled to go out today.")
    lines.append(f"Made since yesterday: {_plural(made, 'draft')}.")
    if working:
        lines.append(f"Working now: {_plural(len(working), 'item')}.")
    problems = [f"{count} {status}" for status, count in tasks.items() if count]
    if problems:
        lines.append("Needs a look: " + ", ".join(problems) + ".")
    lines.extend(blockers)
    if next_run is not None:
        lines.append(f"Next plan: {next_run:%A %H:%M} ({zone.key}).")
    links = {
        "approvals": chat.absolute_url(inbox.approvals_path(workspace.pk)),
        "home": chat.absolute_url(inbox.home_path(workspace.pk)),
    }
    return {
        "lines": lines,
        "text": "\n".join(lines),
        "waiting": waiting,
        "links": links,
        "counts": {"waiting": len(waiting), "going_out": len(going_out), "made": made, **tasks},
        "day": timezone.localtime(now, zone).date().isoformat(),
    }


def send_daily(workspace, *, routine=None) -> int:
    """Send today's briefing once per workspace-local day. Returns how many people were told."""
    from apps.notifications.engine import notify
    from apps.notifications.models import EventType, Notification
    from apps.telegram import inbox
    from apps.telegram.outbox import link_button, link_keyboard

    from .autopilot import _approvers

    data = build(workspace)
    day = data["day"]
    told: set = set()
    already = Notification.objects.filter(
        event_type=EventType.DAILY_BRIEFING, data__workspace_id=str(workspace.pk), data__day=day
    ).exists()
    if not already:
        for person in _approvers(workspace):
            try:
                notify(
                    user=person,
                    event_type=EventType.DAILY_BRIEFING,
                    title=f"Your morning briefing · {workspace.name}"[:255],
                    body=data["text"],
                    data={
                        "workspace_id": str(workspace.pk),
                        "day": day,
                        "routine_id": str(routine.pk) if routine is not None else "",
                        "action_url": data["links"]["approvals"],
                    },
                )
                told.add(person.pk)
            except Exception:
                logger.exception("Briefing could not be recorded for user %s", person.pk)
    keyboard = link_keyboard(
        link_button("Open approvals", inbox.approvals_path(workspace.pk)),
        link_button("Open Home", inbox.home_path(workspace.pk)),
    )
    try:
        count = inbox.tell(
            workspace,
            data["text"],
            source_key=f"briefing:{day}",
            event="daily_briefing",
            reply_markup=keyboard,
            include_muted=True,
        )
        first = data["waiting"][0]["brief"] if data["waiting"] else None
        post = first.post if first is not None and first.post_id else None
        if post is not None and post.workspace_id == workspace.pk:
            inbox.tell(
                workspace,
                "",
                source_key=f"briefing:{day}:first-post",
                event="daily_briefing",
                post=post,
                include_muted=True,
            )
    except Exception:
        logger.exception("Briefing could not be queued to Telegram for workspace %s", workspace.pk)
        count = 0
    return max(len(told), count)
