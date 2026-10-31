"""Steps for golden paths 4, 5 and 7: writing a post in the composer, Approve & schedule, and moving
a scheduled post on the calendar.

Fixtures (workspace A):

- ``publishing_review_post``: a post submitted for review by its author in the dashboard, with a
  proposed time ``days_ahead`` days from today at ``hour`` o'clock workspace time.
- ``publishing_scheduled_post``: the same post, then approved by an internal approver in the
  dashboard (the gate stamps the fingerprint and the time) and scheduled at its approved time.

Payload, both: ``author`` (a seeded role, default ``editor``), ``accounts`` (seeded account keys,
default ``["linkedin_company"]``), ``days_ahead`` (1 to 60, default 3), ``hour`` (0 to 23, default
11), ``caption`` (optional); the scheduled one also takes ``approver`` (default ``owner``).

Probe: ``publishing_post`` (``?post_id=``): the post, each platform post with the gate's fingerprint
of it computed now, the media in order and every approval action, oldest first.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .. import seed
from ..registry import PayloadError, fixture, optional_str, probe, require_number, require_str


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None


def _email(user: Any) -> str | None:
    return user.email if user is not None else None


def _int_in(payload: dict[str, Any], key: str, default: int, low: int, high: int) -> int:
    if payload.get(key) in (None, ""):
        return default
    number = require_number(payload, key)
    if number != int(number) or not low <= number <= high:
        raise PayloadError(f"'{key}' must be a whole number from {low} to {high}.")
    return int(number)


def _person(payload: dict[str, Any], key: str, default: str) -> Any:
    from apps.accounts.models import User

    role = optional_str(payload, key, default)
    if role not in seed.USERS or role == "owner_b":
        roles = ", ".join(name for name in seed.USERS if name != "owner_b")
        raise PayloadError(f"'{key}' must be a role of workspace A: {roles}.")
    return User.objects.get(email=seed.USERS[role][0])


def _accounts(payload: dict[str, Any], workspace: Any) -> list[Any]:
    from apps.social_accounts.models import SocialAccount

    keys = payload.get("accounts", ["linkedin_company"])
    if not isinstance(keys, list) or not keys or not all(isinstance(key, str) for key in keys):
        raise PayloadError("'accounts' must be a non-empty list of account keys.")
    unknown = [key for key in keys if key not in seed.ACCOUNTS]
    if unknown or len(set(keys)) != len(keys):
        raise PayloadError(f"'accounts' takes each of {', '.join(seed.ACCOUNTS)} at most once.")
    return [
        SocialAccount.objects.get(workspace=workspace, platform=key, account_platform_id=seed.ACCOUNTS[key][2])
        for key in keys
    ]


def _review_post(payload: dict[str, Any]) -> tuple[Any, Any, datetime]:
    """A post with one draft platform post per account, submitted for review by its author."""
    from django.utils import timezone

    from apps.approvals.actor import DASHBOARD, acting_as
    from apps.approvals.services import submit_for_review
    from apps.composer.models import PlatformPost, Post
    from apps.workspaces.models import Workspace

    workspace = Workspace.objects.get(pk=seed.WORKSPACE_A_ID)
    author = _person(payload, "author", "editor")
    accounts = _accounts(payload, workspace)
    days_ahead = _int_in(payload, "days_ahead", 3, 1, 60)
    hour = _int_in(payload, "hour", 11, 0, 23)
    caption = optional_str(payload, "caption") or (
        f"E2E {uuid.uuid4().hex[:8]}: site visits every Saturday at the Kokapet site office, 10:00 to 17:00."
    )

    zone = ZoneInfo(workspace.effective_timezone or "UTC")
    day = (timezone.now().astimezone(zone) + timedelta(days=days_ahead)).date()
    when = datetime.combine(day, time(hour), tzinfo=zone)

    post = Post.objects.create(workspace=workspace, author=author, caption=caption, proposed_publish_at=when)
    for account in accounts:
        PlatformPost.objects.create(post=post, social_account=account, status=PlatformPost.Status.DRAFT)
    with acting_as(author, DASHBOARD):
        submit_for_review(post, author, workspace)
    if post.platform_posts.exclude(status=PlatformPost.Status.PENDING_REVIEW).exists():
        raise RuntimeError("The post did not reach pending_review.")
    return post, workspace, when


def _answer(post: Any, when: datetime) -> dict[str, Any]:
    """The fixture's answer; ``when`` is in the workspace's timezone, so ``local`` is its wall time."""
    return {
        "post_id": str(post.pk),
        "platform_posts": [
            {"id": str(pp.pk), "platform": pp.social_account.platform, "account_id": str(pp.social_account_id)}
            for pp in post.platform_posts.select_related("social_account").order_by("social_account__platform")
        ],
        "proposed_publish_at": _iso(when),
        "local": {"date": when.strftime("%Y-%m-%d"), "time": when.strftime("%H:%M"), "hour": when.hour},
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@fixture("publishing_review_post")
def publishing_review_post(payload: dict[str, Any]) -> dict[str, Any]:
    """A post waiting for review with a proposed time; its ids, the time and its local date and hour."""
    post, _workspace, when = _review_post(payload)
    return _answer(post, when)


@fixture("publishing_scheduled_post")
def publishing_scheduled_post(payload: dict[str, Any]) -> dict[str, Any]:
    """A post approved by an internal approver in the dashboard and scheduled at its approved time."""
    from apps.approvals.actor import DASHBOARD, acting_as, is_internal_approver
    from apps.approvals.services import approve_post
    from apps.composer.models import PlatformPost
    from apps.composer.services import transition_platform_post

    approver = _person(payload, "approver", "owner")
    post, workspace, when = _review_post(payload)
    if not is_internal_approver(approver, workspace):
        raise PayloadError(f"{approver.email} cannot approve in workspace A.")
    with acting_as(approver, DASHBOARD):
        approve_post(post, approver, workspace)
        for pp in post.platform_posts.filter(status=PlatformPost.Status.APPROVED).select_related("post__workspace"):
            transition_platform_post(pp, PlatformPost.Status.SCHEDULED, scheduled_at=pp.approved_publish_at)
    if post.platform_posts.exclude(status=PlatformPost.Status.SCHEDULED).exists():
        raise RuntimeError("The post was not scheduled at its approved time.")
    return {**_answer(post, when), "scheduled_at": _iso(when)}


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------


@probe("publishing_post")
def publishing_post(params: dict[str, Any]) -> dict[str, Any]:
    """The post, its platform posts (with the gate's fingerprint now), media and approval actions."""
    from apps.approvals import gate
    from apps.approvals.models import ApprovalAction
    from apps.composer.models import Post

    raw = require_str(params, "post_id")
    try:
        post_id = uuid.UUID(raw)
    except ValueError as exc:
        raise PayloadError("'post_id' must be a UUID.") from exc
    post = Post.objects.select_related("author").filter(pk=post_id).first()
    if post is None:
        return {"post": None, "platform_posts": [], "media": [], "actions": []}

    platform_posts = []
    rows = post.platform_posts.select_related("social_account", "approved_by", "post__workspace")
    for pp in rows.order_by("social_account__platform", "id"):
        platform_posts.append(
            {
                "id": str(pp.pk),
                "account_id": str(pp.social_account_id),
                "platform": pp.social_account.platform,
                "status": pp.status,
                "platform_specific_caption": pp.platform_specific_caption,
                "scheduled_at": _iso(pp.scheduled_at),
                "approved_fingerprint": pp.approved_fingerprint,
                "fingerprint": gate.fingerprint(pp),
                "approved_by": _email(pp.approved_by),
                "approved_at": _iso(pp.approved_at),
                "approved_publish_at": _iso(pp.approved_publish_at),
                "approved_revision": pp.approved_revision,
            }
        )
    media = [
        {"asset_id": str(pm.media_asset_id), "position": pm.position}
        for pm in post.media_attachments.order_by("position", "id")
    ]
    actions = [
        {
            "action": action.action,
            "channel": action.channel,
            "user": _email(action.user),
            "platform_post_id": str(action.platform_post_id) if action.platform_post_id else None,
            "fingerprint": action.fingerprint,
            "publish_at": _iso(action.publish_at),
            "comment": action.comment,
            "created_at": _iso(action.created_at),
        }
        for action in ApprovalAction.objects.filter(post=post).select_related("user").order_by("created_at", "id")
    ]
    return {
        "post": {
            "id": str(post.pk),
            "caption": post.caption,
            "author": _email(post.author),
            "proposed_publish_at": _iso(post.proposed_publish_at),
            "scheduled_at": _iso(post.scheduled_at),
        },
        "platform_posts": platform_posts,
        "media": media,
        "actions": actions,
    }
