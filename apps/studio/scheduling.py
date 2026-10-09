"""The scheduler: when a post should go out. It proposes; a person approves.

The proposed time is the best open posting slot in the coming days:

* slots are the account's PostingSlots (``apps.calendar``), in the workspace's
  timezone;
* a slot is open when no post is scheduled there **and** no other draft, post
  awaiting approval or brief in progress has already been offered it — so a
  week of autopilot posts gets a week of different times;
* among the open slots in the next ``HORIZON``, the one whose weekday and hour
  have done best for this account (see ``apps.studio.performance``) wins; with
  too little history it is simply the first open slot.

When the account has no posting slots at all it falls back to the next weekday
at 10:00 local time. Nothing here schedules anything: the time is stored as
the post's ``proposed_publish_at``, and only an approver turns it into a
schedule.
"""

from __future__ import annotations

import logging
import statistics
import zoneinfo
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

#: How far ahead a "best" slot may be preferred over the first open one.
HORIZON = timedelta(days=8)
#: The earliest a proposal may be (people need time to approve).
LEAD_TIME = timedelta(hours=2)
#: A weekday-and-hour needs this many measured posts before it counts.
MIN_BUCKET_POSTS = 2
MIN_HISTORY = 8
_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass
class Proposal:
    when: datetime
    reason: str
    score: float | None = None


def _zone(workspace) -> zoneinfo.ZoneInfo:
    try:
        return zoneinfo.ZoneInfo(workspace.effective_timezone or "UTC")
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return zoneinfo.ZoneInfo("UTC")


def _bucket(dt: datetime, zone) -> tuple[int, int]:
    local = dt.astimezone(zone)
    return local.weekday(), local.hour


def best_buckets(account) -> dict[tuple[int, int], float]:
    """``{(weekday, hour): ratio to the account's median}`` from its measured posts."""
    from .performance import measured

    items = [item for item in measured(account=account) if item.ratio is not None]
    if len(items) < MIN_HISTORY:
        return {}
    zone = _zone(account.workspace)
    grouped: dict[tuple[int, int], list[float]] = defaultdict(list)
    for item in items:
        grouped[_bucket(item.published_at, zone)].append(item.ratio)
    return {key: statistics.mean(values) for key, values in grouped.items() if len(values) >= MIN_BUCKET_POSTS}


def taken_times(workspace, *, exclude_brief=None, exclude_post_id=None) -> set[datetime]:
    """Times already offered to other work that hasn't been scheduled yet."""
    from apps.composer.models import Post

    from .models import StudioBrief

    taken: set[datetime] = set()
    posts = Post.objects.filter(
        workspace=workspace,
        proposed_publish_at__isnull=False,
        proposed_publish_at__gt=timezone.now(),
        platform_posts__status__in=("draft", "pending_review", "changes_requested", "approved", "pending_client"),
    )
    if exclude_post_id:
        posts = posts.exclude(pk=exclude_post_id)
    taken.update(posts.values_list("proposed_publish_at", flat=True).distinct())
    briefs = StudioBrief.objects.filter(
        workspace=workspace,
        proposed_publish_at__isnull=False,
        proposed_publish_at__gt=timezone.now(),
        status__in=(
            StudioBrief.Status.PLANNED,
            StudioBrief.Status.QUEUED,
            StudioBrief.Status.WORKING,
            StudioBrief.Status.READY,
        ),
    )
    if exclude_brief is not None:
        briefs = briefs.exclude(pk=exclude_brief.pk)
    taken.update(briefs.values_list("proposed_publish_at", flat=True))
    return taken


def _reason(account, when: datetime, score: float | None, zone) -> str:
    local = when.astimezone(zone)
    label = f"{_DAYS[local.weekday()]} {local:%H:%M}"
    name = account.account_name or account.get_platform_display()
    if score and score >= 1.1:
        return f"{label} — posts on {name} at this day and hour do {score:.1f}× your usual; the slot is free."
    return f"{label} — the next open posting slot on {name}."


def propose(
    workspace, accounts, *, exclude_brief=None, exclude_post_id=None, after: datetime | None = None
) -> Proposal:
    """The best open time across ``accounts`` (in order of preference)."""
    from apps.calendar.services import _next_slot_datetimes, _occupied_datetimes

    zone = _zone(workspace)
    start = max(after or timezone.now(), timezone.now() + LEAD_TIME)
    taken = taken_times(workspace, exclude_brief=exclude_brief, exclude_post_id=exclude_post_id)
    best: Proposal | None = None
    for account in accounts:
        try:
            occupied = _occupied_datetimes(account) | taken
            candidates = [c for c in _next_slot_datetimes(account, start, count=60) if c not in occupied]
        except Exception:
            logger.exception("Scheduler: could not read posting slots for account %s", account.pk)
            continue
        if not candidates:
            continue
        buckets = best_buckets(account)
        window = [c for c in candidates if c <= candidates[0] + HORIZON] or candidates[:1]
        if buckets:
            chosen = max(window, key=lambda c: (buckets.get(_bucket(c, zone), 1.0), -c.timestamp()))
            score = buckets.get(_bucket(chosen, zone))
        else:
            chosen, score = window[0], None
        proposal = Proposal(chosen, _reason(account, chosen, score, zone), score)
        if best is None or (proposal.score or 1.0) > (best.score or 1.0):
            best = proposal
        if best is not None and best.score is None:
            break  # no history to compare accounts by: the first account's first open slot
    if best is not None:
        return best

    local = (timezone.now() + LEAD_TIME).astimezone(zone)
    candidate = local.replace(hour=10, minute=0, second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5 or candidate in taken:
        candidate += timedelta(days=1)
    return Proposal(
        candidate, f"{_DAYS[candidate.weekday()]} 10:00 — no posting slots are set up, so a weekday morning."
    )
