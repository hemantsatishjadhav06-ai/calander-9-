"""The e2e steps for golden paths 9 and 10 (tests/e2e/server/steps/g5.py), under ``config.settings.test``.

Path 9's probes read the inbox message a Facebook comment became in workspace A, and the Facebook
calls the mock answered for that one comment, so a test sees its own reply and never another test's.
Path 10's fixture makes a blank-timezone workspace in its own organisation with a post the owner
approved in the dashboard and that is scheduled; what it makes, and the payloads it refuses, are
pinned here, so a change in the approval services that stops it scheduling fails in pytest, not as a
500 inside a browser run.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from django.test import Client
from django.utils import timezone

WORKSPACE_A = "00000000-0000-4000-8000-00000000000a"


@pytest.fixture
def e2e_urls(settings):
    settings.ROOT_URLCONF = "tests.e2e.server.urls"
    settings.SETTINGS_MODULE = "config.settings.e2e"
    return settings


@pytest.fixture
def seeded(db):
    from tests.e2e.server import seed

    return seed.run()


@pytest.fixture
def mock_calls():
    """The mock transport's record of answered calls, empty before and after the test."""
    from tests.e2e.server import mocks

    mocks.reset()
    yield mocks
    mocks.reset()


def _fixture(client: Client, name: str, payload: dict[str, Any]):
    return client.post(f"/__e2e__/fixture/{name}", data=json.dumps(payload), content_type="application/json")


def _probe(client: Client, name: str, params: dict[str, Any]):
    return client.get(f"/__e2e__/probe/{name}", params)


# ---------------------------------------------------------------------------
# Path 9: the Inbox
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_inbox_message_reads_the_message_its_replies_and_who_was_told(client, e2e_urls, seeded):
    from apps.accounts.models import User
    from apps.inbox.models import InboxMessage, InboxReply
    from apps.notifications.models import EventType, Notification
    from apps.social_accounts.models import SocialAccount

    facebook = SocialAccount.objects.get(pk=seeded["accounts"]["facebook"]["id"])
    manager = User.objects.get(email=seeded["users"]["manager"]["email"])
    editor = User.objects.get(email=seeded["users"]["editor"]["email"])
    message = InboxMessage.objects.create(
        workspace_id=WORKSPACE_A,
        social_account=facebook,
        platform_message_id="e2e-steps-comment",
        message_type=InboxMessage.MessageType.COMMENT,
        sender_name="Ravi Kumar",
        body="Is parking free on Saturday?",
        status=InboxMessage.Status.OPEN,
        assigned_to=manager,
        received_at=timezone.now(),
    )
    sent_at = timezone.now()
    reply = InboxReply.objects.create(
        inbox_message=message,
        author=editor,
        body="Yes, it is.",
        status=InboxReply.Status.SENT,
        platform_reply_id="e2e-reply-e2e-steps-comment",
        sent_at=sent_at,
    )
    for _ in range(2):
        Notification.objects.create(
            user=manager,
            event_type=EventType.NEW_INBOX_MESSAGE,
            title="New comment",
            data={"message_id": str(message.pk)},
        )
    # Another message's notification is not counted for this one.
    Notification.objects.create(
        user=editor, event_type=EventType.NEW_INBOX_MESSAGE, title="New comment", data={"message_id": str(uuid.uuid4())}
    )

    response = _probe(client, "inbox_message", {"comment_id": "e2e-steps-comment"})

    assert response.status_code == 200
    assert response.json() == {
        "message": {
            "id": str(message.pk),
            "workspace_id": WORKSPACE_A,
            "account_id": str(facebook.pk),
            "message_type": "comment",
            "status": "open",
            "body": "Is parking free on Saturday?",
            "sender_name": "Ravi Kumar",
            "assigned_to": manager.email,
        },
        "replies": [
            {
                "id": str(reply.pk),
                "status": "sent",
                "body": "Yes, it is.",
                "author": editor.email,
                "platform_reply_id": "e2e-reply-e2e-steps-comment",
                "sent_at": sent_at.astimezone(ZoneInfo("UTC")).isoformat(),
            }
        ],
        "notifications": {manager.email: 2},
    }


@pytest.mark.django_db
def test_inbox_message_for_an_unknown_comment_is_none(client, e2e_urls, seeded):
    response = _probe(client, "inbox_message", {"comment_id": "e2e-no-such-comment"})

    assert response.status_code == 200
    assert response.json() == {"message": None, "replies": [], "notifications": {}}
    assert _probe(client, "inbox_message", {}).status_code == 400


def _answer(mocks: Any, method: str, url: str) -> None:
    """Send one request through the mock transport, as a provider client would."""
    response = mocks.handler(httpx.Request(method, url))
    assert response.status_code == 200


@pytest.mark.django_db
def test_inbox_platform_calls_lists_only_this_comments_facebook_calls(client, e2e_urls, mock_calls):
    from providers import facebook
    from providers import x as x_provider

    since = time.time() - 1
    _answer(mock_calls, "POST", f"{facebook.BASE_URL}/e2e-owner-1/comments")
    _answer(mock_calls, "POST", f"{facebook.BASE_URL}/e2e-editor-2/comments")
    _answer(mock_calls, "POST", f"{facebook.BASE_URL}/e2e-owner-1/comments")
    # The same comment id on another host, and another provider's call, are not Facebook calls.
    mock_calls._note(mock_calls._answered, "POST", "https", "api.x.com", "/e2e-owner-1/comments")
    _answer(mock_calls, "POST", x_provider.TOKEN_URL)

    owner = _probe(client, "inbox_platform_calls", {"since": since, "comment_id": "e2e-owner-1"})
    editor = _probe(client, "inbox_platform_calls", {"since": since, "comment_id": "e2e-editor-2"})
    other = _probe(client, "inbox_platform_calls", {"since": since, "comment_id": "e2e-owner"})
    later = _probe(client, "inbox_platform_calls", {"since": time.time() + 60, "comment_id": "e2e-owner-1"})

    host = facebook.BASE_URL.split("/")[2]
    assert owner.status_code == 200
    assert owner.json()["calls"] == [
        {"method": "POST", "host": host, "url": f"{facebook.BASE_URL}/e2e-owner-1/comments"},
        {"method": "POST", "host": host, "url": f"{facebook.BASE_URL}/e2e-owner-1/comments"},
    ]
    assert editor.json()["calls"] == [
        {"method": "POST", "host": host, "url": f"{facebook.BASE_URL}/e2e-editor-2/comments"}
    ]
    assert other.json()["calls"] == []
    assert later.json()["calls"] == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    "params",
    [
        {},
        {"comment_id": ""},
        {"comment_id": "a/b"},
        {"comment_id": "page:comment"},
        {"comment_id": "c" * 40},
        {"comment_id": "e2e-owner-1", "since": "soon"},
    ],
)
def test_inbox_platform_calls_refuses_a_comment_id_it_could_not_match(client, e2e_urls, mock_calls, params):
    # A comment id the mock would redact (a colon, or 40 characters and more) or that is not one path
    # segment could never match a recorded call, so an empty answer would prove nothing.
    response = _probe(client, "inbox_platform_calls", params)

    assert response.status_code == 400
    assert response.json()["error"]


# ---------------------------------------------------------------------------
# Path 10: the brand colour and the timezone
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_brand_timezone_workspace_schedules_an_approved_post_in_its_own_organisation(client, e2e_urls, seeded):
    from apps.approvals import gate
    from apps.approvals.models import ApprovalAction
    from apps.composer.models import PlatformPost
    from apps.members.models import OrgMembership, WorkspaceMembership
    from apps.studio.models import BrandProfile
    from apps.workspaces.models import Workspace

    payload = {"timezone": "Asia/Dubai", "then_timezone": "Asia/Tokyo", "days_ahead": 3, "hour": 10}
    first = _fixture(client, "brand_timezone_workspace", payload)
    second = _fixture(client, "brand_timezone_workspace", payload).json()

    assert first.status_code == 200
    made = first.json()
    assert made["workspace_id"] != second["workspace_id"]
    assert made["organisation_id"] != second["organisation_id"]
    assert {made["owner"]["email"], made["editor"]["email"]}.isdisjoint(
        {second["owner"]["email"], second["editor"]["email"]}
    )

    workspace = Workspace.objects.select_related("organization").get(pk=made["workspace_id"])
    assert str(workspace.organization_id) == made["organisation_id"]
    assert str(workspace.organization_id) not in {seeded["organisation_a"], seeded["organisation_b"]}
    assert workspace.timezone == ""
    assert workspace.organization.default_timezone == "Asia/Dubai"
    assert workspace.effective_timezone == "Asia/Dubai"
    members = dict(WorkspaceMembership.objects.filter(workspace=workspace).values_list("user_id", "workspace_role"))
    assert {str(user_id): role for user_id, role in members.items()} == {
        made["owner"]["id"]: "owner",
        made["editor"]["id"]: "editor",
    }
    org_roles = dict(
        OrgMembership.objects.filter(organization=workspace.organization).values_list("user_id", "org_role")
    )
    assert {str(user_id): role for user_id, role in org_roles.items()} == {
        made["owner"]["id"]: "owner",
        made["editor"]["id"]: "member",
    }
    assert BrandProfile.objects.filter(workspace=workspace).count() == 1

    # One platform post, scheduled at the approved instant, with the gate's fingerprint of it now.
    platform_post = PlatformPost.objects.select_related("post__workspace", "social_account").get(
        post__workspace=workspace
    )
    assert str(platform_post.pk) == made["platform_post_id"]
    assert str(platform_post.post_id) == made["post_id"]
    assert platform_post.status == PlatformPost.Status.SCHEDULED
    assert platform_post.scheduled_at == platform_post.approved_publish_at
    assert platform_post.approved_fingerprint == gate.fingerprint(platform_post)
    assert datetime.fromisoformat(made["scheduled_at"]) == platform_post.scheduled_at
    approved = ApprovalAction.objects.filter(post_id=made["post_id"], action=ApprovalAction.ActionType.APPROVED)
    assert [(str(action.user_id), action.channel) for action in approved] == [(made["owner"]["id"], "dashboard")]

    # 10:00 in Dubai, three days ahead; the same instant is 15:00 that day in Tokyo.
    local = platform_post.scheduled_at.astimezone(ZoneInfo("Asia/Dubai"))
    assert (local.hour, local.minute) == (10, 0)
    assert local.date() == (timezone.now().astimezone(ZoneInfo("Asia/Dubai")) + timedelta(days=3)).date()
    assert made["local_before"] == {"date": local.strftime("%Y-%m-%d"), "time": "10:00"}
    assert made["local_after"] == {"date": local.strftime("%Y-%m-%d"), "time": "15:00"}

    state = _probe(client, "brand_timezone_state", {"workspace_id": made["workspace_id"]})
    assert state.status_code == 200
    body = state.json()
    assert body["workspace"] == {"timezone": "", "effective_timezone": "Asia/Dubai"}
    assert body["organisation"] == {"default_timezone": "Asia/Dubai"}
    assert [(row["id"], row["status"]) for row in body["platform_posts"]] == [(made["platform_post_id"], "scheduled")]
    assert body["platform_posts"][0]["approved_fingerprint"] == body["platform_posts"][0]["fingerprint"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        {"timezone": "Mars/Olympus_Mons"},
        {"then_timezone": "Nowhere"},
        {"timezone": 4},
        {"hour": 24},
        {"hour": -1},
        {"hour": 9.5},
        {"days_ahead": 0},
        {"days_ahead": 61},
        {"days_ahead": "soon"},
    ],
)
def test_brand_timezone_workspace_refuses_a_bad_payload(client, e2e_urls, payload):
    from apps.organizations.models import Organization

    organisations = Organization.objects.count()

    response = _fixture(client, "brand_timezone_workspace", payload)

    assert response.status_code == 400
    assert response.json()["error"]
    assert Organization.objects.count() == organisations


@pytest.mark.django_db
def test_brand_timezone_state_refuses_a_bad_or_unknown_workspace(client, e2e_urls):
    assert _probe(client, "brand_timezone_state", {}).status_code == 400
    assert _probe(client, "brand_timezone_state", {"workspace_id": "not-a-uuid"}).status_code == 400
    assert _probe(client, "brand_timezone_state", {"workspace_id": str(uuid.uuid4())}).status_code == 400
