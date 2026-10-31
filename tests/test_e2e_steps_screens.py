"""The e2e steps for the Phase 2 screens specs (tests/e2e/server/steps/screens.py), under ``config.settings.test``.

``tests/e2e/screens/`` covers the new navigation, Approvals, Settings, Activity, the switches and
the public pages. Their fixtures make fresh rows, so what each makes, and the payloads each refuses,
are pinned here: a person with any workspace role (a viewer is the role the seed has none of), the
switches of a workspace a test made for itself (never the seeded A or B, which every spec shares),
one unread notification for the bell, and the platform operator who receives invite requests, with
the probe that reads what a request left for them.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID

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


def _signed_in(client: Client, email: str) -> Client:
    session = _fixture(client, "session", {"email": email}).json()
    browser = Client()
    browser.cookies[session["cookie"]["name"]] = session["cookie"]["value"]
    return browser


# ---------------------------------------------------------------------------
# workspace_member
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_workspace_member_makes_a_fresh_viewer_of_a_who_lands_there(client, e2e_urls, seeded):
    from apps.members.models import OrgMembership, WorkspaceMembership

    answer = _fixture(client, "workspace_member", {"role": "viewer"})
    assert answer.status_code == 200, answer.content
    member = answer.json()
    assert member["role"] == "viewer" and member["workspace_id"] == WORKSPACE_A
    assert member["email"].endswith("@e2e.test")
    assert list(
        WorkspaceMembership.objects.filter(user_id=member["id"]).values_list("workspace_id", "workspace_role")
    ) == [(UUID(WORKSPACE_A), "viewer")]
    assert list(OrgMembership.objects.filter(user_id=member["id"]).values_list("org_role", flat=True)) == ["member"]

    browser = _signed_in(client, member["email"])
    # Viewers land on the calendar (accounts.views._workspace_landing); staff who create posts on Home.
    assert browser.get("/")["Location"] == f"/workspace/{WORKSPACE_A}/calendar/"
    # A second call is a second person: each test has its own.
    assert _fixture(client, "workspace_member", {"role": "viewer"}).json()["email"] != member["email"]


@pytest.mark.django_db
def test_workspace_member_joins_a_workspace_a_test_made(client, e2e_urls, seeded):
    from apps.members.models import WorkspaceMembership

    made = _fixture(client, "team_workspace", {}).json()
    member = _fixture(client, "workspace_member", {"role": "contributor", "workspace_id": made["workspace_id"]}).json()
    assert member["workspace_id"] == made["workspace_id"]
    assert list(
        WorkspaceMembership.objects.filter(user_id=member["id"]).values_list("workspace_id", "workspace_role")
    ) == [(UUID(made["workspace_id"]), "contributor")]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"role": "admiral"},
        {"role": "viewer", "workspace_id": "not-a-uuid"},
        {"role": "viewer", "workspace_id": str(uuid.uuid4())},
    ],
)
def test_workspace_member_refuses_a_bad_payload(client, e2e_urls, seeded, payload):
    assert _fixture(client, "workspace_member", payload).status_code == 400


# ---------------------------------------------------------------------------
# workspace_switches
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_workspace_switches_sets_the_switches_of_a_workspace_a_test_made(client, e2e_urls, seeded):
    from apps.common.features import features_for
    from apps.workspaces.models import Workspace

    made = _fixture(client, "team_workspace", {}).json()
    workspace = Workspace.objects.get(pk=made["workspace_id"])
    assert features_for(workspace) == {
        "blog": False,
        "queues": False,
        "templates": False,
        "extra_providers": False,
        "advanced_settings": False,
    }

    answer = _fixture(client, "workspace_switches", {"workspace_id": made["workspace_id"], "features": {"blog": True}})
    assert answer.status_code == 200, answer.content
    assert answer.json()["features"] == {**features_for(workspace), "blog": True}
    assert features_for(workspace)["blog"] is True

    # One switch at a time: the others keep what they had.
    _fixture(
        client, "workspace_switches", {"workspace_id": made["workspace_id"], "features": {"extra_providers": True}}
    )
    _fixture(client, "workspace_switches", {"workspace_id": made["workspace_id"], "features": {"blog": False}})
    assert features_for(workspace) == {
        "blog": False,
        "queues": False,
        "templates": False,
        "extra_providers": True,
        "advanced_settings": False,
    }


@pytest.mark.django_db
@pytest.mark.parametrize("seeded_workspace", [WORKSPACE_A, WORKSPACE_B])
def test_workspace_switches_never_touches_the_seeded_workspaces(client, e2e_urls, seeded, seeded_workspace):
    from apps.common.features import features_for
    from apps.workspaces.models import Workspace

    workspace = Workspace.objects.get(pk=seeded_workspace)
    before = features_for(workspace)
    answer = _fixture(client, "workspace_switches", {"workspace_id": seeded_workspace, "features": {"blog": True}})
    assert answer.status_code == 400
    assert features_for(workspace) == before


@pytest.mark.django_db
@pytest.mark.parametrize(
    "features",
    [None, {}, {"rockets": True}, {"blog": "yes"}, {"blog": 1}, ["blog"]],
)
def test_workspace_switches_refuses_a_bad_payload(client, e2e_urls, seeded, features):
    made = _fixture(client, "team_workspace", {}).json()
    payload: dict[str, Any] = {"workspace_id": made["workspace_id"]}
    if features is not None:
        payload["features"] = features
    assert _fixture(client, "workspace_switches", payload).status_code == 400


@pytest.mark.django_db
def test_workspace_switches_refuses_an_unknown_workspace(client, e2e_urls, seeded):
    unknown = {"workspace_id": str(uuid.uuid4()), "features": {"blog": True}}
    assert _fixture(client, "workspace_switches", unknown).status_code == 400


# ---------------------------------------------------------------------------
# unread_notification
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_unread_notification_gives_a_person_one_more_unread_notification(client, e2e_urls, seeded):
    from apps.notifications.models import Notification

    member = _fixture(client, "workspace_member", {"role": "editor"}).json()
    answer = _fixture(client, "unread_notification", {"email": member["email"], "title": "E2E: the bell"})
    assert answer.status_code == 200, answer.content
    made = Notification.objects.get(pk=answer.json()["id"])
    assert made.user_id == UUID(member["id"])
    assert (made.title, made.is_read, made.shown_in_app) == ("E2E: the bell", False, True)
    assert answer.json()["unread"] == 1

    browser = _signed_in(client, member["email"])
    page = browser.get(f"/workspace/{WORKSPACE_A}/calendar/")
    assert page.context["unread_notification_count"] == 1


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [{}, {"email": "nobody@e2e.test"}, {"email": "owner@e2e.test", "title": 5}])
def test_unread_notification_refuses_a_bad_payload(client, e2e_urls, seeded, payload):
    assert _fixture(client, "unread_notification", payload).status_code == 400


# ---------------------------------------------------------------------------
# invite_operator and invite_requests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_invite_operator_is_one_active_staff_member(client, e2e_urls, seeded):
    from apps.accounts.models import User

    first = _fixture(client, "invite_operator", {})
    assert first.status_code == 200, first.content
    again = _fixture(client, "invite_operator", {}).json()
    assert again == first.json()
    operator = User.objects.get(email=first.json()["email"])
    assert operator.is_staff and operator.is_active and not operator.is_superuser
    assert User.objects.filter(email=operator.email).count() == 1
    assert _fixture(client, "invite_operator", {"role": "owner"}).status_code == 400


@pytest.mark.django_db
def test_invite_requests_reads_what_one_request_left_for_the_operators(client, e2e_urls, seeded):
    operator = _fixture(client, "invite_operator", {}).json()
    email = f"ravi-{uuid.uuid4().hex[:8]}@agency.example"
    assert client.get("/__e2e__/probe/invite_requests", {"email": email}).json() == {
        "operators": [operator["email"]],
        "notifications": [],
    }

    sent = Client().post(
        "/request-invite/",
        {"name": "Ravi Kumar", "agency": "Kokapet Social", "email": email, "note": "", "website": ""},
    )
    assert sent.status_code == 302

    read = client.get("/__e2e__/probe/invite_requests", {"email": email}).json()
    assert read["operators"] == [operator["email"]]
    assert read["notifications"] == [
        {"operator": operator["email"], "title": "Invite request from Ravi Kumar (Kokapet Social)", "is_read": False}
    ]
    # Another person's request is not this one.
    other = client.get("/__e2e__/probe/invite_requests", {"email": "someone-else@agency.example"}).json()
    assert other["notifications"] == []
    assert client.get("/__e2e__/probe/invite_requests", {}).status_code == 400
