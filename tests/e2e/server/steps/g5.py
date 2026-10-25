"""Steps for golden paths 9 and 10: a comment in the Inbox, and the brand colour and timezone.

Path 9 needs no fixture: the comment arrives the real way, as a signed Facebook webhook the test
posts for the seeded Facebook page of workspace A. Its probes:

- ``inbox_message`` (``?comment_id=``): the inbox message that comment became in workspace A, its
  replies (oldest first) and how many "new inbox message" notifications each person got for it.
- ``inbox_platform_calls`` (``?since=<epoch>``): the Facebook calls the mock transport answered
  since then (method, host and path), so a test can see the reply reached the platform once, or not
  at all.

Path 10's fixture, ``brand_timezone_workspace``, makes a workspace with a blank timezone in its own
organisation (default ``timezone``, Asia/Dubai unless given), with a fresh owner and a fresh editor
who both land on it, a connected LinkedIn company account, the brand profile, and a post the editor
submitted and the owner approved in the dashboard, scheduled ``days_ahead`` days ahead at ``hour``
o'clock organisation time. Fresh people, so changing their workspace or organisation never changes
what another test sees for the seeded ones. It answers the ids, the scheduled instant, and the
calendar week cell (local date and hour) the post sits in under ``timezone`` and under
``then_timezone``. Its probe, ``brand_timezone_state`` (``?workspace_id=``), reads the brand colours,
the workspace's and the organisation's timezones, and each platform post with its approval fields
and the gate's fingerprint of it now.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime, time, timedelta
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, available_timezones

from .. import mocks, seed
from ..registry import PayloadError, fixture, optional_number, optional_str, probe, require_number, require_str


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None


def _email(user: Any) -> str | None:
    return user.email if user is not None else None


def _uuid(payload: dict[str, Any], key: str) -> uuid.UUID:
    value = require_str(payload, key)
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise PayloadError(f"'{key}' must be a UUID.") from exc


def _int_in(payload: dict[str, Any], key: str, default: int, low: int, high: int) -> int:
    if payload.get(key) in (None, ""):
        return default
    number = require_number(payload, key)
    if number != int(number) or not low <= number <= high:
        raise PayloadError(f"'{key}' must be a whole number from {low} to {high}.")
    return int(number)


def _zone(payload: dict[str, Any], key: str, default: str) -> str:
    name = optional_str(payload, key, default)
    if name not in available_timezones():
        raise PayloadError(f"'{key}' must be an IANA timezone name, such as {default}.")
    return name


def _week_cell(when: datetime, zone: str) -> dict[str, str]:
    """The week view's cell for ``when`` shown in ``zone``: its local date and the hour it starts."""
    local = when.astimezone(ZoneInfo(zone))
    return {"date": local.strftime("%Y-%m-%d"), "time": f"{local.hour:02d}:00"}


# ---------------------------------------------------------------------------
# Path 9: the Inbox
# ---------------------------------------------------------------------------


@probe("inbox_message")
def inbox_message(params: dict[str, Any]) -> dict[str, Any]:
    """The inbox message a Facebook comment became in workspace A, its replies and notifications."""
    from apps.inbox.models import InboxMessage
    from apps.notifications.models import EventType, Notification

    comment_id = require_str(params, "comment_id")
    message = (
        InboxMessage.objects.select_related("assigned_to")
        .filter(workspace_id=seed.WORKSPACE_A_ID, platform_message_id=comment_id)
        .first()
    )
    if message is None:
        return {"message": None, "replies": [], "notifications": {}}
    replies = [
        {
            "id": str(reply.pk),
            "status": reply.status,
            "body": reply.body,
            "author": _email(reply.author),
            "platform_reply_id": reply.platform_reply_id,
            "sent_at": _iso(reply.sent_at),
        }
        for reply in message.replies.select_related("author").order_by("created_at", "id")
    ]
    notified = Counter(
        Notification.objects.filter(
            event_type=EventType.NEW_INBOX_MESSAGE, data__message_id=str(message.pk)
        ).values_list("user__email", flat=True)
    )
    return {
        "message": {
            "id": str(message.pk),
            "workspace_id": str(message.workspace_id),
            "account_id": str(message.social_account_id),
            "message_type": message.message_type,
            "status": message.status,
            "body": message.body,
            "sender_name": message.sender_name,
            "assigned_to": _email(message.assigned_to),
        },
        "replies": replies,
        "notifications": dict(notified),
    }


@probe("inbox_platform_calls")
def inbox_platform_calls(params: dict[str, Any]) -> dict[str, Any]:
    """The Facebook calls the mock transport answered since ``since`` (method, host, path)."""
    from providers import facebook

    since = optional_number(params, "since")
    host = urlsplit(facebook.BASE_URL).hostname
    calls = [
        {"method": str(item["method"]), "host": str(item["host"]), "url": str(item["url"])}
        for item in mocks.answered(since)
        if item.get("host") == host
    ]
    return {"calls": calls}


# ---------------------------------------------------------------------------
# Path 10: the brand colour and the timezone
# ---------------------------------------------------------------------------


@fixture("brand_timezone_workspace")
def brand_timezone_workspace(payload: dict[str, Any]) -> dict[str, Any]:
    """A blank-timezone workspace in its own organisation, with a post approved and scheduled."""
    from django.utils import timezone

    from apps.approvals.actor import DASHBOARD, acting_as
    from apps.approvals.services import approve_post, submit_for_review
    from apps.composer.models import PlatformPost, Post
    from apps.composer.services import transition_platform_post
    from apps.members.models import OrgMembership, WorkspaceMembership
    from apps.organizations.models import Organization
    from apps.social_accounts.models import SocialAccount
    from apps.studio.brand_defaults import ensure_profile
    from apps.studio.models import BrandProfile
    from apps.workspaces.models import Workspace

    first_zone = _zone(payload, "timezone", "Asia/Dubai")
    then_zone = _zone(payload, "then_timezone", "Asia/Tokyo")
    days_ahead = _int_in(payload, "days_ahead", 3, 1, 60)
    hour = _int_in(payload, "hour", 10, 0, 23)

    suffix = uuid.uuid4().hex[:8]
    now = timezone.now()
    owner = seed._person(f"owner-{suffix}@brand-tz.e2e.test", "Omar Owner")
    editor = seed._person(f"editor-{suffix}@brand-tz.e2e.test", "Esha Editor")
    org = Organization.objects.create(name=f"Brand and time {suffix}", default_timezone=first_zone)
    workspace = Workspace.objects.create(
        organization=org,
        name=f"Lakeside {suffix}",
        timezone="",
        approval_workflow_mode=Workspace.ApprovalWorkflowMode.REQUIRED_INTERNAL,
        require_dashboard_approval=True,
    )
    for person, org_role, role in (
        (owner, OrgMembership.OrgRole.OWNER, WorkspaceMembership.WorkspaceRole.OWNER),
        (editor, OrgMembership.OrgRole.MEMBER, WorkspaceMembership.WorkspaceRole.EDITOR),
    ):
        OrgMembership.objects.create(user=person, organization=org, org_role=org_role)
        WorkspaceMembership.objects.create(user=person, workspace=workspace, workspace_role=role)
        person.last_workspace_id = workspace.pk
        person.save(update_fields=["last_workspace_id"])

    account = SocialAccount(
        workspace=workspace,
        platform="linkedin_company",
        account_platform_id=f"e2e-li-org-{suffix}",
        account_name=f"Lakeside {suffix}",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        oauth_access_token=f"e2e-token-linkedin-{suffix}",
        follower_count=900,
    )
    # Connected long ago, as in the seed: no first-connect analytics backfill (it would meet the mock).
    account.__dict__["_skip_analytics_backfill"] = True
    account.save()

    profile = ensure_profile(workspace)
    # Saved an hour ago, so a save in the test always moves the sample image's ?v= (whole seconds).
    BrandProfile.objects.filter(pk=profile.pk).update(updated_at=now - timedelta(hours=1))

    day = (now.astimezone(ZoneInfo(first_zone)) + timedelta(days=days_ahead)).date()
    when = datetime.combine(day, time(hour), tzinfo=ZoneInfo(first_zone))
    post = Post.objects.create(
        workspace=workspace,
        author=editor,
        caption=f"E2E {suffix}: site visits every Saturday at the Lakeside site office, 10:00 to 17:00.",
        proposed_publish_at=when,
    )
    PlatformPost.objects.create(post=post, social_account=account, status=PlatformPost.Status.DRAFT)
    with acting_as(editor, DASHBOARD):
        submit_for_review(post, editor, workspace)
    with acting_as(owner, DASHBOARD):
        approve_post(post, owner, workspace)
        for pp in post.platform_posts.filter(status=PlatformPost.Status.APPROVED).select_related("post__workspace"):
            transition_platform_post(pp, PlatformPost.Status.SCHEDULED, scheduled_at=pp.approved_publish_at)
    platform_post = post.platform_posts.get()
    if platform_post.status != PlatformPost.Status.SCHEDULED:
        raise RuntimeError(f"The post was not scheduled (it is {platform_post.status}).")

    return {
        "workspace_id": str(workspace.pk),
        "organisation_id": str(org.pk),
        "owner": {"id": str(owner.pk), "email": owner.email},
        "editor": {"id": str(editor.pk), "email": editor.email},
        "post_id": str(post.pk),
        "platform_post_id": str(platform_post.pk),
        "scheduled_at": _iso(platform_post.scheduled_at),
        "local_before": _week_cell(when, first_zone),
        "local_after": _week_cell(when, then_zone),
    }


@probe("brand_timezone_state")
def brand_timezone_state(params: dict[str, Any]) -> dict[str, Any]:
    """The brand colours, the workspace's and organisation's timezones, and the scheduled posts."""
    from apps.approvals import gate
    from apps.composer.models import PlatformPost
    from apps.studio.models import BrandProfile
    from apps.workspaces.models import Workspace

    workspace_id = _uuid(params, "workspace_id")
    workspace = Workspace.objects.select_related("organization").filter(pk=workspace_id).first()
    if workspace is None:
        raise PayloadError(f"No workspace {workspace_id}.")
    profile = BrandProfile.objects.filter(workspace=workspace).first()
    platform_posts = (
        PlatformPost.objects.filter(post__workspace=workspace)
        .select_related("post__workspace", "social_account")
        .order_by("created_at", "id")
    )
    return {
        "brand": {
            "primary_color": profile.primary_color if profile else None,
            "accent_color": profile.accent_color if profile else None,
            "updated_at": _iso(profile.updated_at) if profile else None,
        },
        "workspace": {"timezone": workspace.timezone, "effective_timezone": workspace.effective_timezone},
        "organisation": {"default_timezone": workspace.organization.default_timezone},
        "platform_posts": [
            {
                "id": str(pp.pk),
                "status": pp.status,
                "scheduled_at": _iso(pp.scheduled_at),
                "approved_fingerprint": pp.approved_fingerprint,
                "fingerprint": gate.fingerprint(pp),
                "approved_publish_at": _iso(pp.approved_publish_at),
            }
            for pp in platform_posts
        ],
    }
