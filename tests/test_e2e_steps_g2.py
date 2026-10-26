"""The e2e steps for golden paths 2 and 3 (tests/e2e/server/steps/g2.py), under ``config.settings.test``.

The fixtures make fresh rows, so what they make is pinned here: ``team_workspace`` is a workspace of
its own set up like the seeded workspace A (owner, editor and client, Instagram and LinkedIn, the
brand profile, verified facts, the agency settings, a library image), and ``onboarding_workspace`` a
workspace with nothing but its owner. The probes follow a request from the person's message to the
brief it started.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from django.test import Client

WORKSPACE_A = "00000000-0000-4000-8000-00000000000a"
WORKSPACE_B = "00000000-0000-4000-8000-00000000000b"


@pytest.fixture
def e2e_urls(settings):
    settings.ROOT_URLCONF = "tests.e2e.server.urls"
    settings.SETTINGS_MODULE = "config.settings.e2e"
    return settings


@pytest.fixture
def seeded(db):
    from tests.e2e.server import seed

    return seed.run()


def _fixture(client: Client, name: str, payload: dict[str, Any]):
    return client.post(f"/__e2e__/fixture/{name}", data=json.dumps(payload), content_type="application/json")


def _brief(workspace_id: str, email: str, status: str, **fields: Any):
    from apps.accounts.models import User
    from apps.studio.models import StudioBrief

    author = User.objects.get(email=email)
    return StudioBrief.objects.create(
        workspace_id=workspace_id,
        author=author,
        requested_by=author,
        idea=f"An e2e {status} draft",
        status=status,
        **fields,
    )


@pytest.mark.django_db
def test_team_workspace_is_a_fresh_workspace_set_up_like_the_seeded_one(client, e2e_urls, seeded):
    from apps.calendar.models import Queue
    from apps.media_library.models import MediaAsset
    from apps.members.models import OrgMembership, WorkspaceMembership
    from apps.social_accounts.models import SocialAccount
    from apps.studio.models import AgencySettings, BrandClaim, BrandProfile, StudioBrief
    from apps.workspaces.models import Workspace
    from tests.e2e.server import seed

    rows_in_a = {
        "members": WorkspaceMembership.objects.filter(workspace_id=WORKSPACE_A).count(),
        "accounts": SocialAccount.objects.filter(workspace_id=WORKSPACE_A).count(),
        "claims": BrandClaim.objects.filter(workspace_id=WORKSPACE_A).count(),
        "assets": MediaAsset.objects.filter(workspace_id=WORKSPACE_A).count(),
    }

    first = _fixture(client, "team_workspace", {})
    second = _fixture(client, "team_workspace", {}).json()

    assert first.status_code == 200
    team = first.json()
    assert team["workspace_id"] != second["workspace_id"]
    assert {person["email"] for person in team["users"].values()}.isdisjoint(
        person["email"] for person in second["users"].values()
    )
    workspace = Workspace.objects.get(pk=team["workspace_id"])
    assert workspace.name == team["workspace_name"]
    assert workspace.timezone == seed.TIMEZONE
    assert workspace.approval_workflow_mode == Workspace.ApprovalWorkflowMode.REQUIRED_INTERNAL
    assert workspace.require_dashboard_approval is True
    assert workspace.organization_id not in {uuid.UUID(seeded["organisation_a"]), uuid.UUID(seeded["organisation_b"])}

    members = {
        str(user_id): role
        for user_id, role in WorkspaceMembership.objects.filter(workspace=workspace).values_list(
            "user_id", "workspace_role"
        )
    }
    assert members == {team["users"][role]["id"]: role for role in ("owner", "editor", "client")}
    org_roles = dict(
        OrgMembership.objects.filter(organization_id=workspace.organization_id).values_list("user_id", "org_role")
    )
    assert {str(user_id): role for user_id, role in org_roles.items()} == {
        team["users"]["owner"]["id"]: "owner",
        team["users"]["editor"]["id"]: "member",
        team["users"]["client"]["id"]: "member",
    }
    for role in ("owner", "editor", "client"):
        session = _fixture(client, "session", {"email": team["users"][role]["email"]})
        assert session.status_code == 200

    accounts = SocialAccount.objects.filter(workspace=workspace).order_by("platform")
    assert [(account.platform, account.connection_status) for account in accounts] == [
        ("instagram", "connected"),
        ("linkedin_company", "connected"),
    ]
    assert {account.platform: str(account.pk) for account in accounts} == {
        platform: row["id"] for platform, row in team["accounts"].items()
    }
    assert Queue.objects.filter(social_account__in=accounts).count() == 2

    agency = AgencySettings.objects.get(workspace=workspace)
    assert str(agency.lead_id) == team["users"]["owner"]["id"]
    assert agency.autopilot_enabled is False
    assert agency.creation_mode == AgencySettings.CreationMode.CONFIRM
    assert set(agency.accounts.all()) == set(accounts)
    profile = BrandProfile.objects.get(workspace=workspace)
    assert profile.audience and profile.voice and profile.default_cta
    claims = BrandClaim.objects.filter(workspace=workspace)
    assert sorted(claims.values_list("claim", flat=True)) == sorted(claim for _category, claim in seed.FACTS)
    assert all(claim.verified_at is not None for claim in claims)
    assert MediaAsset.objects.filter(workspace=workspace, title=seed.LIBRARY_ASSET_TITLE).count() == 1
    assert not StudioBrief.objects.filter(workspace=workspace).exists()

    # The seeded workspace A is left as it was.
    assert rows_in_a == {
        "members": WorkspaceMembership.objects.filter(workspace_id=WORKSPACE_A).count(),
        "accounts": SocialAccount.objects.filter(workspace_id=WORKSPACE_A).count(),
        "claims": BrandClaim.objects.filter(workspace_id=WORKSPACE_A).count(),
        "assets": MediaAsset.objects.filter(workspace_id=WORKSPACE_A).count(),
    }


@pytest.mark.django_db
def test_team_workspace_takes_no_options(client, e2e_urls, seeded):
    response = _fixture(client, "team_workspace", {"workspace_id": WORKSPACE_A})

    assert response.status_code == 400


@pytest.mark.django_db
def test_onboarding_workspace_has_only_its_owner(client, e2e_urls, seeded):
    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership
    from apps.social_accounts.models import SocialAccount
    from apps.studio.models import AgencySettings

    first = _fixture(client, "onboarding_workspace", {}).json()
    second = _fixture(client, "onboarding_workspace", {}).json()

    assert first["workspace_id"] != second["workspace_id"]
    assert first["owner"]["email"] != second["owner"]["email"]
    owner = User.objects.get(pk=first["owner"]["id"])
    assert owner.tos_accepted_at is not None
    assert str(owner.last_workspace_id) == first["workspace_id"]
    assert list(OrgMembership.objects.filter(user=owner).values_list("organization_id", "org_role")) == [
        (uuid.UUID(first["organisation_id"]), "owner")
    ]
    members = WorkspaceMembership.objects.filter(workspace_id=first["workspace_id"])
    assert list(members.values_list("user_id", "workspace_role")) == [(owner.pk, "owner")]
    assert not SocialAccount.objects.filter(workspace_id=first["workspace_id"]).exists()
    assert not AgencySettings.objects.filter(workspace_id=first["workspace_id"]).exists()

    state = client.get("/__e2e__/probe/onboarding_state", {"workspace_id": first["workspace_id"]}).json()
    assert state == {"brand_name": None, "accounts": [], "lead": None, "briefs": []}


@pytest.mark.django_db
def test_home_request_follows_a_message_to_the_brief_it_started(client, e2e_urls, seeded):
    from apps.accounts.models import User
    from apps.studio import chat
    from apps.studio.models import AgencyJob, Message, StudioBrief
    from apps.workspaces.models import Workspace

    owner = User.objects.get(email="owner@e2e.test")
    body = "Post about the site visit on Instagram, mention free parking"
    params = {"workspace_id": WORKSPACE_A, "body": body}
    empty = client.get("/__e2e__/probe/home_request", params).json()
    assert empty == {"message": None, "ask": None, "reply": None, "confirm": None, "brief": None, "platform_posts": []}

    conversation = chat.general_conversation(Workspace.objects.get(pk=WORKSPACE_A), created_by=owner)
    message = Message.objects.create(conversation=conversation, author=owner, author_kind="staff", body=body)
    ask = AgencyJob.objects.create(
        workspace_id=WORKSPACE_A,
        kind=AgencyJob.Kind.CHAT,
        status=AgencyJob.Status.DONE,
        conversation=conversation,
        requested_by=owner,
        input={"message_id": str(message.pk), "kind": "question"},
        result={
            "awaiting_confirmation": True,
            "creative_brief": {"topic": "The site visit", "key_message": "Free parking", "channels": ["instagram"]},
            "selected_accounts": [{"id": seeded["accounts"]["instagram"]["id"], "platform": "instagram"}],
        },
    )
    reply = Message.objects.create(
        conversation=conversation, author_kind="agent", body="Here's the brief.", action="new_post", job=ask
    )
    confirm = AgencyJob.objects.create(
        workspace_id=WORKSPACE_A,
        kind=AgencyJob.Kind.CHAT,
        status=AgencyJob.Status.DONE,
        conversation=conversation,
        requested_by=owner,
        input={"kind": "confirm_brief", "confirmation_message_id": str(reply.pk), "facts_confirmed": True},
    )
    brief = _brief(WORKSPACE_A, owner.email, StudioBrief.Status.QUEUED, origin=StudioBrief.Origin.CHAT, job=confirm)
    brief.social_accounts.add(seeded["accounts"]["instagram"]["id"])

    state = client.get("/__e2e__/probe/home_request", params).json()

    assert state["message"] == {"id": str(message.pk), "author": owner.email, "author_kind": "staff"}
    assert state["ask"] == {
        "id": str(ask.pk),
        "status": "done",
        "awaiting_confirmation": True,
        "topic": "The site visit",
        "key_message": "Free parking",
        "channels": ["instagram"],
        "accounts": ["instagram"],
    }
    assert state["reply"] == {"id": str(reply.pk), "action": "new_post", "action_status": ""}
    assert state["confirm"] == {
        "id": str(confirm.pk),
        "status": "done",
        "kind": "confirm_brief",
        "facts_confirmed": True,
    }
    assert state["brief"]["id"] == str(brief.pk)
    assert state["brief"] | {"id": ""} == {
        "id": "",
        "status": "queued",
        "stage": brief.stage,
        "origin": "chat",
        "platforms": ["instagram"],
        "requested_by": owner.email,
        "proposed_publish_at": None,
    }
    assert state["platform_posts"] == []
    # Another workspace's thread is not this workspace's request.
    assert client.get("/__e2e__/probe/home_request", {**params, "workspace_id": WORKSPACE_B}).json()["message"] is None
