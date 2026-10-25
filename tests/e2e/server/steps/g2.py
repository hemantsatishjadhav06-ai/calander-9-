"""Steps for golden paths 2 and 3: asking the team from Home, and onboarding a fresh workspace.

Fixtures: ``team_workspace`` (a workspace of its own, set up like the seeded workspace A, so what
other tests leave in A never reaches this test's Today card) and ``onboarding_workspace`` (a fresh
organisation and workspace with only its owner: no accounts, no lead, no agency settings).

Probes: ``home_request`` (one request typed in a workspace's team thread, followed through the
account manager's brief, Go ahead, the brief and its platform posts) and ``onboarding_state`` (what
the onboarding steps leave on a workspace: the brand name, its accounts, the lead, its briefs).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from .. import seed
from ..registry import PayloadError, fixture, probe, require_str

ONBOARDING_TIMEZONE = "Asia/Kolkata"


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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@fixture("team_workspace")
def team_workspace(payload: dict[str, Any]) -> dict[str, Any]:
    """A workspace of its own, set up like the seeded workspace A (``{}`` -> its ids and people).

    Its own organisation; an owner (the lead and an approver), an editor and a client, each with a
    fresh address; connected Instagram and LinkedIn company accounts with their queues; the brand
    profile, the verified facts, the agency settings (autopilot off, the brief shown first) and a
    library image, as :func:`seed.run` makes them. Today's card and the scheduler's free slots then
    hold only what this test makes, whatever other tests left in workspace A.
    """
    from django.utils import timezone

    from apps.calendar.services import create_default_queue_and_slots
    from apps.members.models import OrgMembership, WorkspaceMembership
    from apps.organizations.models import Organization
    from apps.social_accounts.models import SocialAccount
    from apps.studio.brand_defaults import ensure_profile
    from apps.studio.models import AgencySettings, BrandClaim
    from apps.workspaces.models import Workspace

    if payload:
        raise PayloadError("team_workspace takes no options: send {}.")
    suffix = uuid.uuid4().hex[:8]
    now = timezone.now()
    org = Organization.objects.create(name=f"Team {suffix}", default_timezone=seed.TIMEZONE)
    workspace = Workspace.objects.create(
        organization=org,
        name=f"Kokapet {suffix}",
        timezone=seed.TIMEZONE,
        approval_workflow_mode=Workspace.ApprovalWorkflowMode.REQUIRED_INTERNAL,
        require_dashboard_approval=True,
    )
    people = {}
    for role, name, org_role in (
        ("owner", "Tara Owner", OrgMembership.OrgRole.OWNER),
        ("editor", "Ezra Editor", OrgMembership.OrgRole.MEMBER),
        ("client", "Chandra Client", OrgMembership.OrgRole.MEMBER),
    ):
        person = seed._person(f"{role}-{suffix}@team.e2e.test", name)
        OrgMembership.objects.create(user=person, organization=org, org_role=org_role)
        WorkspaceMembership.objects.create(user=person, workspace=workspace, workspace_role=role)
        person.last_workspace_id = workspace.pk
        person.save(update_fields=["last_workspace_id"])
        people[role] = person

    accounts = {}
    for platform in ("instagram", "linkedin_company"):
        name, handle, platform_id = seed.ACCOUNTS[platform]
        account = SocialAccount(
            workspace=workspace,
            platform=platform,
            account_platform_id=f"{platform_id}-{suffix}",
            account_name=name,
            account_handle=handle,
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
            oauth_access_token=f"e2e-token-{platform}-{suffix}",
            follower_count=1500,
        )
        # Connected long ago, as in the seed: no first-connect analytics backfill (only the mock would answer).
        account.__dict__["_skip_analytics_backfill"] = True
        account.save()
        create_default_queue_and_slots(account)
        accounts[platform] = account

    owner = people["owner"]
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
    agency.accounts.set(accounts.values())
    seed._library_image(org, workspace, owner)
    return {
        "workspace_id": str(workspace.pk),
        "workspace_name": workspace.name,
        "users": {role: {"id": str(person.pk), "email": person.email} for role, person in people.items()},
        "accounts": {
            platform: {"id": str(account.pk), "platform_id": account.account_platform_id, "name": account.account_name}
            for platform, account in accounts.items()
        },
    }


@fixture("onboarding_workspace")
def onboarding_workspace(payload: dict[str, Any]) -> dict[str, Any]:
    """A fresh organisation and workspace whose only member is its owner (``{}`` → ids and the owner).

    Nothing else: no social accounts, no agency settings (so no lead), no brand profile yet. The owner
    has accepted the terms and lands on this workspace.
    """
    from apps.members.models import OrgMembership, WorkspaceMembership
    from apps.organizations.models import Organization
    from apps.workspaces.models import Workspace

    suffix = uuid.uuid4().hex[:8]
    owner = seed._person(f"owner-{suffix}@onboarding.e2e.test", "Olivia Onboarding")
    org = Organization.objects.create(name=f"Onboarding {suffix}", default_timezone=ONBOARDING_TIMEZONE)
    workspace = Workspace.objects.create(organization=org, name=f"Lakeview {suffix}", timezone=ONBOARDING_TIMEZONE)
    OrgMembership.objects.create(user=owner, organization=org, org_role=OrgMembership.OrgRole.OWNER)
    WorkspaceMembership.objects.create(
        user=owner, workspace=workspace, workspace_role=WorkspaceMembership.WorkspaceRole.OWNER
    )
    owner.last_workspace_id = workspace.pk
    owner.save(update_fields=["last_workspace_id"])
    return {
        "workspace_id": str(workspace.pk),
        "organisation_id": str(org.pk),
        "workspace_name": workspace.name,
        "owner": {"id": str(owner.pk), "email": owner.email},
    }


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------


def _brief_row(brief: Any) -> dict[str, Any]:
    return {
        "id": str(brief.pk),
        "status": brief.status,
        "stage": brief.stage,
        "origin": brief.origin,
        "platforms": sorted(account.platform for account in brief.social_accounts.all()),
        "requested_by": _email(brief.requested_by),
        "proposed_publish_at": _iso(brief.proposed_publish_at),
    }


@probe("home_request")
def home_request(params: dict[str, Any]) -> dict[str, Any]:
    """One request typed in a workspace's team thread (``?workspace_id&body``), followed through.

    ``message`` is the person's message; ``ask`` the account manager's job for it (and the brief it
    proposed); ``reply`` the manager's answer, which carries the brief card; ``confirm`` the job Go
    ahead queued; ``brief`` the post it started; ``platform_posts`` that post's channels. Each is
    ``null`` (or empty) until it exists.
    """
    from apps.composer.models import PlatformPost
    from apps.studio.models import AgencyJob, Message, StudioBrief

    workspace_id = _uuid(params, "workspace_id")
    body = require_str(params, "body")
    result: dict[str, Any] = {
        "message": None,
        "ask": None,
        "reply": None,
        "confirm": None,
        "brief": None,
        "platform_posts": [],
    }
    message = (
        Message.objects.filter(conversation__workspace_id=workspace_id, body=body)
        .exclude(author_kind=Message.AuthorKind.AGENT)
        .select_related("author")
        .order_by("-created_at")
        .first()
    )
    if message is None:
        return result
    result["message"] = {"id": str(message.pk), "author": _email(message.author), "author_kind": message.author_kind}
    ask = (
        AgencyJob.objects.filter(workspace_id=workspace_id, kind=AgencyJob.Kind.CHAT, input__message_id=str(message.pk))
        .order_by("created_at")
        .first()
    )
    if ask is None:
        return result
    asked: dict[str, Any] = ask.result if isinstance(ask.result, dict) else {}
    found_intake = asked.get("creative_brief")
    intake: dict[str, Any] = found_intake if isinstance(found_intake, dict) else {}
    found_accounts = asked.get("selected_accounts")
    accounts: list[Any] = found_accounts if isinstance(found_accounts, list) else []
    result["ask"] = {
        "id": str(ask.pk),
        "status": ask.status,
        "awaiting_confirmation": asked.get("awaiting_confirmation") is True,
        "topic": str(intake.get("topic") or ""),
        "key_message": str(intake.get("key_message") or ""),
        "channels": [str(channel) for channel in intake.get("channels") or []],
        "accounts": sorted(str(row.get("platform")) for row in accounts if isinstance(row, dict)),
    }
    reply = Message.objects.filter(job=ask, author_kind=Message.AuthorKind.AGENT).order_by("created_at").first()
    if reply is None:
        return result
    result["reply"] = {"id": str(reply.pk), "action": reply.action, "action_status": reply.action_status}
    confirm = (
        AgencyJob.objects.filter(
            workspace_id=workspace_id,
            kind=AgencyJob.Kind.CHAT,
            input__kind="confirm_brief",
            input__confirmation_message_id=str(reply.pk),
        )
        .order_by("created_at")
        .first()
    )
    if confirm is None:
        return result
    confirmed = confirm.result if isinstance(confirm.result, dict) else {}
    result["confirm"] = {
        "id": str(confirm.pk),
        "status": confirm.status,
        "kind": str((confirm.input or {}).get("kind") or ""),
        "facts_confirmed": (confirm.input or {}).get("facts_confirmed") is True,
    }
    briefs = StudioBrief.objects.filter(workspace_id=workspace_id).select_related("requested_by")
    brief = None
    if confirmed.get("brief_id"):
        brief = briefs.filter(pk=str(confirmed["brief_id"])).first()
    if brief is None:
        brief = briefs.filter(job=confirm).first()
    if brief is None:
        return result
    result["brief"] = _brief_row(brief)
    if brief.post_id:
        result["platform_posts"] = [
            {"platform": row.social_account.platform, "status": row.status}
            for row in PlatformPost.objects.filter(post_id=brief.post_id).select_related("social_account")
        ]
    return result


@probe("onboarding_state")
def onboarding_state(params: dict[str, Any]) -> dict[str, Any]:
    """What the onboarding steps leave on a workspace (``?workspace_id``)."""
    from apps.social_accounts.models import SocialAccount
    from apps.studio.models import AgencySettings, BrandProfile, StudioBrief
    from apps.workspaces.models import Workspace

    workspace_id = _uuid(params, "workspace_id")
    if not Workspace.objects.filter(pk=workspace_id).exists():
        raise PayloadError(f"No workspace {workspace_id}.")
    profile = BrandProfile.objects.filter(workspace_id=workspace_id).first()
    agency = AgencySettings.objects.filter(workspace_id=workspace_id).select_related("lead").first()
    return {
        "brand_name": profile.brand_name if profile is not None else None,
        "accounts": [
            {
                "platform": account.platform,
                "platform_id": account.account_platform_id,
                "status": account.connection_status,
                "name": account.account_name,
            }
            for account in SocialAccount.objects.filter(workspace_id=workspace_id).order_by("connected_at", "pk")
        ],
        "lead": _email(agency.lead) if agency is not None else None,
        "briefs": [
            _brief_row(brief)
            for brief in StudioBrief.objects.filter(workspace_id=workspace_id)
            .select_related("requested_by")
            .order_by("created_at")
        ],
    }
