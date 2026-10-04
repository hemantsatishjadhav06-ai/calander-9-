"""Data for the phone screens.

Everything here reads the same models the desktop pages read and follows the
same rules: a post waits for an approver while any of its channels is pending,
and times are shown in the workspace's timezone. The phone and the laptop
therefore always agree about what is waiting.
"""

from __future__ import annotations

import zoneinfo
from datetime import datetime, time, timedelta

from django.db.models import Count, Exists, F, OuterRef, Q
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.composer.models import PlatformPost, Post

#: A post waits for an approver while any of its channels is in one of these.
PENDING = ("pending_review", "pending_client")
#: How many approval cards and schedule rows Today shows before "See all".
TODAY_APPROVALS = 3
TODAY_SCHEDULE = 12
TODAY_MESSAGES = 3

_SHORT_PLATFORM_NAMES = {
    "instagram_login": "Instagram",
    "linkedin_personal": "LinkedIn",
    "linkedin_company": "LinkedIn",
    "google_business": "Google Business",
    "x": "X",
    "devto": "DEV",
}


def platform_name(value: str) -> str:
    """Short public name of a platform key ("instagram_login" -> "Instagram")."""
    if value in _SHORT_PLATFORM_NAMES:
        return _SHORT_PLATFORM_NAMES[value]
    from apps.credentials.models import PlatformCredential

    try:
        return str(PlatformCredential.Platform(value).label)
    except ValueError:
        return value.replace("_", " ").title()


def platform_names(values) -> list[str]:
    """Distinct short names, first-seen order ("Facebook", "Instagram")."""
    names: list[str] = []
    for value in values:
        name = platform_name(value)
        if name not in names:
            names.append(name)
    return names


def workspace_tz(workspace) -> zoneinfo.ZoneInfo:
    try:
        return zoneinfo.ZoneInfo(workspace.effective_timezone or "UTC")
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return zoneinfo.ZoneInfo("UTC")


def brand_summaries(workspaces) -> list[dict]:
    """One row per workspace: its connected platforms and how many posts wait for approval.

    Two queries for any number of workspaces.
    """
    from apps.social_accounts.models import SocialAccount

    workspaces = list(workspaces)
    ids = [ws.id for ws in workspaces]
    if not ids:
        return []
    platforms: dict = {ws_id: [] for ws_id in ids}
    rows = (
        SocialAccount.objects.filter(workspace_id__in=ids, connection_status=SocialAccount.ConnectionStatus.CONNECTED)
        .order_by("platform")
        .values_list("workspace_id", "platform")
        .distinct()
    )
    for ws_id, platform in rows:
        platforms[ws_id].append(platform)
    pending = dict(
        PlatformPost.objects.filter(post__workspace_id__in=ids, status__in=PENDING)
        .values_list("post__workspace_id")
        .annotate(n=Count("post_id", distinct=True))
        .values_list("post__workspace_id", "n")
    )
    return [
        {
            "workspace": ws,
            "platforms": platform_names(platforms.get(ws.id, [])),
            "pending": pending.get(ws.id, 0),
        }
        for ws in workspaces
    ]


def thumbnail_url(post) -> str:
    """URL of the post's first image (or video poster), '' when it has none."""
    for attachment in post.media_attachments.all():
        asset = attachment.media_asset
        if asset is None:
            continue
        if getattr(asset, "thumbnail", None):
            return asset.thumbnail.url
        if asset.file and asset.media_type == "image":
            return asset.file.url
    return ""


def decorate(post, *, now=None):
    """Attach what the phone cards show to a post fetched with its channels and media prefetched."""
    now = now or timezone.now()
    channels = list(post.platform_posts.all())
    post.when = post.scheduled_at or post.proposed_publish_at
    post.is_past = bool(post.when and post.when <= now)
    post.is_actionable = any(pp.status in PENDING for pp in channels)
    post.channel_platforms = []
    for pp in channels:
        platform = pp.social_account.platform
        if platform not in post.channel_platforms:
            post.channel_platforms.append(platform)
    post.thumb = thumbnail_url(post)
    caption = (post.caption or "").strip()
    if post.title:
        headline, rest = post.title, caption
    else:
        first, _, rest = caption.partition("\n")
        headline = (first[:120] + "…") if len(first) > 120 else (first or "(no caption)")
    post.headline = headline
    # One flowing paragraph: a three-line preview has no room for blank lines.
    post.preview = " ".join(rest.split())
    return post


def _with_details(qs):
    return qs.select_related("author").prefetch_related(
        "platform_posts__social_account", "media_attachments__media_asset"
    )


def approval_queue(workspace, *, limit=None):
    """Posts waiting for an approver, the soonest publish time first."""
    pending = PlatformPost.objects.filter(post_id=OuterRef("pk"), status__in=PENDING)
    qs = _with_details(
        Post.objects.for_workspace(workspace.id)
        .filter(Exists(pending))
        .annotate(sort_time=Coalesce("scheduled_at", "proposed_publish_at"))
        .order_by(F("sort_time").asc(nulls_last=True), "-created_at")
    )
    return list(qs[:limit] if limit else qs)


def day_label(day, today) -> str:
    if day == today:
        return "Today"
    if day == today + timedelta(days=1):
        return "Tomorrow"
    if day == today - timedelta(days=1):
        return "Yesterday"
    return f"{day:%a} {day.day} {day:%b}"


def week_schedule(workspace, *, now=None, limit=TODAY_SCHEDULE):
    """Posts going out (or proposed, or already out) from the start of today to seven days ahead.

    Returns ``[{"label": "Today", "posts": [...]}, ...]`` in time order, in the
    workspace's timezone.
    """
    now = now or timezone.now()
    tz = workspace_tz(workspace)
    today = now.astimezone(tz).date()
    start = datetime.combine(today, time.min, tzinfo=tz)
    end = start + timedelta(days=7)
    live = PlatformPost.objects.filter(post_id=OuterRef("pk")).exclude(status__in=("rejected",))
    qs = _with_details(
        Post.objects.for_workspace(workspace.id)
        .filter(Exists(live))
        .annotate(sort_time=Coalesce("published_at", "scheduled_at", "proposed_publish_at"))
        .filter(sort_time__gte=start, sort_time__lt=end)
        .order_by("sort_time", "created_at")
    )
    groups: list[dict] = []
    for post in qs[:limit]:
        decorate(post, now=now)
        local = post.sort_time.astimezone(tz)
        label = day_label(local.date(), today)
        post.local_time = local
        if not groups or groups[-1]["label"] != label:
            groups.append({"label": label, "posts": []})
        groups[-1]["posts"].append(post)
    return groups


def scheduled_count(workspace, *, now=None, days=7) -> int:
    """Posts with a channel on the schedule in the next *days* days."""
    now = now or timezone.now()
    return (
        PlatformPost.objects.filter(post__workspace_id=workspace.id, status="scheduled")
        .annotate(when=Coalesce("scheduled_at", "post__scheduled_at"))
        .filter(when__gte=now, when__lt=now + timedelta(days=days))
        .values("post_id")
        .distinct()
        .count()
    )


def failed_count(workspace, *, now=None, days=14) -> int:
    """Posts with a channel that failed to publish in the last *days* days."""
    now = now or timezone.now()
    return (
        PlatformPost.objects.filter(
            post__workspace_id=workspace.id, status="failed", updated_at__gte=now - timedelta(days=days)
        )
        .values("post_id")
        .distinct()
        .count()
    )


def unread_messages(workspace, *, limit=TODAY_MESSAGES):
    from apps.inbox.models import InboxMessage

    return list(
        InboxMessage.objects.for_workspace(workspace.id)
        .filter(status=InboxMessage.Status.UNREAD)
        .select_related("social_account")
        .order_by("-received_at")[:limit]
    )


def can_approve(request) -> bool:
    membership = getattr(request, "workspace_membership", None)
    perms = membership.effective_permissions if membership else {}
    return bool(perms.get("approve_posts"))


def today_context(request, workspace) -> dict:
    now = timezone.now()
    tz = workspace_tz(workspace)
    approvals = [decorate(p, now=now) for p in approval_queue(workspace, limit=TODAY_APPROVALS)]
    return {
        "now_local": now.astimezone(tz),
        "approvals": approvals,
        "overdue_count": sum(1 for p in approvals if p.is_past),
        "schedule": week_schedule(workspace, now=now),
        "scheduled_count": scheduled_count(workspace, now=now),
        "failed_count": failed_count(workspace, now=now),
        "blog": blog_counts(workspace),
        # Not "messages": that name is Django's flash messages in every template.
        "inbox_messages": unread_messages(workspace),
        "can_approve": can_approve(request),
        "display_timezone": str(tz),
    }


def blog_counts(workspace) -> dict:
    """Blog posts awaiting approval and blog posts live, in one query."""
    from apps.blog.models import BlogPost

    return BlogPost.objects.filter(workspace=workspace).aggregate(
        pending=Count("id", filter=Q(status=BlogPost.Status.PENDING_REVIEW)),
        live=Count("id", filter=Q(status=BlogPost.Status.PUBLISHED)),
    )
