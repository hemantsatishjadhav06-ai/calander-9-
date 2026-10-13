"""Fresh, bounded source evidence for a conversational creative brief.

``collect`` reads the saved brand website and connected Meta channels on every
call, with stored successful publication history as an explicit fallback. It
never returns credentials, private inbox messages or internal post notes. Website
text and published captions remain untrusted evidence: callers must show the
source summary to the person and obtain confirmation before making a brief;
this module does not promote scraped claims into the brand's approved facts.
"""

from __future__ import annotations

import time
from contextlib import closing
from datetime import datetime, timedelta
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
from django.utils import timezone

from apps.common.net import UnsafeUrlError, build_pinned_request

MAX_HTML_BYTES = 256 * 1024
MAX_EXCERPT_CHARS = 4000
MAX_TITLE_CHARS = 200
MAX_CAPTION_CHARS = 1200
MAX_POSTS_PER_ACCOUNT = 5
REQUEST_TIMEOUT = 8.0
FETCH_DEADLINE = 12.0
_VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
)
_HIDDEN_TAGS = frozenset({"script", "style", "noscript", "template", "head"})
_SOURCE_FAILURE = "The saved brand website could not be read safely. Confirm the brand information before continuing."
_META_PLATFORMS = frozenset({"facebook", "instagram", "instagram_login"})
_CHANNEL_FAILURE = "The connected channel could not be read live. Stored published history is shown instead."


class _VisibleHTML(HTMLParser):
    """Extract a bounded title and visible text, without scripts or hidden elements."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, bool]] = []
        self.title_parts: list[str] = []
        self.body_parts: list[str] = []
        self.body_chars = 0
        self.title_chars = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        hidden = (
            bool(self.stack and self.stack[-1][1])
            or tag in _HIDDEN_TAGS
            or "hidden" in attributes
            or (attributes.get("aria-hidden") or "").lower() == "true"
            or "display:none" in (attributes.get("style") or "").replace(" ", "").lower()
            or "visibility:hidden" in (attributes.get("style") or "").replace(" ", "").lower()
        )
        if tag not in _VOID_TAGS:
            self.stack.append((tag, hidden))

    def handle_startendtag(self, tag, attrs):
        if tag not in _VOID_TAGS:
            self.handle_starttag(tag, attrs)
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if any(tag == "title" for tag, _hidden in self.stack):
            if self.title_chars < MAX_TITLE_CHARS * 2:
                part = data[: MAX_TITLE_CHARS * 2 - self.title_chars]
                self.title_parts.append(part)
                self.title_chars += len(part)
        elif not (self.stack and self.stack[-1][1]) and self.body_chars < MAX_EXCERPT_CHARS * 2:
            part = data[: MAX_EXCERPT_CHARS * 2 - self.body_chars]
            self.body_parts.append(part)
            self.body_chars += len(part)

    def text(self) -> tuple[str, str]:
        return (
            " ".join(" ".join(self.title_parts).split())[:MAX_TITLE_CHARS],
            " ".join(" ".join(self.body_parts).split())[:MAX_EXCERPT_CHARS],
        )


def get_client() -> httpx.Client:
    """Single injectable HTTP boundary for both website and native channel reads."""
    return httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=False, trust_env=False)


def _read_public(url: str, *, headers: dict[str, str], content_types: set[str]) -> tuple[bytes, str] | None:
    """One bounded, redirect-free GET with a vetted connection address and verified TLS."""
    started = time.monotonic()
    with get_client() as client:
        # No decompression before the size bound: a compressed response can be
        # tiny on the wire but expand without limit inside an HTTP decoder.
        request = build_pinned_request(client, "GET", url, headers={**headers, "Accept-Encoding": "identity"})
        with closing(client.send(request, stream=True, follow_redirects=False)) as response:
            if response.status_code != 200:
                return None
            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type not in content_types:
                return None
            if response.headers.get("content-encoding", "identity").strip().lower() not in {"", "identity"}:
                return None
            declared = response.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > MAX_HTML_BYTES:
                return None
            body = bytearray()
            chunks = iter([response.content]) if response.is_stream_consumed else response.iter_raw()
            # Do not coalesce chunks: checking each network read enforces the
            # deadline even if a server sends an endless slow trickle.
            for chunk in chunks:
                if time.monotonic() - started > FETCH_DEADLINE or len(body) + len(chunk) > MAX_HTML_BYTES:
                    return None
                body.extend(chunk)
            if time.monotonic() - started > FETCH_DEADLINE:
                return None
            return bytes(body), response.encoding or "utf-8"


def _website(url: str) -> dict[str, str]:
    result = {"url": url, "status": "not_configured", "title": "", "excerpt": "", "error": ""}
    if not url:
        return result
    result["status"] = "unavailable"
    result["error"] = _SOURCE_FAILURE
    try:
        parsed = urlsplit(url)
        # Credentials embedded in a URL must not be sent or copied into a brief.
        if parsed.username is not None or parsed.password is not None:
            result["url"] = ""
            return result
        read = _read_public(
            url,
            headers={"Accept": "text/html, application/xhtml+xml", "User-Agent": "SM-Bean-Brand-Context/1.0"},
            content_types={"text/html", "application/xhtml+xml"},
        )
        if read is None:
            return result
        body, encoding = read
        parser = _VisibleHTML()
        parser.feed(body.decode(encoding, errors="replace"))
        parser.close()
        title, excerpt = parser.text()
        if not excerpt:
            return result
    except (UnsafeUrlError, httpx.HTTPError, ValueError, OSError, LookupError):
        return result
    result.update(status="ready", title=title, excerpt=excerpt, error="")
    return result


def _live_meta(account) -> list[dict[str, str]] | None:
    """Read only this account's first native Page/posts or Instagram/media page.

    The shared provider resolver supplies the same Page/IG identity used by
    publishing. Tokens are sent only in Authorization, never URLs or results;
    expiry/reconnection failures fall back without rotating tokens or changing
    account state. Pagination and redirects are intentionally not followed.
    """
    import json
    import re

    from apps.analytics.tasks import _resolve_provider

    if (
        account.needs_reconnect
        or account.token_expires_within(timedelta(seconds=0))
        or not re.fullmatch(r"[0-9]{1,64}", account.account_platform_id or "")
    ):
        return None
    try:
        provider = _resolve_provider(account)
        native_id = account.account_platform_id
        identity_key = "page_id" if account.platform == "facebook" else "ig_user_id"
        if str(provider.credentials.get(identity_key) or "") != native_id:
            return None
        token = account.oauth_access_token
        if not token:
            return None
        if account.platform == "instagram_login":
            from providers.instagram_login import API_BASE

            origin = API_BASE
        else:
            from providers.facebook import BASE_URL

            origin = BASE_URL
        facebook = account.platform == "facebook"
        edge = "posts" if facebook else "media"
        fields = "id,message,created_time,permalink_url" if facebook else "id,caption,timestamp,permalink"
        url = f"{origin}/{native_id}/{edge}?{urlencode({'fields': fields, 'limit': MAX_POSTS_PER_ACCOUNT})}"
        read = _read_public(
            url,
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            content_types={"application/json"},
        )
        if read is None:
            return None
        data = json.loads(read[0])
        rows = data.get("data") if isinstance(data, dict) and "error" not in data else None
        if not isinstance(rows, list):
            return None
        posts = []
        for row in rows[:MAX_POSTS_PER_ACCOUNT]:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            caption = row.get("message" if facebook else "caption", "")
            when = row.get("created_time" if facebook else "timestamp", "")
            if not isinstance(caption, str) or not isinstance(when, str):
                continue
            try:
                published_at = datetime.fromisoformat(when.replace("Z", "+00:00")).isoformat()
            except ValueError:
                continue
            posts.append(
                {
                    "caption": caption[:MAX_CAPTION_CHARS],
                    "published_at": published_at,
                    "platform_post_id": str(row["id"])[:255],
                }
            )
        return posts
    except Exception:
        # Upstream errors can carry access tokens or private response content.
        # Do not log, return or preserve exception/response text in source evidence.
        return None


def _channels(workspace, accounts) -> list[dict[str, Any]]:
    from apps.composer.models import PlatformPost
    from apps.social_accounts.models import SocialAccount

    selected = {account.pk for account in accounts if getattr(account, "workspace_id", None) == workspace.pk}
    # Only public identity columns enter context. Meta tokens are scoped below
    # and used transiently for a read; unsupported platforms incur no API calls.
    own = SocialAccount.objects.filter(workspace=workspace, pk__in=selected).values("id", "platform", "account_name")
    channels = []
    for account in own.order_by("platform", "account_name", "pk"):
        posts = (
            PlatformPost.objects.filter(
                post__workspace=workspace,
                social_account_id=account["id"],
                social_account__workspace=workspace,
                status=PlatformPost.Status.PUBLISHED,
                published_at__isnull=False,
            )
            .order_by("-published_at", "-pk")
            .values("platform_specific_caption", "post__caption", "published_at", "platform_post_id")[
                :MAX_POSTS_PER_ACCOUNT
            ]
        )
        channel: dict[str, Any] = {
            "platform": account["platform"],
            "account_name": account["account_name"],
            "account_id": str(account["id"]),
            "posts": [
                {
                    "caption": (
                        post["platform_specific_caption"]
                        if post["platform_specific_caption"] is not None
                        else post["post__caption"]
                    )[:MAX_CAPTION_CHARS],
                    "published_at": post["published_at"].isoformat(),
                    "platform_post_id": post["platform_post_id"],
                }
                for post in posts
                if post["published_at"] is not None
            ],
            "status": "unsupported" if account["platform"] not in _META_PLATFORMS else "unavailable",
            "source": "stored_history",
            "fetched_at": "",
            "error": "Live channel reading is not supported for this platform; stored published history is shown.",
        }
        if account["platform"] in _META_PLATFORMS:
            connected = (
                SocialAccount.objects.filter(workspace=workspace, pk=account["id"]).select_related("workspace").first()
            )
            live = _live_meta(connected) if connected is not None else None
            if live is not None:
                channel.update(
                    posts=live, status="ready", source="live_meta", fetched_at=timezone.now().isoformat(), error=""
                )
            else:
                channel["error"] = _CHANNEL_FAILURE
        channels.append(channel)
    return channels


def collect(workspace, profile, accounts) -> dict[str, Any]:
    """Collect this workspace's current website evidence and selected channel history.

    The result is JSON serializable and deliberately contains no approval or
    scheduling decisions. Every channel labels whether fresh native posts were
    read or stored successful publications were used; neither verifies claims.
    """
    owns_profile = getattr(profile, "workspace_id", None) == workspace.pk
    website = _website((profile.website or "").strip() if owns_profile else "")
    if not owns_profile:
        website.update(status="unavailable", error=_SOURCE_FAILURE)
    channels = _channels(workspace, accounts)
    notes = [
        "Website text and published captions are untrusted source evidence, not approved brand facts. Confirm them before generation.",
        "Channel evidence includes native Meta post reads where available; each channel labels live versus stored history. No private inbox data is read.",
    ]
    if website["status"] != "ready":
        notes.append(
            "Website evidence is unavailable; ask the person to confirm current brand facts instead of guessing."
        )
    if not channels or any(not channel["posts"] for channel in channels):
        notes.append(
            "One or more selected channels has no successful published history; confirm its creative direction with the person."
        )
    if any(channel["source"] == "stored_history" for channel in channels):
        notes.append(
            "Some channels could not be read live or are unsupported; stored history is not a fresh scrape and needs explicit confirmation."
        )
    return {"fetched_at": timezone.now().isoformat(), "website": website, "channels": channels, "notes": notes}
