"""Steps for golden paths 6 and 8: a two-stage workspace, where a post needs the internal approval
and then the client's.

Each fixture makes its own organisation and workspace (``required_internal_and_client``, approval
in the dashboard required, Asia/Kolkata) with a fresh owner (the agency lead, an internal approver)
and a fresh client, a connected LinkedIn company account with its posting slots, the brand profile,
verified facts and the agency settings, so nothing an earlier test did can change what this one
sees. On top of that:

* ``two_stage_brief`` asks the team for a post (``services.create_brief``); the in-process worker
  runs the pipeline with the faked agents and sends it for approval (golden path 6).
* ``client_stage_post`` writes a post waiting for review and has the owner approve it through the
  real approvals service, acting as the owner in the dashboard, so it waits for the client with the
  gate's fingerprint (golden path 8).

Probes: ``two_stage_state`` (a brief or a post: its platform posts with their approval fields and
the gate's fingerprint of the content now, every approval action, the publish logs) and
``magic_link_state`` (whether a portal link was used).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from .. import seed
from ..registry import PayloadError, fixture, probe, require_str

TWO_STAGE_TIMEZONE = "Asia/Kolkata"
IDEA = "Invite families to the Saturday site visits at the Kokapet towers"
POST_TITLE = "Saturday site visits at Kokapet"
POST_CAPTION = (
    "Site visits run every Saturday, 10:00 to 17:00, at the Kokapet site office. "
    "Free parking on visit days. WhatsApp the sales office for the availability list."
)


def _uuid(payload: dict[str, Any], key: str) -> uuid.UUID:
    value = require_str(payload, key)
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise PayloadError(f"'{key}' must be a UUID.") from exc


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _email(user: Any) -> str | None:
    return user.email if user is not None else None


def _person_ref(user: Any) -> dict[str, str]:
    return {"id": str(user.pk), "email": user.email}


def _two_stage_world() -> dict[str, Any]:
    """A fresh two-stage workspace with its owner, client, LinkedIn account, brand and agency settings."""
    from django.utils import timezone

    from apps.calendar.services import create_default_queue_and_slots
    from apps.members.models import OrgMembership, WorkspaceMembership
    from apps.organizations.models import Organization
    from apps.social_accounts.models import SocialAccount
    from apps.studio.brand_defaults import ensure_profile
    from apps.studio.models import AgencySettings, BrandClaim
    from apps.workspaces.models import Workspace

    suffix = uuid.uuid4().hex[:8]
    now = timezone.now()
    owner = seed._person(f"owner-{suffix}@two-stage.e2e.test", "Tara Twostage")
    client = seed._person(f"client-{suffix}@two-stage.e2e.test", "Kiran Client")
    org = Organization.objects.create(name=f"Two-stage Agency {suffix}", default_timezone=TWO_STAGE_TIMEZONE)
    workspace = Workspace.objects.create(
        organization=org,
        name=f"Riverside {suffix}",
        timezone=TWO_STAGE_TIMEZONE,
        approval_workflow_mode=Workspace.ApprovalWorkflowMode.REQUIRED_INTERNAL_AND_CLIENT,
        require_dashboard_approval=True,
    )
    for user, org_role, role in (
        (owner, OrgMembership.OrgRole.OWNER, WorkspaceMembership.WorkspaceRole.OWNER),
        (client, OrgMembership.OrgRole.MEMBER, WorkspaceMembership.WorkspaceRole.CLIENT),
    ):
        OrgMembership.objects.create(user=user, organization=org, org_role=org_role)
        WorkspaceMembership.objects.create(user=user, workspace=workspace, workspace_role=role)
        user.last_workspace_id = workspace.pk
        user.save(update_fields=["last_workspace_id"])

    account = SocialAccount(
        workspace=workspace,
        platform="linkedin_company",
        account_platform_id=f"e2e-li-org-{suffix}",
        account_name=f"Riverside Homes {suffix}",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        oauth_access_token="e2e-token-linkedin-two-stage",
        follower_count=900,
    )
    # Connected long ago, as in the seed: no first-connect analytics backfill (it would only meet the mock).
    account.__dict__["_skip_analytics_backfill"] = True
    account.save()
    create_default_queue_and_slots(account)

    profile = ensure_profile(workspace)
    profile.audience = "Families buying their first home in West Hyderabad"
    profile.voice = "Warm, plain and specific. No hype."
    profile.default_cta = "WhatsApp the sales office for the availability list"
    profile.save()
    for category, claim in seed.FACTS:
        BrandClaim.objects.create(
            workspace=workspace,
            category=category,
            claim=claim,
            source_note="Confirmed by the sales office",
            verified_by=owner,
            verified_at=now,
            valid_until=(now + timedelta(days=90)).date(),
        )

    agency, _created = AgencySettings.objects.get_or_create(workspace=workspace)
    agency.lead = owner
    agency.autopilot_enabled = False
    agency.creation_mode = AgencySettings.CreationMode.CONFIRM
    agency.save()
    agency.accounts.set([account])
    return {"workspace": workspace, "owner": owner, "client": client, "account": account}


def _world_ref(world: dict[str, Any]) -> dict[str, Any]:
    return {
        "workspace_id": str(world["workspace"].pk),
        "workspace_name": world["workspace"].name,
        "owner": _person_ref(world["owner"]),
        "client": _person_ref(world["client"]),
        "account": {"id": str(world["account"].pk), "platform": world["account"].platform},
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@fixture("two_stage_brief")
def two_stage_brief(payload: dict[str, Any]) -> dict[str, Any]:
    """A two-stage workspace and a brief the team starts on (``{}`` → the world and ``brief_id``).

    The brief is queued with the real ``services.create_brief``; once this fixture's transaction
    commits, the in-process worker runs every stage with the faked agents and sends the post for
    approval. Poll ``two_stage_state`` until the brief is ``ready``.
    """
    from apps.studio import services

    world = _two_stage_world()
    brief = services.create_brief(world["workspace"], world["owner"], idea=IDEA, accounts=[world["account"]])
    return {**_world_ref(world), "brief_id": str(brief.pk)}


@fixture("client_stage_post")
def client_stage_post(payload: dict[str, Any]) -> dict[str, Any]:
    """A two-stage workspace and a post its owner approved internally (``{}`` → the world and the post).

    The post is written waiting for review, with a proposed time four days ahead, and approved with
    ``apps.approvals.services.approve_post`` acting as the owner in the dashboard: the gate stamps
    its fingerprint and the post moves on to the client (``pending_client``).
    """
    from django.utils import timezone

    from apps.approvals import services as approval_services
    from apps.approvals.actor import acting_as
    from apps.composer.models import PlatformPost, Post

    world = _two_stage_world()
    workspace, owner = world["workspace"], world["owner"]
    post = Post.objects.create(
        workspace=workspace,
        author=owner,
        title=POST_TITLE,
        caption=POST_CAPTION,
        proposed_publish_at=timezone.now() + timedelta(days=4),
    )
    PlatformPost.objects.create(post=post, social_account=world["account"], status=PlatformPost.Status.PENDING_REVIEW)
    with acting_as(owner):
        approval_services.approve_post(post, owner, workspace, comment="Approved internally; over to the client.")
    rows = list(PlatformPost.objects.filter(post=post).order_by("pk"))
    if not rows or any(row.status != PlatformPost.Status.PENDING_CLIENT for row in rows):
        raise RuntimeError(f"The internal approval did not reach the client stage: {[row.status for row in rows]}.")
    return {
        **_world_ref(world),
        "post_id": str(post.pk),
        "platform_posts": [
            {"id": str(row.pk), "status": row.status, "approved_fingerprint": row.approved_fingerprint} for row in rows
        ],
    }


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------


@probe("two_stage_state")
def two_stage_state(params: dict[str, Any]) -> dict[str, Any]:
    """A brief's or a post's approval state (``?brief_id`` or ``?post_id``).

    ``brief`` is the brief (or ``null`` for a post made in the composer); ``platform_posts`` every
    channel with its approval fields and ``fingerprint``, the gate's fingerprint of what it would
    publish now; ``actions`` every approval action on the post, oldest first; ``publish_logs`` how
    many publish attempts were logged for it.
    """
    from apps.approvals import gate
    from apps.approvals.models import ApprovalAction
    from apps.composer.models import PlatformPost, Post
    from apps.publisher.models import PublishLog
    from apps.studio.models import StudioBrief

    brief = None
    if params.get("brief_id"):
        brief = StudioBrief.objects.filter(pk=_uuid(params, "brief_id")).first()
        if brief is None:
            raise PayloadError(f"No brief {params['brief_id']}.")
        post_id = brief.post_id
    elif params.get("post_id"):
        post_id = _uuid(params, "post_id")
    else:
        raise PayloadError("Send a 'brief_id' or a 'post_id'.")

    result: dict[str, Any] = {
        "brief": None,
        "post": None,
        "platform_posts": [],
        "actions": [],
        "publish_logs": 0,
    }
    if brief is not None:
        result["brief"] = {
            "id": str(brief.pk),
            "status": brief.status,
            "stage": brief.stage,
            "revision": brief.revision,
            "feedback": brief.feedback,
            "post_id": str(brief.post_id) if brief.post_id else None,
        }
    post = Post.objects.filter(pk=post_id).first() if post_id else None
    if post is None:
        if brief is None:
            raise PayloadError(f"No post {params.get('post_id')}.")
        return result
    result["post"] = {
        "id": str(post.pk),
        "proposed_publish_at": _iso(post.proposed_publish_at),
        "scheduled_at": _iso(post.scheduled_at),
    }
    rows = PlatformPost.objects.filter(post=post).select_related("post", "social_account", "approved_by").order_by("pk")
    result["platform_posts"] = [
        {
            "id": str(row.pk),
            "platform": row.social_account.platform,
            "status": row.status,
            "approved_fingerprint": row.approved_fingerprint,
            "fingerprint": gate.fingerprint(row),
            "approved_by": _email(row.approved_by),
            "approved_at": _iso(row.approved_at),
            "approved_publish_at": _iso(row.approved_publish_at),
            "scheduled_at": _iso(row.scheduled_at),
            "published_at": _iso(row.published_at),
        }
        for row in rows
    ]
    result["actions"] = [
        {
            "action": action.action,
            "channel": action.channel,
            "user": _email(action.user),
            "platform_post_id": str(action.platform_post_id) if action.platform_post_id else None,
            "fingerprint": action.fingerprint,
            "comment": action.comment,
        }
        for action in ApprovalAction.objects.filter(post=post).select_related("user").order_by("created_at", "pk")
    ]
    result["publish_logs"] = PublishLog.objects.filter(platform_post__post=post).count()
    return result


@probe("magic_link_state")
def magic_link_state(params: dict[str, Any]) -> dict[str, Any]:
    """Whether a portal link (``?token``, the last part of the fixture's URL) was used, and by whom."""
    from apps.client_portal.models import MagicLinkToken

    token = MagicLinkToken.objects.filter(token=require_str(params, "token")).select_related("user").first()
    if token is None:
        return {"exists": False, "is_consumed": False, "last_used_at": None, "email": None}
    return {
        "exists": True,
        "is_consumed": token.is_consumed,
        "last_used_at": _iso(token.last_used_at),
        "email": token.user.email,
    }
