"""What the agency home shows: what needs a person, what the team is doing, this week, what it learned.

Every number here is a plain query on this workspace's rows, cheap enough to
run on each page view. Nothing calls a model.
"""

from __future__ import annotations

import zoneinfo
from datetime import datetime, timedelta
from typing import Any

from django.db.models import Count, Q
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from . import budget, memory, team
from .models import AgencyJob, AgencySettings, AgentRun, StudioBrief

#: The post pipeline's stage → the agent at work during it.
STAGE_AGENT = {
    "strategy": "strategist",
    "copy": "copywriter",
    "art": "art_director",
    "picture": "illustrator",
    "render": "designer",
    "review": "reviewer",
    "channel": "channel_editor",
    "qa": "qa_inspector",
    "schedule": "scheduler",
    "handoff": "producer",
}


def _zone(workspace):
    try:
        return zoneinfo.ZoneInfo(workspace.effective_timezone or "UTC")
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return zoneinfo.ZoneInfo("UTC")


def _maybe_url(name: str, **kwargs) -> str | None:
    try:
        return reverse(name, kwargs=kwargs)
    except NoReverseMatch:
        return None


def tabs(workspace, active: str) -> list[dict[str, Any]]:
    """The agency's tabs (pages that are not available simply don't show)."""
    items = [
        ("overview", "Overview", "studio:index"),
        ("team", "Team", "studio:team"),
        ("memory", "Creative memory", "studio:memory"),
        ("autopilot", "Autopilot", "studio:autopilot"),
        ("thread", "Ask the team", "studio:thread"),
        ("brand", "Brand", "studio:brand"),
    ]
    out = []
    for key, label, name in items:
        url = _maybe_url(name, workspace_id=workspace.id)
        if url:
            out.append({"key": key, "label": label, "url": url, "active": key == active})
    return out


def _platforms(brief) -> str:
    return " · ".join(sorted({a.get_platform_display() for a in brief.social_accounts.all()}))


def waiting(workspace) -> list[dict[str, Any]]:
    """Work the team finished that is waiting for a person, newest first."""
    rows = []
    briefs = (
        StudioBrief.objects.filter(workspace=workspace, status=StudioBrief.Status.READY)
        .select_related("graphic", "post")
        .prefetch_related("social_accounts")
        .order_by("proposed_publish_at", "-finished_at")[:8]
    )
    now = timezone.now()
    for brief in briefs:
        review = brief.review_notes or {}
        proposed = brief.proposed_publish_at
        rows.append(
            {
                "kind": "post",
                "brief": brief,
                "title": brief.title,
                "where": _platforms(brief),
                "proposed": proposed,
                "proposed_in_future": bool(proposed and proposed > now + timedelta(minutes=5)),
                "score": review.get("score"),
                "flags": len(review.get("risk_flags") or []),
                "qa_notes": sum(1 for c in (review.get("qa") or {}).get("checks", []) if not c.get("passed")),
            }
        )
    try:
        from apps.blog.models import BlogPost
        from apps.blog.seo import score_post

        for post in (
            BlogPost.objects.filter(workspace=workspace, status=BlogPost.Status.PENDING_REVIEW)
            .select_related("site", "featured_image")
            .order_by("-updated_at")[:4]
        ):
            report = score_post(post)
            rows.append(
                {
                    "kind": "blog",
                    "blog_post": post,
                    "title": post.title,
                    "where": post.site.site_url.replace("https://", "").replace("www.", "").rstrip("/") + "/blog",
                    "score": report.score,
                    "words": report.words,
                }
            )
    except Exception:  # the blog is optional for a workspace; never break the home page over it
        pass
    return rows


def _job_agent(job: AgencyJob) -> str:
    from .engine import job_type

    try:
        stage = job_type(job.kind).stage(job.stage)
    except KeyError:
        stage = None
    return stage.agent if stage else "account_manager"


def at_work(workspace, limit: int = 6) -> list[dict[str, Any]]:
    """Who is working right now, then who finished most recently."""
    rows: list[dict[str, Any]] = []
    for brief in StudioBrief.objects.filter(workspace=workspace, status__in=StudioBrief.ACTIVE_STATUSES).order_by(
        "-updated_at"
    )[:limit]:
        agent = team.get(STAGE_AGENT.get(brief.stage, "strategist"))
        rows.append(
            {
                "agent": agent,
                "doing": f"Working on “{brief.title}”"
                if brief.status == StudioBrief.Status.WORKING
                else f"Next up: “{brief.title}”",
                "state": "working" if brief.status == StudioBrief.Status.WORKING else "queued",
                "url": reverse("studio:detail", kwargs={"workspace_id": workspace.id, "brief_id": brief.pk}),
            }
        )
    for job in AgencyJob.objects.filter(workspace=workspace, status__in=AgencyJob.ACTIVE_STATUSES).order_by(
        "-updated_at"
    )[: max(0, limit - len(rows))]:
        rows.append(
            {
                "agent": team.get(_job_agent(job)),
                "doing": job.title or job.get_kind_display(),
                "state": "working" if job.status == AgencyJob.Status.WORKING else "queued",
                "url": _maybe_url("studio:job", workspace_id=workspace.id, job_id=job.pk),
            }
        )
    if len(rows) < limit:
        for run in (
            AgentRun.objects.filter(workspace=workspace, status=AgentRun.Status.SUCCEEDED)
            .exclude(summary="")
            .order_by("-finished_at")[: limit - len(rows)]
        ):
            rows.append({"agent": team.get(run.agent), "doing": run.summary, "state": "done", "url": None})
    return rows


def week(workspace) -> list[dict[str, Any]]:
    """The next seven days: what is planned, waiting or scheduled on each day."""
    from apps.composer.models import PlatformPost

    zone = _zone(workspace)
    today = timezone.now().astimezone(zone).date()
    start = datetime.combine(today, datetime.min.time(), tzinfo=zone)
    end = start + timedelta(days=7)
    days: list[dict[str, Any]] = [{"date": today + timedelta(days=i), "items": []} for i in range(7)]

    def add(when, label, tone):
        local = when.astimezone(zone).date()
        index = (local - today).days
        if 0 <= index < 7:
            days[index]["items"].append({"label": label, "tone": tone, "time": when.astimezone(zone)})

    for brief in StudioBrief.objects.filter(
        workspace=workspace,
        proposed_publish_at__gte=start,
        proposed_publish_at__lt=end,
        status__in=(
            StudioBrief.Status.PLANNED,
            StudioBrief.Status.QUEUED,
            StudioBrief.Status.WORKING,
            StudioBrief.Status.READY,
        ),
    ).only("idea", "design_spec", "post_copy", "chosen_concept", "proposed_publish_at", "status"):
        tone = "ready" if brief.status == StudioBrief.Status.READY else "planned"
        add(brief.proposed_publish_at, brief.title[:60], tone)
    for pp in (
        PlatformPost.objects.filter(
            post__workspace=workspace, status="scheduled", scheduled_at__gte=start, scheduled_at__lt=end
        )
        .select_related("post", "social_account")
        .order_by("scheduled_at")[:40]
    ):
        add(pp.scheduled_at, (pp.post.title or pp.post.caption)[:60], "scheduled")
    for day in days:
        day["items"].sort(key=lambda item: item["time"])
    return days


def stats(workspace) -> dict[str, Any]:
    from apps.composer.models import PlatformPost

    zone = _zone(workspace)
    now = timezone.now()
    local = now.astimezone(zone)
    monday = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    out_week = (
        PlatformPost.objects.filter(post__workspace=workspace, status="published", published_at__gte=monday)
        .values("social_account__platform")
        .annotate(n=Count("id"))
    )
    by_platform = {row["social_account__platform"]: row["n"] for row in out_week}
    active_briefs = StudioBrief.objects.filter(workspace=workspace, status__in=StudioBrief.ACTIVE_STATUSES).count()
    active_jobs = AgencyJob.objects.filter(workspace=workspace, status__in=AgencyJob.ACTIVE_STATUSES).count()
    ready = StudioBrief.objects.filter(workspace=workspace, status=StudioBrief.Status.READY).count()
    try:
        from apps.blog.models import BlogPost

        blogs = BlogPost.objects.filter(workspace=workspace, status=BlogPost.Status.PENDING_REVIEW).count()
    except Exception:
        blogs = 0
    spend = budget.month_spend(workspace)
    limit = budget.monthly_budget(workspace)
    return {
        "waiting": ready + blogs,
        "waiting_posts": ready,
        "waiting_blogs": blogs,
        "working": active_briefs + active_jobs,
        "out_this_week": sum(by_platform.values()),
        "out_by_platform": by_platform,
        "spend": spend,
        "budget": limit,
        "spend_pct": int(min(100, (spend / limit * 100) if limit else 0)),
    }


def learned(workspace) -> list[str]:
    """A few plain lines the team learned, newest first."""
    lines: list[str] = []
    job = (
        AgencyJob.objects.filter(
            workspace=workspace, kind__in=("learn", "plan", "report"), status=AgencyJob.Status.DONE
        )
        .order_by("-finished_at")
        .first()
    )
    for line in (job.result or {}).get("learned", []) if job else []:
        if isinstance(line, str) and line.strip():
            lines.append(line.strip())
    if len(lines) < 3:
        for hook in memory.winning_hooks(workspace, limit=3 - len(lines)):
            lines.append(f"Your best opener lately: “{hook}”")
    return lines[:4]


def settings_for(workspace) -> AgencySettings | None:
    return AgencySettings.objects.filter(workspace=workspace).first()


def overview(workspace) -> dict[str, Any]:
    return {
        "waiting": waiting(workspace),
        "at_work": at_work(workspace),
        "week": week(workspace),
        "stats": stats(workspace),
        "learned": learned(workspace),
        "agency_settings": settings_for(workspace),
        "agent_count": len(team.AGENTS),
        "inbox_drafts": _inbox_drafts(workspace),
    }


def _inbox_drafts(workspace) -> int:
    try:
        from apps.inbox.models import InboxReply

        return (
            InboxReply.objects.filter(inbox_message__workspace=workspace, status="draft")
            .filter(~Q(drafted_by=""))
            .count()
        )
    except Exception:
        return 0
