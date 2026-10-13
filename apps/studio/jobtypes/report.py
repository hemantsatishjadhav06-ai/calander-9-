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

from django.db.models import F, Q
from django.utils import timezone

from .. import budget, engine, outcomes, performance
from ..models import AgencyJob, AgentRun, StudioBrief
from ..reports import network_name
from ..roles import base, insights
from .plan import audience_messages, audience_text, zone_of

logger = logging.getLogger(__name__)

#: Openings of posts shown to the reporter (per section).
MAX_LISTED = 5
OPERATION_SCOPE = (
    "Requests, prepared drafts and publication are events in this period. Other counts show the observed "
    "status of content created, proposed or published in this period when the report was written. "
    "A post can appear in more than one channel state; these counts are not a conversion funnel. "
    "Historical status changes are not reconstructed."
)


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
        _skip(job, "audience_listener", "The AI budget is paused; the report uses recorded operational counts.")
        engine.update_state(job, audience=None, messages=0, narrative_unavailable="The AI budget is paused.")
        return "write"
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


def operational_counts(workspace, start: datetime, end: datetime) -> dict[str, int]:
    """Period events plus clearly scoped observed content states, without private errors."""
    from apps.approvals.models import ApprovalAction
    from apps.composer.models import PlatformPost, Post

    from ..models import AutopilotWeek

    period = Q(created_at__gte=start, created_at__lt=end)
    briefs = StudioBrief.objects.filter(workspace=workspace)
    posts = Post.objects.filter(workspace=workspace)
    relevant = (
        posts.filter(created_at__lt=end)
        .filter(
            period
            | Q(proposed_publish_at__gte=start, proposed_publish_at__lt=end)
            | Q(platform_posts__scheduled_at__gte=start, platform_posts__scheduled_at__lt=end)
            | Q(platform_posts__published_at__gte=start, platform_posts__published_at__lt=end)
        )
        .distinct()
    )
    own_pps = PlatformPost.objects.filter(
        post__in=relevant,
        social_account__workspace=workspace,
        post__workspace=workspace,
    )

    def state_count(*states):
        return own_pps.filter(status__in=states).values("post_id").distinct().count()

    failed_briefs = briefs.filter(status=StudioBrief.Status.FAILED).filter(
        period | Q(finished_at__gte=start, finished_at__lt=end)
    )
    blocked_ids = ApprovalAction.objects.filter(
        post__workspace=workspace,
        action=ApprovalAction.ActionType.BLOCKED,
        created_at__gte=start,
        created_at__lt=end,
    ).values_list("post_id", flat=True)
    blocked = (
        own_pps.filter(Q(status=PlatformPost.Status.ON_HOLD) | Q(post_id__in=blocked_ids))
        .values("post_id")
        .distinct()
        .count()
    )
    failed_jobs = (
        AgencyJob.objects.filter(workspace=workspace, status=AgencyJob.Status.FAILED)
        .exclude(kind=AgencyJob.Kind.REPORT)
        .filter(Q(finished_at__gte=start, finished_at__lt=end) | Q(finished_at__isnull=True) & period)
        .count()
    )
    paused = AutopilotWeek.objects.filter(
        workspace=workspace,
        status__in=[AutopilotWeek.Status.SKIPPED, AutopilotWeek.Status.FAILED],
        created_at__gte=start,
        created_at__lt=end,
    ).count()
    return {
        "requested": briefs.filter(period).count() + posts.filter(period, studio_briefs__isnull=True).count(),
        "prepared": posts.filter(period).count(),
        "awaiting_approval": state_count(
            PlatformPost.Status.PENDING_REVIEW,
            PlatformPost.Status.PENDING_CLIENT,
            PlatformPost.Status.CHANGES_REQUESTED,
        ),
        "approved": state_count(PlatformPost.Status.APPROVED),
        "scheduled": state_count(PlatformPost.Status.SCHEDULED),
        "published": PlatformPost.objects.filter(
            post__workspace=workspace,
            social_account__workspace=workspace,
            status=PlatformPost.Status.PUBLISHED,
            published_at__gte=start,
            published_at__lt=end,
        )
        .values("post_id")
        .distinct()
        .count(),
        "failed": state_count(PlatformPost.Status.FAILED) + failed_briefs.filter(post__isnull=True).count(),
        "blocked": blocked,
        "job_failures": failed_jobs,
        "paused_weeks": paused,
    }


def current_backlog(workspace) -> dict[str, int]:
    """Outstanding content observed now, kept separate from historical period events."""
    from apps.composer.models import PlatformPost

    own = PlatformPost.objects.filter(post__workspace=workspace, social_account__workspace=workspace)
    return {
        "awaiting_approval": own.filter(status__in=["pending_review", "pending_client", "changes_requested"])
        .values("post_id")
        .distinct()
        .count(),
        "blocked": own.filter(status="on_hold").values("post_id").distinct().count(),
        "failed": own.filter(status="failed").values("post_id").distinct().count()
        + StudioBrief.objects.filter(
            workspace=workspace,
            status=StudioBrief.Status.FAILED,
            post__isnull=True,
        ).count(),
    }


def performance_note(workspace, published, measured, end: datetime) -> str:
    """Explain unavailable comparisons using the actual evidence prerequisites."""
    if not published:
        return "No posts were published in this period."
    mature = [pp for pp in published if pp.published_at <= end - performance.MIN_AGE]
    if not mature:
        return "The period's posts were younger than three days at the report cutoff; compare after they have gathered results."
    if not any(performance.score_metric(pp.social_account.platform) for pp in mature):
        return "Comparative analytics are not available for these channels."
    fresh = [item for item in measured if item.platform_post_id in {pp.pk for pp in mature}]
    if not fresh:
        return "Successful analytics captured within seven days of the report cutoff are missing. Refresh insights before comparing results."
    if not any(item.percentile is not None for item in fresh):
        return "An account needs at least five posts with fresh measured results before a performance comparison is meaningful."
    if not any(item.ratio is not None for item in fresh):
        return "The account's baseline result is zero, so a meaningful performance ratio cannot be calculated."
    return "Comparisons use successful results captured within seven days of the report cutoff, against the same account's measured posts."


def report_facts(workspace, start: datetime, end: datetime) -> dict[str, Any]:
    """Everything code knows about the week, counted from this workspace's own rows."""
    from apps.composer.models import PlatformPost

    published = list(
        PlatformPost.objects.filter(
            post__workspace=workspace,
            social_account__workspace_id=F("post__workspace_id"),
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
    all_measured = performance.measured(workspace=workspace, now=end)
    measured = [m for m in all_measured if m.ratio is not None and start <= m.published_at < end]
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
        "operations": operational_counts(workspace, start, end),
        "performance_note": performance_note(workspace, published, all_measured, end),
        "outcomes": outcomes.totals(workspace, start, end),
        "current_backlog": current_backlog(workspace),
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
        best_text = facts["performance_note"]
    topics = "\n".join(base.untrusted("planned_topic", topic, limit=160) for topic in facts["planned_topics"])
    coming = f"{facts['planned']} post(s) being prepared for next week, {facts['scheduled']} already scheduled."
    return "\n\n".join(
        [
            base.tagged("report_week", label),
            base.tagged("went_out", f"{went}\n{openings}".strip()),
            base.tagged("best_post", best_text),
            base.tagged("coming_up", f"{coming}\n{topics}".strip()),
            base.tagged(
                "operational_counts",
                "\n".join(f"{key.replace('_', ' ')}: {count}" for key, count in facts["operations"].items())
                + "\n"
                + OPERATION_SCOPE,
            ),
            base.tagged(
                "manual_outcomes",
                "\n".join(f"{key.replace('_', ' ')}: {count}" for key, count in facts["outcomes"].items())
                + "\nManually recorded events, not unique people or automatically attributed conversions.",
            ),
            base.tagged(
                "current_backlog",
                "\n".join(f"{key.replace('_', ' ')}: {count}" for key, count in facts["current_backlog"].items())
                + "\nObserved when this report was written; separate from the historical period counts.",
            ),
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


def counts_report(facts: dict[str, Any], label: str, reason: str = "") -> dict[str, Any]:
    """Useful report fallback when model narrative is unavailable or work needs attention."""
    operations = facts["operations"]
    attention = operations["failed"] + operations["blocked"] + operations["job_failures"] + operations["paused_weeks"]
    summary = f"{operations['published']} post(s) published; {operations['awaiting_approval']} awaiting approval."
    if attention:
        summary += " Failed, held or paused work needs attention."
    backlog = facts["current_backlog"]
    if any(backlog.values()):
        summary += f" Current backlog: {backlog['awaiting_approval']} awaiting approval, {backlog['blocked']} held, {backlog['failed']} failed."
    if any(facts["outcomes"].values()):
        summary += (
            f" Recorded events: {facts['outcomes']['enquiry']} enquiries, "
            f"{facts['outcomes']['qualified_enquiry']} qualified enquiries, {facts['outcomes']['site_visit']} site visits."
        )
    if reason:
        summary += " A model-written narrative is unavailable; recorded counts are shown."
    return {
        "title": f"Your week on social: {label}",
        "summary": summary,
        "sections": [
            {"kind": "went_out", "heading": "Delivery and review", "body": summary},
            {"kind": "best", "heading": "Results available", "body": facts["performance_note"]},
            {
                "kind": "next",
                "heading": "Next action",
                "body": "Review waiting drafts and resolve failed or held work before scheduling more content."
                if attention or operations["awaiting_approval"] or any(backlog.values())
                else "Check upcoming drafts and their proposed times before approving delivery.",
            },
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
    stored: dict[str, Any] = {
        "period": {"start": start.date().isoformat(), "end": end.date().isoformat(), "label": label}
    }
    stored["went_out"] = facts["went_out"]
    stored.update(
        operations=facts["operations"],
        operation_scope=OPERATION_SCOPE,
        operations_as_of=timezone.now().isoformat(),
        performance_note=facts["performance_note"],
        outcomes=facts["outcomes"],
        current_backlog=facts["current_backlog"],
    )

    if (
        not facts["went_out"]
        and not facts["planned"]
        and not facts["scheduled"]
        and not state.get("messages")
        and not any(facts["operations"].values())
        and not any(facts["outcomes"].values())
        and not any(facts["current_backlog"].values())
    ):
        _skip(job, "reporter", "A quiet week: wrote a short report without the model.")
        engine.finish(job, result={**quiet_week(label), **stored})
        return None
    if not budget.can_spend(workspace):
        _skip(job, "reporter", "The AI budget is paused; wrote a report from recorded counts.")
        engine.finish(job, result={**counts_report(facts, label, reason="budget"), **stored})
        return None

    profile = ensure_profile(workspace)
    try:
        run, result = engine.call(
            job,
            "reporter",
            lambda: insights.reporter(profile, facts_text(facts, label), audience=audience),
            effort=insights.REPORTER_EFFORT,
        )
    except engine.JobError:
        engine.finish(job, result={**counts_report(facts, label, reason="provider"), **stored})
        return None
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
        # Delivery counts and the period are facts counted by code, not a
        # model's paraphrase. Narrative sections may suggest next steps.
        "title": f"Your week on social: {label}",
        "summary": counts_report(facts, label)["summary"],
        "sections": sections,
    }
    for section in sections:
        if section["kind"] == "went_out":
            section["body"] = report["summary"]
        elif section["kind"] == "best" and not facts["best"]:
            section["body"] = facts["performance_note"]
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
