"""Conversational source collection: safe fresh reads, explicit fallbacks and isolation."""

from __future__ import annotations

import json
import socket
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
from django.utils import timezone

from apps.composer.models import PlatformPost, Post
from apps.social_accounts.models import SocialAccount
from apps.studio import creative_sources
from apps.studio.brand_defaults import ensure_profile
from apps.workspaces.models import Workspace

_HTTP_CLIENT = httpx.Client


@pytest.fixture
def offline_http(monkeypatch):
    """All HTTP and DNS are fake, while the real pinning and bounded reader run."""
    state = {
        "requests": [],
        "dns": [],
        "website": httpx.Response(
            200, headers={"Content-Type": "text/html"}, text="<title>Brand</title><p>Current brand information</p>"
        ),
        "meta": httpx.Response(200, json={"data": []}),
    }

    def resolve(host, port, **kwargs):
        state["dns"].append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", port))]

    def respond(request):
        state["requests"].append(request)
        result = state["meta"] if request.headers.get("Host", "").startswith("graph.") else state["website"]
        if isinstance(result, Exception):
            raise result
        # Fresh response instances allow a second collect call to read again.
        return httpx.Response(result.status_code, headers=result.headers, content=result.content)

    monkeypatch.setattr("apps.common.validators.socket.getaddrinfo", resolve)
    monkeypatch.setattr(
        creative_sources,
        "get_client",
        lambda: _HTTP_CLIENT(
            transport=httpx.MockTransport(respond),
            timeout=creative_sources.REQUEST_TIMEOUT,
            follow_redirects=False,
            trust_env=False,
        ),
    )
    return state


@pytest.fixture
def profile(world):
    profile = ensure_profile(world.workspace)
    profile.website = "https://brand.example/"
    profile.save(update_fields=["website"])
    return profile


def _post(world, account, number, *, status="published", workspace=None, caption=None, override=None):
    post = Post.objects.create(
        workspace=workspace or world.workspace,
        author=world.owner,
        caption=caption if caption is not None else f"Public caption {number}",
        internal_notes="PRIVATE-INTERNAL-NOTE",
    )
    return PlatformPost.objects.create(
        post=post,
        social_account=account,
        status=status,
        published_at=timezone.now() - timedelta(minutes=number),
        platform_post_id=f"native-{number}",
        platform_specific_caption=override,
        publish_error="PRIVATE-PROVIDER-ERROR",
    )


def _meta(world, platform="instagram", **fields):
    return SocialAccount.objects.create(
        workspace=world.workspace,
        platform=platform,
        account_name="Brand channel",
        account_platform_id=fields.pop("account_platform_id", "123456"),
        oauth_access_token=fields.pop("oauth_access_token", "PRIVATE-CHANNEL-TOKEN"),
        **fields,
    )


def test_collect_reads_website_fresh_each_time_and_extracts_only_visible_text(world, profile, offline_http):
    offline_http["website"] = httpx.Response(
        200,
        headers={"Content-Type": "text/html; charset=utf-8"},
        text="""<html><head><title> Brand &amp; Homes </title><style>STYLE-SECRET</style></head>
        <body><h1>Premium homes</h1><p>Contact our team.</p><script>SCRIPT-SECRET</script>
        <noscript>NOSCRIPT-SECRET</noscript><template>TEMPLATE-SECRET</template>
        <div hidden>HIDDEN-SECRET</div><span aria-hidden="true">ARIA-SECRET</span>
        <div style="display: none">DISPLAY-SECRET</div></body></html>""",
    )
    first = creative_sources.collect(world.workspace, profile, [world.linkedin])
    second = creative_sources.collect(world.workspace, profile, [world.linkedin])
    assert first["website"]["status"] == "ready"
    assert first["website"]["title"] == "Brand & Homes"
    assert first["website"]["excerpt"] == "Premium homes Contact our team."
    assert second["website"] == first["website"]
    assert len(offline_http["requests"]) == 2
    request = offline_http["requests"][0]
    assert request.url.host == "93.184.216.34"
    assert request.headers["Host"] == "brand.example"
    assert request.extensions["sni_hostname"] == "brand.example"
    assert "Confirm them before generation" in first["notes"][0]
    json.dumps(first)


def test_private_dns_is_rejected_before_http_and_channel_fallback_survives(world, profile, offline_http, monkeypatch):
    _post(world, world.linkedin, 1)
    monkeypatch.setattr(
        "apps.common.validators.socket.getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 443))],
    )
    result = creative_sources.collect(world.workspace, profile, [world.linkedin])
    assert result["website"]["status"] == "unavailable"
    assert not offline_http["requests"]
    assert result["channels"][0]["posts"][0]["caption"] == "Public caption 1"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"Location": "http://127.0.0.1/private"}),
        httpx.Response(500, text="PRIVATE-UPSTREAM-ERROR"),
        httpx.Response(200, headers={"Content-Type": "application/json"}, json={"secret": "PRIVATE-UPSTREAM-ERROR"}),
        httpx.Response(
            200,
            headers={"Content-Type": "text/html", "Content-Length": str(creative_sources.MAX_HTML_BYTES + 1)},
            content=b"x",
        ),
        httpx.Response(
            200, headers={"Content-Type": "text/html"}, content=b"x" * (creative_sources.MAX_HTML_BYTES + 1)
        ),
        httpx.Response(200, headers={"Content-Type": "text/html", "Content-Encoding": "gzip"}),
        httpx.ConnectError("PRIVATE-UPSTREAM-ERROR"),
    ],
)
def test_source_failures_are_bounded_generic_and_do_not_follow_redirects(world, profile, offline_http, response):
    offline_http["website"] = response
    result = creative_sources.collect(world.workspace, profile, [])
    assert result["website"]["status"] == "unavailable"
    assert result["website"]["excerpt"] == ""
    assert "PRIVATE-UPSTREAM-ERROR" not in json.dumps(result)
    assert len(offline_http["requests"]) == 1


def test_total_read_deadline_is_enforced(world, profile, offline_http, monkeypatch):
    clock = iter([0.0, creative_sources.FETCH_DEADLINE + 1])
    monkeypatch.setattr(creative_sources, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    result = creative_sources.collect(world.workspace, profile, [])
    assert result["website"]["status"] == "unavailable"
    assert result["website"]["excerpt"] == ""
    assert len(offline_http["requests"]) == 1


def test_missing_website_and_embedded_credentials_never_make_requests(world, profile, offline_http):
    profile.website = ""
    assert creative_sources.collect(world.workspace, profile, [])["website"]["status"] == "not_configured"
    profile.website = "https://username:PRIVATE-SECRET@brand.example/"
    result = creative_sources.collect(world.workspace, profile, [])
    assert result["website"]["status"] == "unavailable"
    assert "PRIVATE-SECRET" not in json.dumps(result)
    assert not offline_http["requests"]


def test_website_excerpt_is_bounded(world, profile, offline_http):
    offline_http["website"] = httpx.Response(
        200, headers={"Content-Type": "text/html"}, text="<title>" + "T" * 500 + "</title><p>" + "W" * 9000 + "</p>"
    )
    result = creative_sources.collect(world.workspace, profile, [])
    assert len(result["website"]["title"]) == creative_sources.MAX_TITLE_CHARS
    assert len(result["website"]["excerpt"]) == creative_sources.MAX_EXCERPT_CHARS


def test_history_uses_selected_own_accounts_and_five_latest_successful_public_variants(world, profile, offline_http):
    for number in range(1, 8):
        _post(
            world,
            world.linkedin,
            number,
            caption="C" * 2500,
            override=f"Channel caption {number}" if number != 1 else "",
        )
    _post(world, world.linkedin, 0, status="failed", caption="FAILED-SECRET")
    _post(world, world.linkedin, 0, status="draft", caption="DRAFT-SECRET")
    _post(world, world.x, 0, caption="UNSELECTED-SECRET")
    other = Workspace.objects.create(organization=world.org, name="Other tenant")
    foreign = SocialAccount.objects.create(
        workspace=other,
        platform="facebook",
        account_platform_id="987",
        account_name="FOREIGN-SECRET",
        oauth_access_token="FOREIGN-TOKEN",
    )
    _post(world, foreign, 0, workspace=other, caption="FOREIGN-CAPTION")
    # Even malformed historical cross-workspace links cannot supply evidence.
    _post(world, world.linkedin, 0, workspace=other, caption="CROSS-WORKSPACE-SECRET")
    result = creative_sources.collect(world.workspace, profile, [world.linkedin, foreign])
    assert len(result["channels"]) == 1
    channel = result["channels"][0]
    assert channel["source"] == "stored_history" and channel["status"] == "unsupported"
    assert len(channel["posts"]) == 5
    assert channel["posts"][0]["caption"] == ""  # empty override is the actual published wording
    assert channel["posts"][1]["caption"] == "Channel caption 2"
    serialised = json.dumps(result)
    for private in (
        "FAILED-SECRET",
        "DRAFT-SECRET",
        "UNSELECTED-SECRET",
        "FOREIGN-SECRET",
        "FOREIGN-CAPTION",
        "CROSS-WORKSPACE-SECRET",
        "PRIVATE-INTERNAL-NOTE",
        "PRIVATE-PROVIDER-ERROR",
        "li-token",
        "x-token",
    ):
        assert private not in serialised


def test_foreign_profile_website_is_never_fetched(world, profile, offline_http):
    other = Workspace.objects.create(organization=world.org, name="Foreign")
    foreign_profile = ensure_profile(other)
    foreign_profile.website = "https://foreign.example/"
    result = creative_sources.collect(world.workspace, foreign_profile, [])
    assert result["website"]["status"] == "unavailable"
    assert result["website"]["url"] == ""
    assert not offline_http["requests"]


@pytest.mark.parametrize(
    ("platform", "host", "edge", "caption_field", "time_field"),
    [
        ("instagram", "graph.facebook.com", "media", "caption", "timestamp"),
        ("instagram_login", "graph.instagram.com", "media", "caption", "timestamp"),
        ("facebook", "graph.facebook.com", "posts", "message", "created_time"),
    ],
)
def test_live_meta_reads_have_correct_connector_host_bounded_posts_and_header_only_auth(
    world, profile, offline_http, platform, host, edge, caption_field, time_field
):
    account = _meta(world, platform)
    offline_http["meta"] = httpx.Response(
        200,
        json={
            "data": [
                {
                    "id": str(number),
                    caption_field: "Public brand caption" + "C" * 2000,
                    time_field: "2026-10-11T09:00:00+0000",
                }
                for number in range(8)
            ],
            "paging": {"next": "https://evil.example/?access_token=PRIVATE-CHANNEL-TOKEN"},
        },
    )
    result = creative_sources.collect(world.workspace, profile, [account])
    channel = result["channels"][0]
    assert channel["status"] == "ready" and channel["source"] == "live_meta"
    assert channel["fetched_at"] and len(channel["posts"]) == 5
    assert len(channel["posts"][0]["caption"]) == creative_sources.MAX_CAPTION_CHARS
    request = offline_http["requests"][1]
    assert request.headers["Host"] == host
    assert request.extensions["sni_hostname"] == host
    assert request.url.path == f"/v25.0/123456/{edge}"
    assert request.url.params["limit"] == "5"
    assert request.headers["Authorization"] == "Bearer PRIVATE-CHANNEL-TOKEN"
    assert "access_token" not in request.url.params
    assert "PRIVATE-CHANNEL-TOKEN" not in str(request.url)
    assert "PRIVATE-CHANNEL-TOKEN" not in json.dumps(result)
    assert len(offline_http["requests"]) == 2  # website and one native page, never pagination


def test_meta_failure_uses_explicit_stored_fallback_without_leaking_response(world, profile, offline_http):
    account = _meta(world)
    _post(world, account, 1)
    offline_http["meta"] = httpx.Response(403, json={"error": {"message": "PRIVATE-CHANNEL-TOKEN"}})
    result = creative_sources.collect(world.workspace, profile, [account])
    channel = result["channels"][0]
    assert channel["status"] == "unavailable" and channel["source"] == "stored_history"
    assert channel["fetched_at"] == "" and channel["posts"][0]["caption"] == "Public caption 1"
    assert "PRIVATE-CHANNEL-TOKEN" not in json.dumps(result)
    assert any("not a fresh scrape" in note for note in result["notes"])


@pytest.mark.parametrize(
    "fields",
    [
        {"account_platform_id": "123/../me"},
        {"oauth_access_token": ""},
        {"token_expires_at": timezone.now() - timedelta(hours=1)},
        {"connection_status": SocialAccount.ConnectionStatus.DISCONNECTED},
    ],
)
def test_invalid_or_expired_meta_binding_does_not_make_channel_requests(world, profile, offline_http, fields):
    account = _meta(world, **fields)
    result = creative_sources.collect(world.workspace, profile, [account])
    assert result["channels"][0]["status"] == "unavailable"
    assert len(offline_http["requests"]) == 1  # website only
