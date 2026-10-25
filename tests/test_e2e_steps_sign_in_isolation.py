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


def _other_patterns(patterns: list[Any], inherited: frozenset[str] = frozenset()) -> int:
    """How many patterns take a part but no ``workspace_id``, from the named groups Django compiled."""
    count = 0
    for pattern in patterns:
        names = inherited | frozenset(pattern.pattern.regex.groupindex)
        if isinstance(pattern, URLResolver):
            count += _other_patterns(pattern.url_patterns, names)
        elif isinstance(pattern, URLPattern) and names and "workspace_id" not in names:
            count += 1
    return count


def _b_rows(client: Client) -> dict[str, Any]:
    rows = _fixture(client, "isolation_b_objects").json()
    from tests.e2e.server.steps import g1

    assert set(rows["objects"]) == set(g1._B_ROWS)
    return rows


@pytest.mark.django_db
def test_isolation_urls_covers_every_workspace_pattern_with_the_given_rows(client, e2e_urls, seeded):
    objects = _b_rows(client)["objects"]

    response = client.get("/__e2e__/probe/isolation_urls", {"workspace_id": WORKSPACE_B, **objects})

    assert response.status_code == 200, response.content
    urls = response.json()["urls"]
    assert len(urls) == response.json()["count"] == _workspace_patterns(get_resolver().url_patterns) >= 200
    ids = set(objects.values())
    for url in urls:
        match = resolve(url["path"])
        assert match.kwargs["workspace_id"] == UUID(WORKSPACE_B), url
        assert match.view_name == url["resolves_to"], url
        for part in url["objects"]:
            assert str(match.kwargs[part]) in ids, url
        assert not set(url["objects"]) & set(url["samples"]), url
    by_name = {url["name"]: url for url in urls}
    detail = by_name["studio:detail"]
    assert detail["objects"] == ["brief_id"] and objects["brief_id"] in detail["path"]
    transition = by_name["composer:transition_platform_post"]
    assert transition["objects"] == ["post_id", "platform_post_id"]
    assert transition["path"].count(objects["post_id"]) == 1 and objects["platform_post_id"] in transition["path"]
    assert by_name["studio:index"]["objects"] == [] and by_name["studio:index"]["samples"] == []
    # The most specific key wins: an article under blog:, a saved reply under its own URL name.
    article = by_name["blog:detail"]["path"]
    assert objects["blog:post_id"] in article and objects["post_id"] not in article
    saved = by_name["inbox:saved_reply_edit"]["path"]
    assert objects["inbox:saved_reply_edit:reply_id"] in saved and objects["reply_id"] not in saved
    assert objects["reply_id"] in by_name["inbox:send_reply_draft"]["path"]
    # The parts no row of B fills are the three the spec reviewed (tests/e2e/golden/11-isolation.spec.ts).
    sampled = sorted(f"{url['name']}:{part}" for url in urls for part in url["samples"])
    assert sampled == [
        "studio:brand_sample:template",
        "telegram:deactivate_chat:chat_id",
        "telegram:disconnect_channel:channel_id",
    ]
    # Methods, read through the decorators: require_POST, require_GET, and a view that takes any.
    assert transition["methods"] == ["POST"]
    assert by_name["studio:index"]["methods"] == ["GET"]
    assert by_name["social_accounts:connect_bluesky"]["methods"] is None


@pytest.mark.django_db
def test_isolation_urls_refuses_a_part_no_url_takes(client, e2e_urls, seeded):
    for probe in ("isolation_urls", "isolation_other_urls"):
        params = {"postid": WORKSPACE_A, **({"workspace_id": WORKSPACE_B} if probe == "isolation_urls" else {})}
        response = client.get(f"/__e2e__/probe/{probe}", params)

        assert response.status_code == 400, probe
        assert "postid" in response.json()["error"], probe


@pytest.mark.django_db
def test_isolation_other_urls_fill_the_portal_and_organisation_urls_with_bs_rows(client, e2e_urls, seeded):
    objects = _b_rows(client)["objects"]

    response = client.get("/__e2e__/probe/isolation_other_urls", objects)

    assert response.status_code == 200, response.content
    urls = response.json()["urls"]
    assert len(urls) == response.json()["count"] == _other_patterns(get_resolver().url_patterns)
    assert not any("workspace_id" in url["route"] for url in urls)
    by_name = {url["name"]: url for url in urls if url["name"]}
    expected = {
        "client_portal:approve": f"/portal/approvals/{objects['client_portal:post_id']}/approve/",
        "client_portal:request_changes": f"/portal/approvals/{objects['client_portal:post_id']}/request-changes/",
        "client_portal:reject": f"/portal/approvals/{objects['client_portal:post_id']}/reject/",
        "client_portal:request_hold": f"/portal/approvals/{objects['client_portal:request_hold:post_id']}/hold/",
        "client_portal:post_ask": f"/portal/approvals/{objects['client_portal:post_id']}/ask/",
        "client_portal:post_thread": f"/portal/approvals/{objects['client_portal:post_id']}/thread/",
        "client_portal:team_messages": f"/portal/team/{objects['client_portal:conversation_id']}/messages/",
        "members:update_role": f"/members/{objects['members:membership_id']}/role/",
        "members:remove": f"/members/{objects['members:membership_id']}/remove/",
        "members:manage_workspaces": f"/members/{objects['members:membership_id']}/workspaces/",
        "members:resend_invite": f"/members/invite/{objects['invitation_id']}/resend/",
        "api_keys:revoke": f"/organizations/api-keys/{objects['key_id']}/revoke/",
        "notifications:mark_as_read": f"/notifications/{objects['notification_id']}/read/",
        "media_library_org:shared_asset_detail": f"/organizations/media/shared/{objects['media_library_org:asset_id']}/",
    }
    assert {name: by_name[name]["path"] for name in expected} == expected
    for name in expected:
        assert by_name[name]["samples"] == [] and len(by_name[name]["objects"]) == 1, name
        assert resolve(by_name[name]["path"]).view_name == name
    assert by_name["client_portal:approve"]["methods"] == ["POST"]
    assert by_name["client_portal:team_messages"]["methods"] == ["GET"]
    assert by_name["members:manage_workspaces"]["methods"] is None
    assert by_name["media_library_org:shared_asset_edit"]["methods"] == ["GET", "POST"]
    # A token or a name in the path is not a row: it stays a sample, for the spec to review.
    assert by_name["client_portal:magic_link_entry"]["samples"] == ["token"]
    assert by_name["members:accept_invite"]["samples"] == ["token"]
    # A regular-expression route (the public media) is listed with its parts and no path.
    media = [url for url in urls if url["route"].startswith("^media/")]
    assert media and all(url["path"] is None and url["samples"] == ["path"] for url in media)


@pytest.mark.django_db
def test_isolation_rows_are_made_in_b_and_read_back_as_fingerprints(client, e2e_urls, seeded):
    from django.apps import apps

    from apps.approvals.models import PostComment
    from apps.composer.models import PlatformPost
    from apps.studio.models import Conversation
    from tests.e2e.server.steps import g1

    rows = _b_rows(client)
    objects = rows["objects"]
    assert rows["workspace_id"] == WORKSPACE_B
    assert rows["workspace_name"] == seeded["workspace_names"]["b"]
    for key, (label, path) in g1._B_ROWS.items():
        assert apps.get_model(label)._base_manager.filter(pk=objects[key], **{path: WORKSPACE_B}).exists(), key
    # The portal's rows are in the states the portal acts on, so a lookup that lost its scope would act.
    portal_post = PlatformPost.objects.get(post_id=objects["client_portal:post_id"])
    assert portal_post.status == PlatformPost.Status.PENDING_CLIENT
    held = PlatformPost.objects.get(post_id=objects["client_portal:request_hold:post_id"])
    assert held.status == PlatformPost.Status.APPROVED and held.scheduled_at is None
    thread = Conversation.objects.get(pk=objects["client_portal:conversation_id"])
    assert thread.audience == Conversation.Audience.CLIENT and str(thread.post_id) == objects["client_portal:post_id"]
    shared = apps.get_model("media_library.MediaAsset").objects.get(pk=objects["media_library_org:asset_id"])
    assert shared.workspace_id is None

    response = client.get("/__e2e__/probe/isolation_b_state", objects)
    assert response.status_code == 200, response.content
    state = response.json()
    assert b"e2e-token-bayside" not in response.content
    assert set(state["rows"]) == set(g1._B_ROWS)
    for key, row in state["rows"].items():
        model = apps.get_model(g1._B_ROWS[key][0])
        assert row is not None, key
        assert set(row) == {field.attname for field in model._meta.concrete_fields}, key
        assert all(isinstance(digest, str) and len(digest) == 16 for digest in row.values()), key
    assert set(state["counts"]) == set(state["digests"]) == {label for label, _path in g1._b_kinds().items()}
    # Every kind a URL names has its row; the kinds a request would add may have none yet.
    assert all(state["counts"][label] > 0 for label, _path in g1._B_ROWS.values()), state["counts"]
    assert client.get("/__e2e__/probe/isolation_b_state", objects).json() == state

    PlatformPost.objects.filter(pk=objects["platform_post_id"]).update(status=PlatformPost.Status.SCHEDULED)
    changed = client.get("/__e2e__/probe/isolation_b_state", objects).json()
    assert changed["rows"]["platform_post_id"]["status"] != state["rows"]["platform_post_id"]["status"]
    assert changed["rows"]["post_id"] == state["rows"]["post_id"]
    assert changed["digests"]["composer.PlatformPost"] != state["digests"]["composer.PlatformPost"]
    assert changed["counts"] == state["counts"]

    # A status change on a row no URL names (the held post's platform post) still shows.
    PlatformPost.objects.filter(pk=held.pk).update(status=PlatformPost.Status.ON_HOLD)
    held_changed = client.get("/__e2e__/probe/isolation_b_state", objects).json()
    assert held_changed["digests"]["composer.PlatformPost"] != changed["digests"]["composer.PlatformPost"]

    author = apps.get_model("accounts.User").objects.get(email=seeded["users"]["owner_b"]["email"])
    PostComment.objects.create(post_id=objects["post_id"], author=author, body="One more")
    added = client.get("/__e2e__/probe/isolation_b_state", objects).json()
    assert added["counts"]["approvals.PostComment"] == state["counts"]["approvals.PostComment"] + 1
    assert added["digests"]["approvals.PostComment"] != state["digests"]["approvals.PostComment"]

    missing = dict(objects)
    missing.pop("routine_id")
    assert client.get("/__e2e__/probe/isolation_b_state", missing).status_code == 400
    assert client.get("/__e2e__/probe/isolation_b_state", {**objects, "nope": WORKSPACE_A}).status_code == 400


@pytest.mark.django_db
def test_reset_rate_limits_clears_a_views_counter(client, e2e_urls, seeded):
    from apps.accounts.models import User

    assert e2e_urls.RATELIMIT_ENABLE, "the limits are on under the test settings, as under config.settings.e2e"
    browser = Client()
    browser.force_login(User.objects.get(email=seeded["users"]["owner"]["email"]))
    # members:resend_invite allows 10 a minute; a row the owner's organisation does not have is a 404.
    path = f"/members/invite/{WORKSPACE_B}/resend/"
    assert [browser.post(path).status_code for _ in range(10)] == [404] * 10
    assert browser.post(path).status_code == 403

    cleared = _fixture(client, "reset_rate_limits").json()["cleared"]

    assert cleared >= 1
    assert browser.post(path).status_code == 404
    assert _fixture(client, "reset_rate_limits").json() == {"cleared": 1}


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
