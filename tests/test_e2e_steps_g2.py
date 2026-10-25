"""The e2e steps for golden paths 2 and 3 (tests/e2e/server/steps/g2.py), under ``config.settings.test``.

The fixtures change rows, so what they touch is pinned here: ``discard_open_briefs`` discards only
the named workspace's open drafts, and ``onboarding_workspace`` makes a workspace with nothing but
its owner. The probes follow a request from the person's message to the brief it started.
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
def test_discard_open_briefs_discards_only_that_workspaces_open_drafts(client, e2e_urls, seeded):
    from apps.studio.models import StudioBrief

    status = StudioBrief.Status
    open_a = [_brief(WORKSPACE_A, "owner@e2e.test", value) for value in (status.READY, status.WORKING, status.PLANNED)]
    approved_a = _brief(WORKSPACE_A, "owner@e2e.test", status.APPROVED)
    ready_b = _brief(WORKSPACE_B, "owner-b@e2e.test", status.READY)

    response = _fixture(client, "discard_open_briefs", {"workspace_id": WORKSPACE_A})

    assert response.status_code == 200
    assert response.json() == {"discarded": 3, "kept": 0}
    for brief in open_a:
        brief.refresh_from_db()
        assert brief.status == status.DISCARDED
    approved_a.refresh_from_db()
    ready_b.refresh_from_db()
    assert approved_a.status == status.APPROVED
    assert ready_b.status == status.READY


@pytest.mark.django_db
def test_discard_open_briefs_refuses_a_bad_or_unknown_workspace(client, e2e_urls, seeded):
    assert _fixture(client, "discard_open_briefs", {"workspace_id": "not-a-uuid"}).status_code == 400
    unknown = _fixture(client, "discard_open_briefs", {"workspace_id": "00000000-0000-4000-8000-0000000000ff"})
    assert unknown.status_code == 400


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
