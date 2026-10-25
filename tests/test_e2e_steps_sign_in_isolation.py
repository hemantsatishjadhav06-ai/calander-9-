"""The e2e steps of golden paths 1 and 11 (``tests/e2e/server/steps/g1.py``), called as a spec calls them.

Under ``config.settings.test``, with the harness URL conf and the e2e settings module name, as in
``tests/test_e2e_server.py``.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import pytest
from django.test import Client
from django.urls import URLPattern, URLResolver, get_resolver, resolve

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


def _fixture(client: Client, name: str, payload: dict[str, Any] | None = None) -> Any:
    return client.post(f"/__e2e__/fixture/{name}", data=json.dumps(payload or {}), content_type="application/json")


def _workspace_patterns(patterns: list[Any], inherited: bool = False) -> int:
    """How many patterns take a ``workspace_id`` (theirs or their include's), from Django's parsed converters."""
    count = 0
    for pattern in patterns:
        takes = inherited or "workspace_id" in pattern.pattern.converters
        if isinstance(pattern, URLResolver):
            count += _workspace_patterns(pattern.url_patterns, takes)
        elif isinstance(pattern, URLPattern) and takes:
            count += 1
    return count


@pytest.mark.django_db
def test_isolation_urls_covers_every_workspace_pattern_with_the_given_rows(client, e2e_urls, seeded):
    rows = _fixture(client, "isolation_b_objects").json()
    objects = {key: rows[key] for key in ("account_id", "post_id", "platform_post_id", "brief_id", "idea_id")}

    response = client.get("/__e2e__/probe/isolation_urls", {"workspace_id": WORKSPACE_B, **objects})

    assert response.status_code == 200, response.content
    urls = response.json()["urls"]
    assert len(urls) == _workspace_patterns(get_resolver().url_patterns) >= 200
    for url in urls:
        match = resolve(url["path"])
        assert match.kwargs["workspace_id"] == UUID(WORKSPACE_B), url
        for part in url["objects"]:
            assert str(match.kwargs[part]) == objects[part], url
    by_name = {url["name"]: url for url in urls}
    assert by_name["studio:detail"]["objects"] == ["brief_id"]
    assert by_name["composer:transition_platform_post"]["objects"] == ["post_id", "platform_post_id"]
    assert by_name["studio:index"]["objects"] == []


@pytest.mark.django_db
def test_isolation_urls_refuses_a_part_no_workspace_url_takes(client, e2e_urls, seeded):
    response = client.get("/__e2e__/probe/isolation_urls", {"workspace_id": WORKSPACE_B, "postid": WORKSPACE_A})

    assert response.status_code == 400
    assert "postid" in response.json()["error"]


@pytest.mark.django_db
def test_isolation_rows_are_made_in_b_with_its_name_and_read_back(client, e2e_urls, seeded):
    from apps.composer.models import PlatformPost

    rows = _fixture(client, "isolation_b_objects").json()
    params = {key: rows[key] for key in ("account_id", "post_id", "platform_post_id", "brief_id", "idea_id")}

    state = client.get("/__e2e__/probe/isolation_b_state", params).json()

    assert rows["workspace_id"] == WORKSPACE_B
    assert rows["workspace_name"] == seeded["workspace_names"]["b"]
    for key in ("account", "post", "brief", "idea"):
        assert state[key]["workspace_id"] == WORKSPACE_B, key
    assert state["platform_post"]["status"] == PlatformPost.Status.PENDING_REVIEW
    assert rows["workspace_name"] in state["post"]["caption"]
    assert rows["workspace_name"] in state["brief"]["idea"]
    assert client.get("/__e2e__/probe/isolation_b_state", params).json() == state

    PlatformPost.objects.filter(pk=rows["platform_post_id"]).update(status=PlatformPost.Status.SCHEDULED)
    assert client.get("/__e2e__/probe/isolation_b_state", params).json() != state


@pytest.mark.django_db
def test_member_of_a_lands_on_a_and_has_no_workspace_of_their_own(client, e2e_urls, seeded):
    from apps.members.models import WorkspaceMembership

    member = _fixture(client, "member_of_a", {"role": "editor"}).json()
    session = _fixture(client, "session", {"email": member["email"]}).json()

    browser = Client()
    browser.cookies[session["cookie"]["name"]] = session["cookie"]["value"]
    assert browser.get("/")["Location"] == f"/workspace/{WORKSPACE_A}/studio/"
    assert list(
        WorkspaceMembership.objects.filter(user_id=member["id"]).values_list("workspace_id", "workspace_role")
    ) == [(UUID(WORKSPACE_A), "editor")]
    assert _fixture(client, "member_of_a", {"role": "admiral"}).status_code == 400


@pytest.mark.django_db
def test_sessions_and_accounts_are_read_back(client, e2e_urls, seeded):
    email = seeded["users"]["editor"]["email"]
    before = client.get("/__e2e__/probe/auth_sessions", {"email": email}).json()
    session = _fixture(client, "session", {"role": "editor"}).json()

    after = client.get("/__e2e__/probe/auth_sessions", {"email": email}).json()
    assert after == {"count": before["count"] + 1, "cookie_name": session["cookie"]["name"]}
    assert client.get("/__e2e__/probe/session_user", {"key": session["cookie"]["value"]}).json() == {
        "exists": True,
        "user": {"id": seeded["users"]["editor"]["id"], "email": email},
    }
    assert client.get("/__e2e__/probe/session_user", {"key": "no-such-session"}).json() == {
        "exists": False,
        "user": None,
    }

    account = client.get("/__e2e__/probe/user_account", {"email": email}).json()
    assert account["users"] == 1 and account["tos_accepted"] is True and account["google_uids"] == []
    assert account["workspaces"] == [{"id": WORKSPACE_A, "name": seeded["workspace_names"]["a"], "role": "editor"}]
    assert client.get("/__e2e__/probe/user_account", {"email": "nobody@e2e.test"}).json() == {"users": 0}


@pytest.mark.django_db
def test_google_profile_registers_what_google_returns_for_a_fresh_code(client, e2e_urls):
    from tests.e2e.server import mocks

    first = _fixture(client, "google_profile", {"email": "gia@e2e.test", "name": "Gia Google"}).json()
    second = _fixture(client, "google_profile", {"email": "gia@e2e.test"}).json()
    try:
        assert first["code"] != second["code"] and first["sub"] != second["sub"]
        assert mocks.GOOGLE_PROFILES[first["code"]] == {
            "sub": first["sub"],
            "email": "gia@e2e.test",
            "email_verified": True,
            "name": "Gia Google",
            "given_name": "Gia",
            "family_name": "Google",
        }
        assert _fixture(client, "google_profile", {}).status_code == 400
    finally:
        mocks.GOOGLE_PROFILES.pop(first["code"], None)
        mocks.GOOGLE_PROFILES.pop(second["code"], None)
