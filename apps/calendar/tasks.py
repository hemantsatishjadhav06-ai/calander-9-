"""Background tasks for the Content Calendar (F-2.3)."""

import copy
import logging
import zoneinfo
from datetime import datetime, timedelta

from background_task import background
from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.utils import timezone

from apps.common.background import keep_schedule
from apps.composer.models import PlatformPost, Post, PostMedia

from .models import RecurrenceRule

logger = logging.getLogger(__name__)

LOOKAHEAD_DAYS = 90

# Registered on this interval by apps.calendar.apps. Occurrences are generated
# up to 90 days ahead, so once a day is plenty; hourly would only add churn.
RECURRENCE_INTERVAL_SECONDS = 60 * 60


@background(schedule=0)
@keep_schedule
def run_recurrence_cycle():
    """Recurring-task entry point around :func:`generate_recurring_posts`."""
    generate_recurring_posts()


def generate_recurring_posts():
    """Generate individual Post records from active RecurrenceRules.

    For each active rule, computes recurrence dates from the source post's
    scheduled_at up to 90 days ahead and clones the source post for each date
    the rule has not produced before (``RecurrenceRule.generated_dates``).
    Each occurrence is created in its own transaction, so a crash leaves no
    childless Post behind to block that date.
    """
    rules = RecurrenceRule.objects.filter(is_active=True).select_related("post__workspace")
    now = timezone.now()
    generated_total = 0

    for rule in rules:
        try:
            generated_total += _generate_for_rule(rule, now)
        except Exception:
            logger.exception("Recurrence generation failed for rule %s", rule.id)

    logger.info("Generated %d recurring posts.", generated_total)
    return generated_total


def _generate_for_rule(rule, now) -> int:
    source = rule.post
    if not source.scheduled_at:
        return 0
    # A held source is a held series: the client asked for nothing to go out.
    if source.platform_posts.filter(status=PlatformPost.Status.ON_HOLD).exists():
        return 0

    # Recurrence dates and times are computed in the post's workspace
    # timezone so the wall-clock time is preserved across DST boundaries
    # (a 09:00-local series stays at 09:00 local, not drifting by the DST
    # offset). ``scheduled_at`` is stored as UTC, so convert it back first.
    ws_tz = zoneinfo.ZoneInfo(source.workspace.effective_timezone or "UTC")
    local_start = source.scheduled_at.astimezone(ws_tz)
    base_date = local_start.date()
    base_time = local_start.time()
    today_local = now.astimezone(ws_tz).date()

    # Bound the lookahead horizon in the workspace's local calendar so it
    # lands on the same local day for every timezone, not the UTC date.
    cutoff = today_local + timedelta(days=LOOKAHEAD_DAYS)
    end = rule.end_date or cutoff
    if end > cutoff:
        end = cutoff

    already = set(rule.generated_dates or [])
    generated = 0
    for d in _compute_recurrence_dates(base_date, rule.frequency, rule.interval, end):
        key = d.isoformat()
        if key in already or d <= today_local:
            continue
        scheduled_dt = datetime.combine(d, base_time).replace(tzinfo=ws_tz)
        with transaction.atomic():
            _clone_occurrence(source, scheduled_dt)
            already.add(key)
            RecurrenceRule.objects.filter(pk=rule.pk).update(generated_dates=sorted(already), last_generated_at=now)
        generated += 1
    if not generated:
        RecurrenceRule.objects.filter(pk=rule.pk).update(last_generated_at=now)
    return generated


def _clone_occurrence(source, scheduled_dt):
    new_post = Post.objects.create(
        workspace=source.workspace,
        author=source.author,
        caption=source.caption,
        first_comment=source.first_comment,
        internal_notes=source.internal_notes,
        tags=source.tags,
        category=source.category,
        scheduled_at=scheduled_dt,
    )

    # Clone platform posts in bulk, preserving per-platform offsets
    source_pps = list(source.platform_posts.all())
    if source_pps:
        new_pps = []
        for pp in source_pps:
            # Preserve the offset between source PP's scheduled_at and
            # source post's scheduled_at, so per-platform time deltas
            # carry into each recurrence.
            pp_scheduled = None
            if pp.scheduled_at and source.scheduled_at:
                delta = pp.scheduled_at - source.scheduled_at
                pp_scheduled = scheduled_dt + delta
            new_pps.append(
                PlatformPost(
                    post=new_post,
                    social_account=pp.social_account,
                    platform_specific_caption=pp.platform_specific_caption,
                    platform_specific_first_comment=pp.platform_specific_first_comment,
                    platform_specific_media=pp.platform_specific_media,
                    # Carry per-platform settings (e.g. TikTok privacy level,
                    # comment/duet/stitch toggles, disclosure flags) into each
                    # recurrence. Without this the publisher falls back to
                    # provider defaults and loses the creator's choices.
                    platform_extra=copy.deepcopy(pp.platform_extra) if pp.platform_extra else {},
                    scheduled_at=pp_scheduled,
                    status="scheduled",
                )
            )
        PlatformPost.objects.bulk_create(new_pps)

        # Sync Post.scheduled_at to min of children.
        from apps.composer.services import sync_post_scheduled_at

        sync_post_scheduled_at(new_post)

    # Clone media attachments in bulk
    source_media = list(source.media_attachments.all())
    if source_media:
        PostMedia.objects.bulk_create(
            [
                PostMedia(
                    post=new_post,
                    media_asset=pm.media_asset,
                    position=pm.position,
                    alt_text=pm.alt_text,
                    platform_overrides=pm.platform_overrides,
                )
                for pm in source_media
            ]
        )
    return new_post


def _compute_recurrence_dates(base_date, frequency, interval, end_date):
    """Compute a list of recurrence dates from base_date to end_date.

    Every date is computed from ``base_date`` (``base + n * step``), never from
    the previous occurrence: stepping monthly from a clamped date turned a
    31st into the 28th for good after one February.
    """
    dates = []
    max_recurrences = LOOKAHEAD_DAYS * 2  # Safety limit
    for n in range(1, max_recurrences + 1):
        if frequency == "daily":
            current = base_date + timedelta(days=interval * n)
        elif frequency == "weekly":
            current = base_date + timedelta(weeks=interval * n)
        elif frequency == "monthly":
            current = base_date + relativedelta(months=interval * n)
        else:
            break
        if current > end_date:
            break
        dates.append(current)
    return dates
