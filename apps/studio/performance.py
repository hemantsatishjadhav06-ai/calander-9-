"""How well each published post did, measured fairly.

Platforms report different numbers and accounts have different audiences, so
a post is only ever compared with the other posts of its own account: its
**percentile** (0–1) and its **ratio** to that account's median on one metric
— the engagement rate where the platform reports one, otherwise the
platform's main metric (reach, impressions, views...). Posts younger than
``MIN_AGE`` are left out (their numbers are still climbing), and an account
needs ``MIN_POSTS`` measured posts before anything is ranked.

Snapshot values are cumulative per day, so the newest row is the post's
lifetime value (``apps.analytics.services._latest_post_stats``). Everything
here is read-only and runs in the worker.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db.models import F
from django.utils import timezone

MIN_AGE = timedelta(days=3)
MIN_POSTS = 5
LOOKBACK = timedelta(days=180)
# A recent publication date does not make an old analytics snapshot current.
MAX_METRIC_AGE = timedelta(days=7)


@dataclass
class Measured:
    platform_post_id: object
    post_id: object
    account_id: object
    platform: str
    published_at: datetime
    metric: str
    value: float
    percentile: float | None = None
    ratio: float | None = None
    captured_at: datetime | None = None


def score_metric(platform: str) -> str | None:
    from apps.analytics.metrics import PLATFORM_METRICS, PLATFORM_PRIMARY

    if "engagement" in PLATFORM_METRICS.get(platform, []):
        return "engagement"
    return PLATFORM_PRIMARY.get(platform)


def fresh_post_stats(post_ids, metrics: list[str], *, now: datetime | None = None) -> dict:
    """Latest successful values captured recently and before the reference time.

    Keep the capture time alongside the value, so memory cards and reports can
    distinguish fresh evidence from an old stored score. Failed snapshots and
    measurements captured after a historical cutoff never grant a ranking.
    """
    from apps.analytics.models import PostInsightsSnapshot

    now = now or timezone.now()
    rows = (
        PostInsightsSnapshot.objects.filter(
            platform_post_id__in=list(post_ids),
            metric_key__in=metrics,
            captured_at__gte=now - MAX_METRIC_AGE,
            captured_at__lte=now,
            date__lte=now.date(),
            errors={},
        )
        .order_by("platform_post_id", "metric_key", "-captured_at", "-date", "-pk")
        .values_list("platform_post_id", "metric_key", "value", "captured_at")
    )
    stats: dict = {}
    for pp_id, metric, value, captured in rows:
        numeric = float(value)
        if math.isfinite(numeric) and numeric >= 0:
            stats.setdefault(pp_id, {}).setdefault(metric, (numeric, captured))
    return stats


def measured(
    *, workspace=None, account=None, since: datetime | None = None, now: datetime | None = None
) -> list[Measured]:
    """Published posts with a value on their account's score metric, ranked within the account."""
    from apps.composer.models import PlatformPost

    from .jobtypes.plan import zone_of

    now = now or timezone.now()
    target_workspace = workspace or (account.workspace if account is not None else None)
    if target_workspace is not None:
        now = now.astimezone(zone_of(target_workspace))
    since = since or now - LOOKBACK
    published = PlatformPost.objects.filter(
        status=PlatformPost.Status.PUBLISHED,
        published_at__isnull=False,
        published_at__gte=since,
        published_at__lte=now - MIN_AGE,
        social_account__workspace_id=F("post__workspace_id"),
    )
    if workspace is not None:
        published = published.filter(post__workspace=workspace)
    if account is not None:
        published = published.filter(social_account=account)
    rows = published.values_list("id", "post_id", "social_account_id", "social_account__platform", "published_at")
    by_platform: dict[str, list[tuple]] = {}
    for row in rows:
        by_platform.setdefault(row[3], []).append(row)

    out: list[Measured] = []
    for platform, items in by_platform.items():
        metric = score_metric(platform)
        if not metric:
            continue
        stats = fresh_post_stats([item[0] for item in items], [metric], now=now)
        for pp_id, post_id, account_id, _platform, published_at in items:
            evidence = stats.get(pp_id, {}).get(metric)
            if evidence is None:
                continue
            value, captured_at = evidence
            out.append(
                Measured(pp_id, post_id, account_id, platform, published_at, metric, value, captured_at=captured_at)
            )
    _rank(out)
    return out


def _rank(items: list[Measured]) -> None:
    by_account: dict[object, list[Measured]] = {}
    for item in items:
        by_account.setdefault(item.account_id, []).append(item)
    for group in by_account.values():
        if len(group) < MIN_POSTS:
            continue
        values = sorted(item.value for item in group)
        median = statistics.median(values)
        count = len(values)
        for item in group:
            below = sum(1 for v in values if v < item.value)
            equal = sum(1 for v in values if v == item.value)
            item.percentile = round((below + 0.5 * equal) / count, 4)
            item.ratio = round(item.value / median, 3) if median > 0 else None
