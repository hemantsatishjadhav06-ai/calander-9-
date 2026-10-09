"""The ``report`` job: the weekly plain-language report for the client.

Two stages, one worker task each:

1. **listen** — the audience listener reads the week's comments, messages and
   reviews (scrubbed of names, handles, emails, phone numbers and links, as
   for the plan). Skipped, with a SKIPPED timeline row, when nobody wrote;
   a failure only means the report says less about the audience.
2. **write** — code counts the facts (what went out per network, the post that
   did best against its own account's usual, what is planned or scheduled
   next) and the client reporter turns them into a short report. A week with
   nothing at all to report is written by code, at no cost.

The report is stored in ``job.result`` as ``{"title", "summary", "sections":
[{"kind", "heading", "body"}], "period", "went_out"}``; ``apps.studio.reports``
is the only reader that shows it to anyone, and copies out just those words
and numbers. The reporter is told nothing about costs, internal notes or how
the team works, so it can't repeat them. Nothing here approves, schedules or
publishes.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import date, datetime, time, timedelta
from typing import Any

from django.utils import timezone

from .. import budget, engine, performance
from ..models import AgencyJob, AgentRun, StudioBrief
from ..reports import network_name
from ..roles import base, insights
from .plan import audience_messages, audience_text, zone_of

logger = logging.getLogger(__name__)

#: Openings of posts shown to the reporter (per section).
MAX_LISTED = 5


def report_window(job: AgencyJob) -> tuple[datetime, datetime]:
    """The reported week: ``input["week_start"]`` (a Monday, workspace time) for 7 days, else the last 7 days."""
    zone = zone_of(job.workspace)
    raw = (job.input or {}).get("week_start")
    if raw:
        try:
            start = datetime.combine(date.fromisoformat(str(raw)), time.min).replace(tzinfo=zone)
        except ValueError as exc:
            raise engine.JobError("This report doesn't say which week it is for. Ask for it again.") from exc
        return start, start + timedelta(days=7)
    end = timezone.now().astimezone(zone)
    return end - timedelta(days=7), end


def period_label(start: datetime, end: datetime) -> str:
    last = end - timedelta(seconds=1)
    if start.month == last.month:
        return f"{start.day}–{last.day} {last:%B}"
    return f"{start.day} {start:%B} – {last.day} {last:%B}"


def _skip(job: AgencyJob, agent: str, summary: str) -> None:
    run = engine.begin(job, agent)
    engine.end(run, summary=summary, status=AgentRun.Status.SKIPPED)


def stage_listen(job: AgencyJob) -> str:
    from ..brand_defaults import ensure_profile

    workspace = job.workspace
    if not budget.can_spend(workspace):
        raise engine.JobError(budget.over_budget_message(workspace))
    start, end = report_window(job)
    messages = audience_messages(workspace, start=start, end=end)
    audience: dict[str, Any] | None = None
    if not messages:
        _skip(job, "audience_listener", "Nobody commented, messaged or reviewed this week.")
    else:
        profile = ensure_profile(workspace)
        try:
            run, result = engine.call(
                job,
                "audience_listener",
                lambda: insights.audience_listener(profile, messages, days=7),
                effort=insights.AUDIENCE_LISTENER_EFFORT,
            )
        except engine.JobError:
            logger.info("Report %s: the audience listener failed; reporting without it", job.pk)
        else:
            audience = result.output.model_dump()
            engine.end(
                run, summary=result.output.summary, output={**audience, "messages_read": len(messages)}, result=result
            )
    engine.update_state(job, audience=audience, messages=len(messages))
    return "write"


def _opening(caption: str) -> str:
    return ((caption or "").strip().splitlines() or [""])[0][:200]


def report_facts(workspace, start: datetime, end: datetime) -> dict[str, Any]:
    """Everything code knows about the week, counted from this workspace's own rows."""
    from apps.composer.models import PlatformPost

    published = list(
        PlatformPost.objects.filter(
            post__workspace=workspace,
            status=PlatformPost.Status.PUBLISHED,
            published_at__gte=start,
            published_at__lt=end,
        )
        .select_related("post", "social_account")
        .order_by("published_at")
    )
    went_out = Counter(network_name(pp.social_account.platform) for pp in published)
    openings: list[tuple[str, str]] = []
    for pp in published:
        text = _opening(pp.platform_specific_caption or pp.post.caption)
        if text and text not in [o[1] for o in openings]:
            openings.append((network_name(pp.social_account.platform), text))

    best = None
    # Ranked against each account's whole recent history, then narrowed to the week.
    measured = [
        m for m in performance.measured(workspace=workspace) if m.ratio is not None and start <= m.published_at < end
    ]
    if measured:
        top = max(measured, key=lambda m: m.ratio or 0)
        best_pp = next((p for p in published if p.pk == top.platform_post_id), None)
        if best_pp is not None:
            best = {
                "network": network_name(top.platform),
                "ratio": round(top.ratio or 0, 1),
                "better_than": round((top.percentile or 0) * 100),
                "opening": _opening(best_pp.platform_specific_caption or best_pp.post.caption),
            }

    next_end = end + timedelta(days=7)
    upcoming_briefs = list(
        StudioBrief.objects.filter(
            workspace=workspace,
            proposed_publish_at__gte=end,
            proposed_publish_at__lt=next_end,
            status__in=(
                StudioBrief.Status.PLANNED,
                StudioBrief.Status.QUEUED,
                StudioBrief.Status.WORKING,
                StudioBrief.Status.READY,
            ),
        ).order_by("proposed_publish_at")
    )
    scheduled = PlatformPost.objects.filter(
        post__workspace=workspace,
        status=PlatformPost.Status.SCHEDULED,
        scheduled_at__gte=max(end, timezone.now()),
        scheduled_at__lt=next_end,
    ).count()
    return {
        "went_out": dict(went_out),
        "openings": openings[:MAX_LISTED],
        "best": best,
        "planned": len(upcoming_briefs),
        "planned_topics": [brief.title[:160] for brief in upcoming_briefs[:MAX_LISTED]],
        "scheduled": scheduled,
    }


def facts_text(facts: dict[str, Any], label: str) -> str:
    """The facts as the reporter reads them. Captions and topics are wrapped as untrusted."""
    went = base.bullets(f"{name}: {count} post(s)" for name, count in facts["went_out"].items())
    openings = "\n".join(
        base.untrusted("post_opening", text, limit=200, network=name) for name, text in facts["openings"]
    )
    best = facts.get("best")
    if best:
        best_text = (
            f"On {best['network']}: did about {best['ratio']}× as well as the account's usual post "
            f"(better than {best['better_than']}% of its posts).\n"
            + base.untrusted("best_post_opening", best["opening"], limit=200)
        )
    else:
        best_text = "No post from this week has had three days to gather reactions yet; compare next week."
    topics = "\n".join(base.untrusted("planned_topic", topic, limit=160) for topic in facts["planned_topics"])
    coming = f"{facts['planned']} post(s) being prepared for next week, {facts['scheduled']} already scheduled."
    return "\n\n".join(
        [
            base.tagged("report_week", label),
            base.tagged("went_out", f"{went}\n{openings}".strip()),
            base.tagged("best_post", best_text),
            base.tagged("coming_up", f"{coming}\n{topics}".strip()),
        ]
    )


def quiet_week(label: str) -> dict[str, Any]:
    """A report for a week with nothing in it, written without a model."""
    return {
        "title": f"Your week on social: {label}",
        "summary": "A quiet week: nothing went out and nothing is lined up yet.",
        "sections": [
            {
                "kind": "next",
                "heading": "What's next",
                "body": "Nothing is planned for the coming week yet. Ask the team for a few posts, "
                "or switch on autopilot to have next week planned for you to approve.",
            }
        ],
    }


def stage_write(job: AgencyJob) -> None:
    from ..brand_defaults import ensure_profile

    workspace = job.workspace
    start, end = report_window(job)
    label = period_label(start, end)
    facts = report_facts(workspace, start, end)
    state = job.state or {}
    audience = audience_text(state.get("audience"))
    stored = {"period": {"start": start.date().isoformat(), "end": end.date().isoformat(), "label": label}}
    stored["went_out"] = facts["went_out"]

    if not facts["went_out"] and not facts["planned"] and not facts["scheduled"] and not state.get("messages"):
        _skip(job, "reporter", "A quiet week: wrote a short report without the model.")
        engine.finish(job, result={**quiet_week(label), **stored})
        return None
    if not budget.can_spend(workspace):
        raise engine.JobError(budget.over_budget_message(workspace))

    profile = ensure_profile(workspace)
    run, result = engine.call(
        job,
        "reporter",
        lambda: insights.reporter(profile, facts_text(facts, label), audience=audience),
        effort=insights.REPORTER_EFFORT,
    )
    answer = result.output
    order = {kind: index for index, kind in enumerate(("went_out", "best", "audience", "next"))}
    sections = sorted(
        (
            {"kind": s.kind, "heading": " ".join(s.heading.split())[:120], "body": " ".join(s.body.split())[:1200]}
            for s in answer.sections
            if s.heading.strip() and s.body.strip()
        ),
        key=lambda s: order.get(s["kind"], 9),
    )
    report = {
        "title": " ".join(answer.title.split())[:200] or f"Your week on social: {label}",
        "summary": " ".join(answer.summary.split())[:600],
        "sections": sections,
    }
    engine.end(run, summary=f"Wrote “{report['title']}”.", output={"sections": len(sections)}, result=result)
    engine.finish(job, result={**report, **stored})
    return None


JOB = engine.JobType(
    kind="report",
    stages=(
        engine.Stage("listen", "audience_listener", stage_listen),
        engine.Stage("write", "reporter", stage_write),
    ),
    priority=engine.PRIORITY_BACKGROUND,
    stuck_after=timedelta(minutes=45),
)
