"""The ``plan`` job: next week's posts, prepared as planned briefs for a person to approve.

Stages, one worker task each:

1. **listen** — the performance analyst reads the workspace's ranked results
   (``apps.studio.performance``) and the audience listener reads the last two
   weeks of comments, messages and reviews (scrubbed of names, handles, emails,
   phone numbers and links by :func:`scrub`). Either is skipped, with a SKIPPED
   timeline row, when there is nothing to read; either failing only means the
   plan is made without it.
2. **moments** — the moments scout lists timely dates for the week. With
   ``STUDIO_WEB_SEARCH`` on it searches the web first (a separate free-text
   turn whose searches are recorded on its timeline row, so the budget counts
   them); otherwise it works from what the model knows and marks what it isn't
   sure of.
3. **plan** — the content planner writes one idea per post wanted, choosing
   accounts and an open slot by the short keys this job showed it.
4. **brief** — code. Each idea gets a distinct open time in the week (the
   planner's slot if it is still free, else ``scheduling.propose`` re-asked
   per idea so earlier ideas' times count as taken, else a plain weekday time)
   and becomes a PLANNED brief authored by the workspace's lead. The autopilot
   cycle hands planned briefs to the team a few at a time. Blog articles for
   the month's quota are queued as ``blog`` jobs.

Targets never come from the model: accounts are this workspace's autopilot
accounts that are still connected, the author is the validated lead, and the
times are checked against the calendar here. Nothing is approved, scheduled
or published; every post waits for a person in Approvals.
"""

from __future__ import annotations

import calendar
import logging
import math
import re
import zoneinfo
from datetime import date, datetime, time, timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from .. import budget, engine, llm, performance, scheduling
from ..models import AgencyJob, AgencySettings, AgentRun, AutopilotWeek, StudioBrief
from ..roles import base, insights, strategy

logger = logging.getLogger(__name__)

#: How far back the audience listener reads.
LISTEN_DAYS = 14
#: At most this many messages go to the listener (newest first).
MAX_MESSAGES = 60
#: Recent briefs and posts the planner sees, to avoid repeats.
RECENT_DAYS = 60
#: Plain times (local) offered when the accounts have no posting slots.
FALLBACK_HOURS = (10, 13, 16)
_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


# ---------------------------------------------------------------------------
# Shared with the autopilot tick and the report job
# ---------------------------------------------------------------------------


def zone_of(workspace) -> zoneinfo.ZoneInfo:
    try:
        return zoneinfo.ZoneInfo(workspace.effective_timezone or "UTC")
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return zoneinfo.ZoneInfo("UTC")


def week_window(workspace, week_start: date) -> tuple[datetime, datetime]:
    """Monday 00:00 to the next Monday 00:00, in the workspace's timezone."""
    zone = zone_of(workspace)
    start = datetime.combine(week_start, time.min).replace(tzinfo=zone)
    return start, datetime.combine(week_start + timedelta(days=7), time.min).replace(tzinfo=zone)


def plan_accounts(workspace, settings_row: AgencySettings) -> list:
    """The autopilot accounts that belong to this workspace, can be designed for and are connected."""
    from ..forms import STUDIO_PLATFORMS

    rows = settings_row.accounts.filter(workspace=workspace, platform__in=STUDIO_PLATFORMS).order_by(
        "platform", "account_name"
    )
    return [account for account in rows if not account.needs_reconnect]


def valid_lead(settings_row: AgencySettings, workspace) -> tuple[Any, str]:
    """``(user, "")`` when the lead may author drafts here, else ``(None, reason for people)``.

    The lead must still be an active member who can create posts and approve
    them (an owner or manager), and not a client.
    """
    from apps.approvals.actor import is_internal_approver
    from apps.members.models import WorkspaceMembership

    lead = settings_row.lead
    if lead is None or not lead.is_active:
        return None, "Choose who the drafts are from (an owner or manager) under Agency → Autopilot."
    membership = (
        WorkspaceMembership.objects.filter(user=lead, workspace=workspace).select_related("custom_role").first()
    )
    if membership is None:
        return None, "The person the drafts are from is no longer in this workspace. Choose someone else."
    if not membership.effective_permissions.get("create_posts", False) or not is_internal_approver(lead, workspace):
        return None, "The person the drafts are from can no longer create and approve posts. Choose someone else."
    return lead, ""


def scrub(text: str, names: list[str] | None = None) -> str:
    """``text`` without emails, links, @handles, phone numbers or the sender's own name."""
    out = _EMAIL.sub("[email]", text or "")
    out = _URL.sub("[link]", out)
    out = _HANDLE.sub("[someone]", out)
    out = _PHONE.sub("[phone]", out)
    for name in names or []:
        for token in re.split(r"[\s@_.]+", name or ""):
            if len(token) >= 3 and token.lower() not in {"the", "and", "official"}:
                out = re.sub(rf"(?<!\w){re.escape(token)}(?!\w)", "[name]", out, flags=re.IGNORECASE)
    return " ".join(out.split())


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_HANDLE = re.compile(r"(?<![\w@])@[\w.]{2,}")
_PHONE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{6,}\d")


def audience_messages(
    workspace,
    *,
    days: int = LISTEN_DAYS,
    limit: int = MAX_MESSAGES,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[dict[str, str]]:
    """Recent comments, messages and reviews of this workspace, scrubbed for the listener.

    The last ``days`` days by default, or ``[start, end)`` when given (the report's week).
    """
    from apps.inbox.models import InboxMessage

    rows = InboxMessage.objects.filter(
        workspace=workspace, received_at__gte=start or timezone.now() - timedelta(days=days)
    )
    if end is not None:
        rows = rows.filter(received_at__lt=end)
    rows = rows.exclude(body="").select_related("social_account").order_by("-received_at")[:limit]
    out = []
    for message in rows:
        text = scrub(message.body, [message.sender_name, message.sender_handle])[:400]
        if text.strip():
            out.append(
                {
                    "kind": message.message_type,
                    "network": message.social_account.platform if message.social_account_id else "",
                    "sentiment": message.sentiment,
                    "text": text,
                }
            )
    return out


def performance_digest(workspace, *, since: datetime | None = None) -> str | None:
    """The ranked posts as text for the performance analyst, or None when nothing is scored yet."""
    from apps.composer.models import PlatformPost

    from .learn import _studio_designs

    items = [m for m in performance.measured(workspace=workspace, since=since) if m.ratio is not None]
    if not items:
        return None
    pps: dict[Any, Any] = {
        pp.pk: pp
        for pp in PlatformPost.objects.filter(
            pk__in=[m.platform_post_id for m in items], post__workspace=workspace
        ).select_related("post", "social_account")
    }
    items = [m for m in items if m.platform_post_id in pps]
    if not items:
        return None
    designs = _studio_designs(workspace, {m.post_id for m in items})
    zone = zone_of(workspace)
    counts: dict[str, int] = {}
    for item in items:
        account = pps[item.platform_post_id].social_account
        label = (
            f"{account.get_platform_display()} — {account.account_name or account.platform} (scored on {item.metric})"
        )
        counts[label] = counts.get(label, 0) + 1
    ordered = sorted(items, key=lambda m: m.ratio or 0, reverse=True)
    picked = ordered[:8] + [m for m in ordered[-5:] if m not in ordered[:8]]
    lines = []
    for item in picked:
        pp = pps[item.platform_post_id]
        local = item.published_at.astimezone(zone)
        design = designs.get(item.post_id) or {}
        made = (
            f"made in the Studio: {design.get('template') or '?'} layout, {design.get('post_format') or 'single'} format"
            if design
            else "made outside the Studio"
        )
        caption = (pp.platform_specific_caption or pp.post.caption or "").strip()
        first_line = (caption.splitlines() or [""])[0]
        lines.append(
            f"- {pp.social_account.get_platform_display()}, {_DAYS[local.weekday()]} {local:%H}:00: "
            f"{item.ratio:.1f}× the account's usual (better than {round((item.percentile or 0) * 100)}% of its "
            f"posts); {made}.\n  {base.untrusted('caption_opening', first_line, limit=200)}"
        )
    return "\n\n".join(
        [
            base.tagged("measured_posts_per_account", base.bullets(f"{k}: {v} posts" for k, v in counts.items())),
            base.tagged("best_and_worst_posts", "\n".join(lines)),
        ]
    )


def performance_text(answer: dict[str, Any] | None) -> str:
    if not answer:
        return ""
    parts = [answer.get("summary", "")]
    for label, key in (("Working", "whats_working"), ("Not working", "whats_not"), ("Try", "recommendations")):
        if answer.get(key):
            parts.append(f"{label}:\n{base.bullets(answer[key])}")
    parts.append(f"Evidence: {answer.get('evidence', 'thin')}.")
    return "\n".join(p for p in parts if p)


def audience_text(answer: dict[str, Any] | None) -> str:
    if not answer:
        return ""
    parts = [answer.get("summary", "")]
    themes = [f"{t.get('theme')} ({t.get('mentions')}): {t.get('summary')}" for t in answer.get("themes") or []]
    for label, values in (
        ("Themes", themes),
        ("Questions people ask", answer.get("questions")),
        ("Praise", answer.get("praise")),
        ("Complaints", answer.get("complaints")),
    ):
        if values:
            parts.append(f"{label}:\n{base.bullets(values)}")
    return "\n".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Slots
# ---------------------------------------------------------------------------


def _label(when: datetime, zone) -> str:
    local = when.astimezone(zone)
    return f"{_DAYS[local.weekday()]} {local:%d %b}, {local:%H:%M}"


def _fallback_times(workspace, start: datetime, end: datetime, taken: set[datetime], limit: int) -> list[datetime]:
    """Plain local times in the week (weekdays first) for accounts without posting slots."""
    zone = zone_of(workspace)
    floor = timezone.now() + scheduling.LEAD_TIME
    day0 = start.astimezone(zone).date()
    order = [0, 1, 2, 3, 4, 5, 6]
    out = []
    for hour in FALLBACK_HOURS:
        for offset in order:
            when = datetime.combine(day0 + timedelta(days=offset), time(hour)).replace(tzinfo=zone)
            if floor < when < end and when not in taken and when not in out:
                out.append(when)
    out.sort(key=lambda w: (w.astimezone(zone).weekday() >= 5, w))
    return out[:limit]


def open_slots(workspace, accounts, start: datetime, end: datetime, *, limit: int) -> list[tuple[datetime, list]]:
    """Free posting-slot times in ``[start, end)`` across ``accounts``: ``[(when, accounts with that slot)]``."""
    from apps.calendar.services import _next_slot_datetimes, _occupied_datetimes

    taken = scheduling.taken_times(workspace)
    floor = max(start, timezone.now() + scheduling.LEAD_TIME)
    found: dict[datetime, list] = {}
    for account in accounts:
        try:
            occupied = _occupied_datetimes(account) | taken
            candidates = _next_slot_datetimes(account, floor, count=60)
        except Exception:
            logger.exception("Plan: could not read posting slots for account %s", account.pk)
            continue
        for when in candidates:
            if when >= end:
                break
            if when not in occupied:
                found.setdefault(when, []).append(account)
    slots = sorted(found.items())[:limit]
    if not slots:
        slots = [(when, list(accounts)) for when in _fallback_times(workspace, start, end, taken, limit)]
    return slots


def _is_free(when: datetime, accounts, taken: set[datetime]) -> bool:
    from apps.calendar.services import _occupied_datetimes

    if when in taken or when <= timezone.now() + scheduling.LEAD_TIME:
        return False
    return not any(when in _occupied_datetimes(account) for account in accounts)


def allocate(workspace, accounts, preferred: datetime | None, start: datetime, end: datetime, used: set[datetime]):
    """A free time in the week for one idea, or None when the week is full."""
    taken = scheduling.taken_times(workspace) | used
    if preferred is not None and start <= preferred < end and _is_free(preferred, accounts, taken):
        return preferred
    proposal = scheduling.propose(workspace, accounts, after=start)
    if start <= proposal.when < end and proposal.when not in taken:
        return proposal.when
    fallback = _fallback_times(workspace, start, end, taken, 1)
    return fallback[0] if fallback else None


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------


def _settings(job: AgencyJob) -> AgencySettings:
    row = AgencySettings.objects.filter(workspace=job.workspace).select_related("lead", "blog_site").first()
    if row is None:
        raise engine.JobError("Autopilot isn't set up for this workspace yet. Open Agency → Autopilot.")
    return row


def _week_start(job: AgencyJob) -> date:
    try:
        return date.fromisoformat(str((job.input or {}).get("week_start")))
    except ValueError as exc:
        raise engine.JobError("This plan doesn't say which week it is for. Plan the week again.") from exc


def _skip(job: AgencyJob, agent: str, summary: str) -> None:
    run = engine.begin(job, agent)
    engine.end(run, summary=summary, status=AgentRun.Status.SKIPPED)


def stage_listen(job: AgencyJob) -> str:
    """The performance analyst and the audience listener; either may be skipped or fail without stopping the plan."""
    from ..brand_defaults import ensure_profile

    workspace = job.workspace
    if not budget.can_spend(workspace):
        raise engine.JobError(budget.over_budget_message(workspace))
    profile = ensure_profile(workspace)

    perf: dict[str, Any] | None = None
    digest = performance_digest(workspace)
    if digest is None:
        _skip(job, "performance_analyst", "No published posts with enough results to compare yet.")
    else:
        try:
            run, result = engine.call(
                job,
                "performance_analyst",
                lambda: insights.performance_analyst(profile, digest),
                effort=insights.PERFORMANCE_ANALYST_EFFORT,
            )
        except engine.JobError:
            logger.info("Plan %s: the performance analyst failed; planning without it", job.pk)
        else:
            perf = result.output.model_dump()
            engine.end(run, summary=result.output.summary, output=perf, result=result)

    audience: dict[str, Any] | None = None
    messages = audience_messages(workspace)
    if not messages:
        _skip(job, "audience_listener", f"No comments, messages or reviews in the last {LISTEN_DAYS} days.")
    else:
        try:
            run, result = engine.call(
                job,
                "audience_listener",
                lambda: insights.audience_listener(profile, messages, days=LISTEN_DAYS),
                effort=insights.AUDIENCE_LISTENER_EFFORT,
            )
        except engine.JobError:
            logger.info("Plan %s: the audience listener failed; planning without it", job.pk)
        else:
            audience = result.output.model_dump()
            engine.end(
                run,
                summary=result.output.summary,
                output={**audience, "messages_read": len(messages)},
                result=result,
            )

    engine.update_state(job, performance=perf, audience=audience)
    return "moments"


def _record_research(run: AgentRun, research: llm.ResearchResult) -> None:
    run.model = research.model
    run.input_tokens = research.input_tokens
    run.output_tokens = research.output_tokens
    run.cache_read_tokens = research.cache_read_tokens
    run.save(update_fields=["model", "input_tokens", "output_tokens", "cache_read_tokens"])
    engine.end(
        run,
        summary=f"Searched the web for the week's moments ({research.web_searches} search(es)).",
        output={"web_searches": research.web_searches},
    )


def stage_moments(job: AgencyJob) -> str:
    """The moments scout, with a web research turn first when web search is switched on."""
    from ..brand_defaults import ensure_profile

    workspace = job.workspace
    settings_row = _settings(job)
    profile = ensure_profile(workspace)
    week_start = _week_start(job)
    week_end = week_start + timedelta(days=6)
    pillars = [str(p) for p in settings_row.pillars or []]
    where = workspace.effective_timezone or "UTC"

    research_text = ""
    web_searches = 0
    if llm.web_search_enabled():
        run = engine.begin(job, "trend_scout", effort=strategy.RESEARCH_EFFORT)
        try:
            research = strategy.moments_research(
                profile, window_start=week_start, window_end=week_end, pillars=pillars, zone=where
            )
        except engine.JobError as exc:
            engine.fail_run(run, exc)
        else:
            research_text, web_searches = research.text, research.web_searches
            _record_research(run, research)

    moments: dict[str, Any] | None = None
    try:
        run, result = engine.call(
            job,
            "trend_scout",
            lambda: strategy.trend_scout(
                profile,
                window_start=week_start,
                window_end=week_end,
                pillars=pillars,
                zone=where,
                research=research_text or None,
            ),
            effort=strategy.TREND_SCOUT_EFFORT,
        )
    except engine.JobError:
        logger.info("Plan %s: the moments scout failed; planning without moments", job.pk)
    else:
        moments = result.output.model_dump()
        source = "web research" if research_text else "the model's own knowledge (dates may be uncertain)"
        count = len(result.output.moments)
        engine.end(
            run,
            summary=f"Found {count} moment(s) for the week, from {source}.",
            output={**moments, "source": source, "researched": bool(research_text)},
            result=result,
        )
    engine.update_state(job, moments=moments, researched=bool(research_text), web_searches=web_searches)
    return "plan"


def _moments_text(moments: dict[str, Any] | None, researched: bool) -> str:
    if not moments:
        return ""
    rows = [
        f"{m.get('when')}: {m.get('name')} ({m.get('confidence')}) — {m.get('why_it_matters')} Idea: {m.get('angle_idea')}"
        for m in moments.get("moments") or []
    ]
    source = "From web research." if researched else "From the scout's own knowledge; dates may be uncertain."
    return "\n".join([source, base.bullets(rows), moments.get("notes", "")])


def recent_topics(workspace, limit: int = 15) -> list[str]:
    """Recent brief ideas and post openings of this workspace, to avoid repeating them."""
    from apps.composer.models import Post

    since = timezone.now() - timedelta(days=RECENT_DAYS)
    ideas = (
        StudioBrief.objects.filter(workspace=workspace, created_at__gte=since)
        .exclude(status=StudioBrief.Status.DISCARDED)
        .order_by("-created_at")
        .values_list("idea", flat=True)[:limit]
    )
    captions = (
        Post.objects.filter(workspace=workspace, created_at__gte=since)
        .exclude(caption="")
        .order_by("-created_at")
        .values_list("caption", flat=True)[:limit]
    )
    out = [f"Brief: {' '.join(idea.split())[:200]}" for idea in ideas]
    out += [f"Post: {' '.join(caption.split())[:200]}" for caption in captions]
    return out


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}


def _repeats(text: str, others: list[str]) -> bool:
    mine = _words(text)
    if len(mine) < 3:
        return False
    for other in others:
        theirs = _words(other)
        if theirs and len(mine & theirs) / len(mine | theirs) >= 0.7:
            return True
    return False


def _articles_wanted(job: AgencyJob, settings_row: AgencySettings) -> int:
    """This week's share of the month's article quota (0 without a site of this workspace)."""
    from apps.blog.models import BlogSite

    quota = int(settings_row.blog_posts_per_month or 0)
    if quota <= 0 or not settings_row.blog_site_id:
        return 0
    if not BlogSite.objects.filter(pk=settings_row.blog_site_id, workspace=job.workspace, is_enabled=True).exists():
        return 0
    made = (
        AgencyJob.objects.filter(
            workspace=job.workspace,
            kind=AgencyJob.Kind.BLOG,
            parent__kind=AgencyJob.Kind.PLAN,
            created_at__gte=budget.month_start(job.workspace),
        )
        .exclude(parent=job)
        .count()
    )
    remaining = max(0, quota - made)
    local = timezone.now().astimezone(zone_of(job.workspace))
    days_left = calendar.monthrange(local.year, local.month)[1] - local.day + 1
    weeks_left = max(1, math.ceil(days_left / 7))
    return min(remaining, math.ceil(remaining / weeks_left), 4)


def stage_plan(job: AgencyJob) -> str:
    """The content planner fills the week; its answer is validated against this job's own accounts and slots."""
    from ..brand_defaults import ensure_profile

    workspace = job.workspace
    settings_row = _settings(job)
    accounts = plan_accounts(workspace, settings_row)
    if not accounts:
        raise engine.JobError(
            "None of the autopilot accounts is connected right now. Reconnect one, or choose others under "
            "Agency → Autopilot, then press Retry."
        )
    if not budget.can_spend(workspace):
        raise engine.JobError(budget.over_budget_message(workspace))
    profile = ensure_profile(workspace)
    week_start = _week_start(job)
    start, end = week_window(workspace, week_start)
    posts = max(1, min(14, int((job.input or {}).get("posts") or settings_row.posts_per_week or 1)))
    zone = zone_of(workspace)

    account_rows = [
        {
            "key": f"a{index}",
            "id": str(account.pk),
            "label": f"{account.get_platform_display()} — {account.account_name or account.platform}",
        }
        for index, account in enumerate(accounts, start=1)
    ]
    names = {str(a.pk): a.get_platform_display() for a in accounts}
    slot_rows = []
    for index, (when, slot_accounts) in enumerate(open_slots(workspace, accounts, start, end, limit=posts * 3), 1):
        where = ", ".join(sorted({names.get(str(a.pk), "") for a in slot_accounts}))
        slot_rows.append({"key": f"s{index}", "when": when.isoformat(), "label": f"{_label(when, zone)} ({where})"})
    articles_wanted = _articles_wanted(job, settings_row)
    recent = recent_topics(workspace)
    state = job.state or {}
    pillars = [str(p) for p in settings_row.pillars or []]

    run, result = engine.call(
        job,
        "planner",
        lambda: strategy.planner(
            profile,
            posts=posts,
            articles=articles_wanted,
            window_start=week_start,
            window_end=week_start + timedelta(days=6),
            pillars=pillars,
            accounts=[{"key": r["key"], "label": r["label"]} for r in account_rows],
            slots=[{"key": r["key"], "label": r["label"]} for r in slot_rows],
            performance=performance_text(state.get("performance")),
            audience=audience_text(state.get("audience")),
            moments=_moments_text(state.get("moments"), bool(state.get("researched"))),
            recent=recent,
        ),
        effort=strategy.PLANNER_EFFORT,
    )
    answer = result.output
    account_keys = {row["key"]: row["id"] for row in account_rows}
    slot_keys = {row["key"] for row in slot_rows}
    ideas: list[dict[str, Any]] = []
    chosen_slots: set[str] = set()
    for idea in answer.ideas:
        text = " ".join((idea.idea or "").split())[:600]
        if not text or _repeats(text, recent + [i["idea"] for i in ideas]):
            continue
        keys = list(dict.fromkeys(k.strip() for k in idea.accounts if k.strip() in account_keys))
        slot = idea.slot.strip() if idea.slot.strip() in slot_keys - chosen_slots else ""
        if slot:
            chosen_slots.add(slot)
        ideas.append(
            {
                "idea": text,
                "pillar": " ".join((idea.pillar or "").split())[:60],
                "goal": idea.goal if idea.goal in StudioBrief.Goal.values else "",
                "angle": " ".join((idea.angle_notes or "").split())[:600],
                "why_now": " ".join((idea.why_now or "").split())[:300],
                "accounts": [account_keys[k] for k in keys],
                "slot": slot,
            }
        )
        if len(ideas) >= posts:
            break
    articles = [
        {
            "topic": " ".join(a.topic.split())[:200],
            "focus_keyword": " ".join(a.focus_keyword.lower().split())[:80],
            "why": " ".join(a.why.split())[:300],
        }
        for a in answer.articles
        if a.topic.strip()
    ][:articles_wanted]
    engine.end(
        run,
        summary=f"Planned {len(ideas)} post(s)" + (f" and {len(articles)} article(s)" if articles else "") + ".",
        output={"ideas": ideas, "articles": articles, "notes": answer.notes[:1000]},
        result=result,
    )
    if not ideas:
        raise engine.JobError("The planner's ideas all repeated recent posts or were empty. Press Retry.")
    engine.update_state(job, accounts=account_rows, slots=slot_rows, ideas=ideas, articles=articles)
    return "brief"


def _notes(idea: dict[str, Any], label: str) -> str:
    lines = [f"Planned by autopilot for {label}."]
    if idea.get("pillar"):
        lines.append(f"Pillar: {idea['pillar']}")
    if idea.get("angle"):
        lines.append(f"How to make it land: {idea['angle']}")
    if idea.get("why_now") and idea["why_now"].lower() != "evergreen":
        lines.append(f"Why now: {idea['why_now']}")
    lines.append("State only facts from the brand profile; anything in this plan that isn't there is unconfirmed.")
    return "\n".join(lines)[:2000]


def stage_brief(job: AgencyJob) -> None:
    """Planned briefs for each idea, at distinct free times in the week, plus the month's blog jobs."""
    from apps.blog.models import BlogSite

    from .. import services

    workspace = job.workspace
    settings_row = _settings(job)
    lead, reason = valid_lead(settings_row, workspace)
    if lead is None:
        raise engine.JobError(reason)
    accounts = plan_accounts(workspace, settings_row)
    if not accounts:
        raise engine.JobError("None of the autopilot accounts is connected right now. Reconnect one, then Retry.")
    by_id = {str(a.pk): a for a in accounts}
    start, end = week_window(workspace, _week_start(job))
    zone = zone_of(workspace)
    state = job.state or {}
    slot_times = {row["key"]: datetime.fromisoformat(row["when"]) for row in state.get("slots") or []}

    run = engine.begin(job, "scheduler")
    made: dict[str, str] = dict(state.get("made") or {})
    used: set[datetime] = {
        when
        for when in StudioBrief.objects.filter(job=job, workspace=workspace).values_list(
            "proposed_publish_at", flat=True
        )
        if when is not None
    }
    placed, full = [], 0
    for index, idea in enumerate(state.get("ideas") or []):
        if str(index) in made:
            continue
        idea_accounts = [by_id[pk] for pk in idea.get("accounts") or [] if pk in by_id] or accounts
        when = allocate(workspace, idea_accounts, slot_times.get(idea.get("slot") or ""), start, end, used)
        if when is None:
            full += 1
            continue
        label = _label(when, zone)
        with transaction.atomic():
            brief = services.create_brief(
                workspace,
                lead,
                idea=idea["idea"],
                notes=_notes(idea, label),
                goal=idea.get("goal", ""),
                accounts=idea_accounts,
                style_lock=True,
                proposed_publish_at=when,
                origin=StudioBrief.Origin.AUTOPILOT,
                job=job,
                start=False,
            )
            made[str(index)] = str(brief.pk)
            engine.update_state(job, made=made)  # a cancelled plan rolls this brief back
        used.add(when)
        placed.append(label)

    blog_jobs: list[str] = list(state.get("blog_jobs") or [])
    site = (
        BlogSite.objects.filter(pk=settings_row.blog_site_id, workspace=workspace, is_enabled=True).first()
        if settings_row.blog_site_id
        else None
    )
    if site is not None:
        for article in (state.get("articles") or [])[len(blog_jobs) :]:
            with transaction.atomic():
                child = engine.create(
                    workspace,
                    AgencyJob.Kind.BLOG,
                    title=article["topic"],
                    input={
                        "topic": article["topic"],
                        "site_id": str(site.pk),
                        "focus_keyword": article["focus_keyword"],
                    },
                    requested_by=lead,
                    parent=job,
                )
                blog_jobs.append(str(child.pk))
                engine.update_state(job, blog_jobs=blog_jobs)

    if not made:
        engine.end(run, summary="No free time left in the week for the planned posts.", status=AgentRun.Status.FAILED)
        raise engine.JobError("Next week has no free posting time left for the plan. Free a slot, then press Retry.")
    summary = f"Planned {len(made)} post(s) for the week of {start:%d %b}"
    if blog_jobs:
        summary += f" and asked the SEO team for {len(blog_jobs)} article(s)"
    summary += "."
    if full:
        summary += f" {full} idea(s) didn't fit: the week has no more free time."
    engine.end(run, summary=summary, output={"times": placed, "briefs": list(made.values()), "blog_jobs": blog_jobs})
    week_id = (job.input or {}).get("week_id")
    if week_id:
        AutopilotWeek.objects.filter(pk=week_id, workspace=workspace).update(
            note=summary[:500], updated_at=timezone.now()
        )
    engine.finish(
        job,
        result={
            "week_start": start.date().isoformat(),
            "briefs": list(made.values()),
            "blog_jobs": blog_jobs,
            "summary": summary,
            "learned": learned_lines(state),
        },
    )
    return None


def learned_lines(state: dict[str, Any]) -> list[str]:
    """What the analyst and the listener found, as plain lines for the agency home."""
    lines = []
    performance_notes = state.get("performance") or {}
    lines += [str(line) for line in (performance_notes.get("whats_working") or [])[:2]]
    audience = state.get("audience") or {}
    questions = audience.get("questions") or []
    if questions:
        lines.append(f"People are asking: {questions[0]}")
    return [" ".join(line.split())[:300] for line in lines if str(line).strip()]


JOB = engine.JobType(
    kind="plan",
    stages=(
        engine.Stage("listen", "performance_analyst", stage_listen),
        engine.Stage("moments", "trend_scout", stage_moments),
        engine.Stage("plan", "planner", stage_plan),
        engine.Stage("brief", "scheduler", stage_brief),
    ),
    priority=engine.PRIORITY_DEFAULT,
    stuck_after=timedelta(minutes=45),
)
