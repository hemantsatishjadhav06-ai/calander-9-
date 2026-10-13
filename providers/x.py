"""X (formerly Twitter) API v2 provider.

Publishing and identity only, on purpose. X's API is pay-per-use with no free
tier: every call — reads included — spends credits on the developer account
that owns the app. Comment polling, DM polling and analytics sync would each run
on a schedule nobody is watching and quietly drain that balance, so this
provider implements none of them; the base class's ``NotImplementedError``
stubs are what tell the inbox and analytics layers that X has nothing to offer
(see ``apps.analytics.constants.NO_ANALYTICS_PLATFORMS``).

What it does:

* OAuth 2.0 Authorization Code with PKCE (S256), confidential client — the
  token endpoint takes HTTP Basic auth with the app's client id and secret.
  Access tokens live two hours; refresh tokens rotate on every refresh, so the
  new one must replace the old (``SocialAccount.refresh_oauth_token`` does).
* ``get_profile`` from ``GET /2/users/me`` — doubles as the health check.
* ``publish_post``: text, up to four images, or one video or GIF, uploaded
  through the v2 media endpoints (initialize → append → finalize → status).
* ``delete_post``: ``DELETE /2/tweets/{id}``.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import math
import os
import re
import time
import unicodedata
from datetime import UTC, datetime, timedelta
from urllib.parse import quote, urlencode

import httpx

from .base import SocialProvider
from .exceptions import APIError, OAuthError, ProviderError, PublishError, QuotaExceededError
from .types import (
    AccountProfile,
    AuthType,
    MediaType,
    OAuthTokens,
    PostType,
    PublishContent,
    PublishResult,
)

logger = logging.getLogger(__name__)

AUTH_URL = "https://x.com/i/oauth2/authorize"
TOKEN_URL = "https://api.x.com/2/oauth2/token"
API_BASE = "https://api.x.com/2"
POST_URL_TEMPLATE = "https://x.com/{username}/status/{post_id}"
# Resolves without knowing the author's handle; used when we don't have it.
POST_URL_FALLBACK_TEMPLATE = "https://x.com/i/web/status/{post_id}"

SCOPES = ["tweet.read", "tweet.write", "users.read", "offline.access", "media.write"]
PROFILE_FIELDS = "profile_image_url,public_metrics,username,name"

# ---------------------------------------------------------------------------
# Text length, as X counts it
# ---------------------------------------------------------------------------

MAX_WEIGHTED_LENGTH = 280
# Every link costs this much, however long or short it is typed: X rewrites it
# to a t.co link before counting.
URL_WEIGHT = 23

# Code-point ranges X counts as one character; everything outside them (CJK,
# most emoji) counts as two. These are the ranges in twitter-text's v3 config.
_SINGLE_WEIGHT_RANGES = (
    (0x0000, 0x10FF),
    (0x2000, 0x200D),
    (0x2010, 0x201F),
    (0x2032, 0x2037),
)

# A link X will shorten: an http(s) scheme or a leading "www.", up to the next
# whitespace, not counting punctuation that closes the sentence around it.
_URL_RE = re.compile(r"(?:https?://|www\.)\S*[^\s.,;:!?)\]}'\"]", re.IGNORECASE)

_ZWJ = 0x200D
_KEYCAP = 0x20E3
_VARIATION_SELECTORS = (0xFE0E, 0xFE0F)
_SKIN_TONE_MODIFIERS = (0x1F3FB, 0x1F3FF)
_REGIONAL_INDICATORS = (0x1F1E6, 0x1F1FF)
_EMOJI_TAGS = (0xE0020, 0xE007F)


def _char_weight(code_point: int) -> int:
    for start, end in _SINGLE_WEIGHT_RANGES:
        if start <= code_point <= end:
            return 1
    return 2


def _is_emoji_modifier(code_point: int) -> bool:
    return (
        code_point in _VARIATION_SELECTORS
        or _SKIN_TONE_MODIFIERS[0] <= code_point <= _SKIN_TONE_MODIFIERS[1]
        or _EMOJI_TAGS[0] <= code_point <= _EMOJI_TAGS[1]
    )


def _weighted_text_length(text: str) -> int:
    """Weighted length of link-free text.

    An emoji sequence counts as one emoji (two), the way X counts it, rather
    than as the sum of its code points: variation selectors, skin-tone modifiers
    and tag characters ride free; after an emoji, a zero-width joiner pulls the
    next code point into the same emoji; a regional-indicator pair (a flag)
    counts once; and a keycap ("1️⃣") makes its digit an emoji. Without this
    "❤️" reads as 4 and a family emoji as 8. A joiner between letters (as some
    scripts use it) joins nothing.
    """
    total = 0
    last_weight = 0
    join_next = False
    pending_flag_half = False
    for ch in text:
        cp = ord(ch)
        if _is_emoji_modifier(cp):
            continue
        if cp == _ZWJ:
            join_next = last_weight == 2
            continue
        if join_next:
            join_next = False
            continue
        if cp == _KEYCAP:
            # Digit (1) + keycap → one emoji (2).
            total += 1
            last_weight = 2
            continue
        if _REGIONAL_INDICATORS[0] <= cp <= _REGIONAL_INDICATORS[1]:
            if pending_flag_half:
                pending_flag_half = False
                continue
            pending_flag_half = True
        else:
            pending_flag_half = False
        last_weight = _char_weight(cp)
        total += last_weight
    return total


def weighted_length(text: str) -> int:
    """Length of ``text`` as X counts it against the 280 limit.

    Links count as ``URL_WEIGHT`` each; the rest is weighted per code point (see
    ``_SINGLE_WEIGHT_RANGES``) after NFC normalisation, which is what X applies
    before counting. Bare domains typed without "www." or a scheme ("example.com")
    are counted as typed — X may still shorten those, so a post right at the
    limit can be refused; everything else here errs on the long side.
    """
    if not text:
        return 0
    text = unicodedata.normalize("NFC", text)
    total = 0
    cursor = 0
    for match in _URL_RE.finditer(text):
        total += _weighted_text_length(text[cursor : match.start()]) + URL_WEIGHT
        cursor = match.end()
    return total + _weighted_text_length(text[cursor:])


# ---------------------------------------------------------------------------
# Media
# ---------------------------------------------------------------------------

MAX_IMAGES = 4
# APPEND segment size. Small images go up in one segment; videos and GIFs are
# streamed off disk a segment at a time so a large file never sits in memory.
SEGMENT_BYTES = 4 * 1024 * 1024
MEDIA_CATEGORY = {"image": "tweet_image", "gif": "tweet_gif", "video": "tweet_video"}
# processing_info.state values that mean "keep waiting".
MEDIA_PENDING_STATES = frozenset({"pending", "in_progress"})
MEDIA_STATUS_MAX_POLLS = 60
MEDIA_STATUS_DEFAULT_WAIT = 2  # seconds, when X sends no check_after_secs
MEDIA_STATUS_MAX_WAIT = 10  # seconds; caps a large check_after_secs per poll

MIME_BY_EXTENSION = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
}

MEDIA_MIX_MESSAGE = "X takes up to 4 images, or a single video or GIF, per post. Remove the extra media and try again."

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

CREDITS_DEPLETED_MESSAGE = (
    "X rejected the post: the X developer account has no API credits. Add credits at console.x.com."
)
# Long enough for any sentence X writes, short enough to stay well inside
# ``error_messages._MAX_PASSTHROUGH_LENGTH`` once prefixed.
_MAX_DETAIL_LENGTH = 220


def pkce_code_challenge(code_verifier: str) -> str:
    """RFC 7636 S256 challenge: unpadded base64url of SHA-256(verifier).

    Standard PKCE — unlike TikTok, whose challenge is a hex digest.
    """
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _is_credits_problem(body: dict) -> bool:
    """Whether an error body is X saying the developer account is out of credits.

    Pay-per-use accounts are refused with a ``CreditsDepleted``-titled problem
    when the balance is empty. Matched loosely on "credit" in the problem's
    title or type so a renamed variant still lands here.
    """
    if not isinstance(body, dict):
        return False
    for key in ("title", "type"):
        value = body.get(key)
        if isinstance(value, str) and "credit" in value.lower():
            return True
    return False


def _problem_detail(body: dict) -> str:
    """X's own sentence about a refused request, or ``""``.

    v2 errors are problem documents. A validation failure puts the specific
    reason in ``errors[].message`` and something generic in ``detail``, so the
    specific one is preferred; a refusal like a duplicate post only has
    ``detail``.
    """
    if not isinstance(body, dict):
        return ""
    candidates = [item.get("message") for item in body.get("errors") or [] if isinstance(item, dict)]
    candidates += [body.get("detail"), body.get("title")]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            detail = " ".join(candidate.split())
            if len(detail) > _MAX_DETAIL_LENGTH:
                detail = detail[: _MAX_DETAIL_LENGTH - 1].rstrip() + "…"
            return detail
    return ""


def _rate_limit_reset(headers, now: datetime) -> tuple[datetime | None, int | None]:
    """When X's rate-limit window reopens, as ``(resets_at, seconds_from_now)``.

    ``x-rate-limit-reset`` is the epoch second the window resets. ``Retry-After``
    is honoured as a fallback. ``(None, None)`` when neither is usable, which
    leaves the publish engine on its ordinary retry ladder.
    """
    raw_reset = headers.get("x-rate-limit-reset")
    if raw_reset:
        try:
            resets_at = datetime.fromtimestamp(int(raw_reset), UTC)
        except (TypeError, ValueError, OverflowError, OSError):
            resets_at = None
        if resets_at is not None:
            return resets_at, max(0, math.ceil((resets_at - now).total_seconds()))
    raw_retry_after = headers.get("retry-after")
    if raw_retry_after:
        try:
            seconds = max(0, int(raw_retry_after))
        except (TypeError, ValueError):
            return None, None
        return now + timedelta(seconds=seconds), seconds
    return None, None


class XProvider(SocialProvider):
    """X API v2 provider: OAuth 2.0 + PKCE, publish, delete, identity."""

    # X refuses an authorization request without a code_challenge.
    uses_pkce = True

    # Media goes up as bytes through the v2 upload endpoints; X never fetches a
    # URL for us, so the engine has to put the file on local disk.
    needs_local_media = True

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    @property
    def platform_name(self) -> str:
        return "X"

    @property
    def auth_type(self) -> AuthType:
        return AuthType.OAUTH2

    @property
    def max_caption_length(self) -> int:
        return MAX_WEIGHTED_LENGTH

    @property
    def supported_post_types(self) -> list[PostType]:
        return [PostType.TEXT, PostType.IMAGE, PostType.VIDEO]

    @property
    def supported_media_types(self) -> list[MediaType]:
        return [MediaType.JPEG, MediaType.PNG, MediaType.WEBP, MediaType.GIF, MediaType.MP4, MediaType.MOV]

    @property
    def required_scopes(self) -> list[str]:
        return list(SCOPES)

    # ------------------------------------------------------------------
    # OAuth
    # ------------------------------------------------------------------

    def _client_credentials(self) -> tuple[str, str]:
        client_id = str(self.credentials.get("client_id") or "").strip()
        client_secret = str(self.credentials.get("client_secret") or "").strip()
        if not client_id or not client_secret:
            raise OAuthError(
                "X app credentials are not configured (client_id and client_secret are both required).",
                platform=self.platform_name,
                retryable=False,
            )
        return client_id, client_secret

    def _basic_auth_header(self) -> dict[str, str]:
        client_id, client_secret = self._client_credentials()
        encoded = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode("ascii")
        return {"Authorization": f"Basic {encoded}"}

    def get_auth_url(self, redirect_uri: str, state: str, code_verifier: str | None = None) -> str:
        if not code_verifier:
            # Fail here rather than send the user to a consent screen X will
            # refuse: every caller should have issued one via issue_pkce_verifier.
            raise OAuthError("X requires PKCE: no code_verifier was supplied.", platform=self.platform_name)
        client_id, _secret = self._client_credentials()
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(self.required_scopes),
            "state": state,
            "code_challenge": pkce_code_challenge(code_verifier),
            "code_challenge_method": "S256",
        }
        # quote, not quote_plus: scopes are space-separated and X documents them
        # as %20, not "+".
        return f"{AUTH_URL}?{urlencode(params, quote_via=quote)}"

    def exchange_code(self, code: str, redirect_uri: str, code_verifier: str | None = None) -> OAuthTokens:
        if not code_verifier:
            raise OAuthError("X requires PKCE: no code_verifier was supplied.", platform=self.platform_name)
        client_id, _secret = self._client_credentials()
        resp = self._request(
            "POST",
            TOKEN_URL,
            headers=self._basic_auth_header(),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
                "client_id": client_id,
            },
        )
        return self._tokens_from(resp.json(), "token exchange")

    def refresh_token(self, refresh_token: str) -> OAuthTokens:
        """Trade a refresh token for a new pair.

        X rotates refresh tokens: the one passed in stops working once this
        succeeds, so the returned ``refresh_token`` must be persisted.
        """
        client_id, _secret = self._client_credentials()
        resp = self._request(
            "POST",
            TOKEN_URL,
            headers=self._basic_auth_header(),
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
            },
        )
        return self._tokens_from(resp.json(), "token refresh")

    def _tokens_from(self, body: dict, step: str) -> OAuthTokens:
        if not isinstance(body, dict) or not body.get("access_token"):
            raise OAuthError(
                f"X {step} returned no access token",
                platform=self.platform_name,
                raw_response=body if isinstance(body, dict) else {},
            )
        return OAuthTokens(
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token"),
            expires_in=body.get("expires_in"),
            token_type=body.get("token_type") or "bearer",
            scope=body.get("scope"),
            raw_response=body,
        )

    # ------------------------------------------------------------------
    # Profile / health
    # ------------------------------------------------------------------

    def get_profile(self, access_token: str) -> AccountProfile:
        """The connected user, from ``GET /2/users/me``.

        Also what the periodic health check calls. That is a billed read, which
        is why it is the *only* read this provider makes on a schedule.
        """
        resp = self._request(
            "GET",
            f"{API_BASE}/users/me",
            access_token=access_token,
            params={"user.fields": PROFILE_FIELDS},
        )
        body = resp.json()
        user = (body or {}).get("data") or {}
        user_id = str(user.get("id") or "")
        if not user_id:
            raise APIError(
                "X returned no user for this token",
                status_code=resp.status_code,
                platform=self.platform_name,
                raw_response=body if isinstance(body, dict) else {},
            )
        username = user.get("username") or ""
        metrics = user.get("public_metrics") or {}
        try:
            followers = int(metrics.get("followers_count") or 0)
        except (TypeError, ValueError):
            followers = 0
        return AccountProfile(
            platform_id=user_id,
            name=user.get("name") or username,
            handle=username or None,
            avatar_url=user.get("profile_image_url"),
            follower_count=followers,
            extra={"username": username},
        )

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    def publish_post(self, access_token: str, content: PublishContent) -> PublishResult:
        """Create a post: text, up to four images, or one video or GIF.

        Refusals X explains (no credits, duplicate text, an invalid file) come
        back as a non-retryable :class:`PublishError` carrying a sentence the
        composer can show as-is — ``error_messages`` only passes ``PublishError``
        text through, and retrying would just pay for the same refusal again.
        Rate limits stay a :class:`QuotaExceededError`, which the engine
        reschedules for the moment the window reopens.
        """
        try:
            return self._publish(access_token, content)
        except APIError as exc:
            converted = self._as_publish_error(exc)
            if converted is exc:
                raise
            raise converted from exc

    def _publish(self, access_token: str, content: PublishContent) -> PublishResult:
        text = content.text or ""
        length = weighted_length(text)
        if length > MAX_WEIGHTED_LENGTH:
            raise PublishError(
                f"This post is {length} characters as X counts them (each link counts as {URL_WEIGHT}); "
                f"X allows {MAX_WEIGHTED_LENGTH}. Shorten it and try again.",
                platform=self.platform_name,
                retryable=False,
            )

        media = self._plan_media(content)
        if not text.strip() and not media:
            raise PublishError(
                "There is nothing to post to X: add text or media.",
                platform=self.platform_name,
                retryable=False,
            )

        media_ids = [self._upload_media(access_token, path, mime, kind) for path, mime, kind in media]

        payload: dict = {}
        if text.strip():
            payload["text"] = text
        if media_ids:
            payload["media"] = {"media_ids": media_ids}

        resp = self._request("POST", f"{API_BASE}/tweets", access_token=access_token, json=payload)
        body = resp.json()
        data = (body or {}).get("data") or {}
        post_id = str(data.get("id") or "")
        if not post_id:
            # X answered 2xx, so the post may well exist. A blind retry is how a
            # duplicate lands on a real account; ask the user to look instead.
            raise PublishError(
                "X accepted the post but didn't confirm it. Check the account before publishing again.",
                platform=self.platform_name,
                raw_response=body if isinstance(body, dict) else {},
                retryable=False,
            )
        return PublishResult(
            platform_post_id=post_id,
            url=self._post_url(post_id, content),
            extra=data,
        )

    def _post_url(self, post_id: str, content: PublishContent) -> str:
        username = content.extra.get("username") or self.credentials.get("username") or ""
        if username:
            return POST_URL_TEMPLATE.format(username=username, post_id=post_id)
        return POST_URL_FALLBACK_TEMPLATE.format(post_id=post_id)

    def _as_publish_error(self, exc: APIError) -> ProviderError:
        """Turn the refusals X explains into a user-facing PublishError.

        Returns ``exc`` unchanged for anything else — 401s keep their
        reconnect handling, 5xx stay retryable.
        """
        if exc.status_code == 402 or _is_credits_problem(exc.raw_response):
            return PublishError(
                CREDITS_DEPLETED_MESSAGE,
                platform=self.platform_name,
                raw_response=exc.raw_response,
                retryable=False,
            )
        if exc.status_code in (400, 403):
            detail = _problem_detail(exc.raw_response)
            if detail:
                return PublishError(
                    f"X rejected the post: {detail}",
                    platform=self.platform_name,
                    raw_response=exc.raw_response,
                    retryable=False,
                )
        return exc

    def _plan_media(self, content: PublishContent) -> list[tuple[str, str, str]]:
        """``(path, mime, kind)`` per attachment, validated against X's rules."""
        if not content.media_files:
            if content.media_urls:
                raise PublishError(
                    "X needs the media file itself, and none was provided for this post.",
                    platform=self.platform_name,
                    retryable=False,
                )
            return []

        planned = []
        for index, path in enumerate(content.media_files):
            mime = self._media_mime(path)
            if mime == "image/gif":
                kind = "gif"
            elif mime.startswith("image/"):
                kind = "image"
            elif mime.startswith("video/"):
                kind = "video"
            else:
                declared = content.media_types[index] if index < len(content.media_types) else ""
                raise PublishError(
                    f"X can't attach this file{f' ({declared})' if declared else ''}. "
                    "Use a JPEG, PNG, WebP or GIF image, or an MP4 or MOV video.",
                    platform=self.platform_name,
                    retryable=False,
                )
            planned.append((path, mime, kind))

        kinds = [kind for _path, _mime, kind in planned]
        has_motion = any(kind in ("video", "gif") for kind in kinds)
        if (has_motion and len(kinds) > 1) or len(kinds) > MAX_IMAGES:
            raise PublishError(MEDIA_MIX_MESSAGE, platform=self.platform_name, retryable=False)
        return planned

    @staticmethod
    def _media_mime(path: str) -> str:
        """The file's real MIME type, from its magic bytes.

        The extension on the engine's temp file is copied from the uploader's
        filename and is cosmetic, so it is only a fallback.
        """
        from apps.media_library.validators import sniff_mime

        sniffed = None
        try:
            with open(path, "rb") as fh:
                sniffed = sniff_mime(fh)
        except OSError:
            logger.warning("Could not read %s to sniff its type", path, exc_info=True)
        if sniffed:
            return sniffed
        return MIME_BY_EXTENSION.get(os.path.splitext(path)[1].lower(), "application/octet-stream")

    def _upload_media(self, access_token: str, path: str, mime: str, kind: str) -> str:
        """Upload one file through the v2 media endpoints; return its media id."""
        total_bytes = os.path.getsize(path)
        init = self._request(
            "POST",
            f"{API_BASE}/media/upload/initialize",
            access_token=access_token,
            json={
                "media_type": mime,
                "total_bytes": total_bytes,
                "media_category": MEDIA_CATEGORY[kind],
            },
        )
        init_body = init.json()
        media_id = str(((init_body or {}).get("data") or {}).get("id") or "")
        if not media_id:
            raise PublishError(
                "X did not return a media id for the upload.",
                platform=self.platform_name,
                raw_response=init_body if isinstance(init_body, dict) else {},
            )

        filename = os.path.basename(path)
        with open(path, "rb") as fh:
            segment_index = 0
            while True:
                chunk = fh.read(SEGMENT_BYTES)
                if not chunk:
                    break
                self._request(
                    "POST",
                    f"{API_BASE}/media/upload/{media_id}/append",
                    access_token=access_token,
                    data={"segment_index": str(segment_index)},
                    files={"media": (filename, chunk, mime)},
                    timeout=120.0,
                )
                segment_index += 1

        finalize = self._request(
            "POST",
            f"{API_BASE}/media/upload/{media_id}/finalize",
            access_token=access_token,
        )
        finalize_body = finalize.json() if finalize.content else {}
        processing = ((finalize_body or {}).get("data") or {}).get("processing_info")
        if processing:
            self._wait_for_media(access_token, media_id, processing)
        return media_id

    def _wait_for_media(self, access_token: str, media_id: str, processing: dict) -> None:
        """Poll the upload's STATUS until X has finished processing it.

        Videos and GIFs are transcoded after FINALIZE; a post that references
        them before they reach ``succeeded`` is refused.
        """
        for _ in range(MEDIA_STATUS_MAX_POLLS):
            state = str(processing.get("state") or "")
            if state == "succeeded":
                return
            if state == "failed":
                error = processing.get("error") or {}
                reason = error.get("message") or error.get("name") or "no reason given"
                raise PublishError(
                    f"X could not process this media ({reason}).",
                    platform=self.platform_name,
                    raw_response={"processing_info": processing},
                    retryable=False,
                )
            if state and state not in MEDIA_PENDING_STATES:
                # A state we don't know yet: treat it as done rather than spin.
                logger.warning("Unknown X media processing state %r for %s", state, media_id)
                return

            wait = processing.get("check_after_secs") or MEDIA_STATUS_DEFAULT_WAIT
            try:
                wait = float(wait)
            except (TypeError, ValueError):
                wait = MEDIA_STATUS_DEFAULT_WAIT
            time.sleep(min(max(wait, 1.0), MEDIA_STATUS_MAX_WAIT))

            resp = self._request(
                "GET",
                f"{API_BASE}/media/upload",
                access_token=access_token,
                params={"command": "STATUS", "media_id": media_id},
            )
            processing = ((resp.json() or {}).get("data") or {}).get("processing_info") or {"state": "succeeded"}

        raise PublishError(
            "X is still processing this media. We'll try the post again shortly.",
            platform=self.platform_name,
        )

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_post(self, access_token: str, post_id: str) -> bool:
        """Delete a post this account published. True when X confirms it."""
        resp = self._request("DELETE", f"{API_BASE}/tweets/{post_id}", access_token=access_token)
        return bool(((resp.json() or {}).get("data") or {}).get("deleted"))

    # ------------------------------------------------------------------
    # Errors
    # ------------------------------------------------------------------

    def _error_for_response(self, response: httpx.Response, *, now: datetime | None = None) -> ProviderError:
        """Tell X's two billing-shaped refusals apart from everything else.

        * 429 → :class:`QuotaExceededError` (a :class:`RateLimitError`) carrying
          ``resets_at`` from ``x-rate-limit-reset``, so the publish engine
          reschedules for when the window reopens instead of burning its retry
          ladder inside it, and the health check keeps the account connected.
        * 402 / a ``CreditsDepleted`` problem → a non-retryable
          :class:`APIError` saying the developer account is out of credits.
          Retrying cannot help until someone tops up, and every retry would be
          another request against an empty balance.

        Everything else keeps the base mapping. ``now`` pins the clock for tests.
        """
        body = self._safe_json(response)
        if response.status_code == 429:
            resets_at, retry_after = _rate_limit_reset(response.headers, now or datetime.now(UTC))
            when = f" until {resets_at:%Y-%m-%d %H:%M} UTC" if resets_at else ""
            logger.warning("X API 429 (rate limited%s): %s", when, response.text[:500])
            return QuotaExceededError(
                f"X rate limit reached{when}.",
                resets_at=resets_at,
                retry_after=retry_after,
                status_code=429,
                quota_scope="x-rate-limit",
                platform=self.platform_name,
                raw_response=body,
            )
        if response.status_code == 402 or _is_credits_problem(body):
            logger.warning("X API %s (out of credits): %s", response.status_code, response.text[:500])
            return APIError(
                CREDITS_DEPLETED_MESSAGE,
                status_code=response.status_code,
                platform=self.platform_name,
                raw_response=body,
                retryable=False,
            )
        return super()._error_for_response(response)
