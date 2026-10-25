"""Steps for golden paths 2 and 3: asking the team from Home, and onboarding a fresh workspace.

Fixtures: ``discard_open_briefs`` (a workspace's drafts left by earlier tests are discarded, as a
person would discard them, so Today lists this test's own) and ``onboarding_workspace`` (a fresh
organisation and workspace with only its owner: no accounts, no lead, no agency settings).

Probes: ``home_request`` (one request typed in a workspace's team thread, followed through the
account manager's brief, Go ahead, the brief and its platform posts) and ``onboarding_state`` (what
the onboarding steps leave on a workspace: the brand name, its accounts, the lead, its briefs).
"""

from __future__ import annotations

import uuid
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


@fixture("discard_open_briefs")
def discard_open_briefs(payload: dict[str, Any]) -> dict[str, Any]:
    """Discard the workspace's drafts that are planned, in the works or waiting for review.

    Today shows the first three drafts waiting, earliest proposed time first, and the scheduler gives
    each new draft the next free slot; drafts earlier tests left would push this test's own off the
    card. They are discarded the way a person discards them (``services.discard``); a draft that was
    approved or has a delivery to resolve is left as it is (it is not waiting anyway).
    """
    from apps.studio import services
    from apps.studio.models import StudioBrief
    from apps.workspaces.models import Workspace

    workspace_id = _uuid(payload, "workspace_id")
    if not Workspace.objects.filter(pk=workspace_id).exists():
        raise PayloadError(f"No workspace {workspace_id}.")
    open_statuses = (StudioBrief.Status.PLANNED, *StudioBrief.ACTIVE_STATUSES, StudioBrief.Status.READY)
    discarded, kept = 0, 0
    for brief in StudioBrief.objects.filter(workspace_id=workspace_id, status__in=open_statuses):
        try:
            services.discard(brief)
        except services.StudioActionError:
            kept += 1
        else:
            discarded += 1
    return {"discarded": discarded, "kept": kept}


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
