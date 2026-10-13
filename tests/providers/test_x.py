"""Tests for the X (Twitter) provider.

HTTP is mocked two ways, matching the rest of this package: ``_request`` is
patched where a test is about the requests we build, and ``httpx.Client`` is
given a ``MockTransport`` where the real status-code-to-exception path has to
run (402, 429, problem documents).
"""

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from providers import caption_wire_length, get_provider
from providers.exceptions import APIError, OAuthError, PublishError, QuotaExceededError, RateLimitError
from providers.types import PostType, PublishContent
from providers.x import (
    API_BASE,
    AUTH_URL,
    CREDITS_DEPLETED_MESSAGE,
    MEDIA_MIX_MESSAGE,
    TOKEN_URL,
    XProvider,
    pkce_code_challenge,
    weighted_length,
)

CREDS = {"client_id": "x-client-id", "client_secret": "x-client-secret"}
REDIRECT = "https://studio.example.com/social-accounts/callback/x/"

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64
GIF = b"GIF89a" + b"\x00" * 64


def _response(payload: dict | None = None, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json = MagicMock(return_value=payload if payload is not None else {})
    resp.content = json.dumps(payload).encode() if payload is not None else b""
    return resp


def _provider(**extra) -> XProvider:
    return XProvider({**CREDS, **extra})


def _expected_basic() -> str:
    return "Basic " + base64.b64encode(b"x-client-id:x-client-secret").decode()


@pytest.fixture
def mock_transport(monkeypatch):
    """Route every httpx.Client through a handler the test supplies."""

    def install(handler):
        transport = httpx.MockTransport(handler)
        original = httpx.Client
        monkeypatch.setattr(httpx, "Client", lambda *a, **k: original(*a, **{**k, "transport": transport}))

    return install


# ---------------------------------------------------------------------------
# Registration and capability honesty
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_registered_under_x(self):
        provider = get_provider("x", CREDS)
        assert isinstance(provider, XProvider)
        assert provider.platform_name == "X"
        assert provider.max_caption_length == 280

    def test_declares_pkce(self):
        assert XProvider.uses_pkce is True

    def test_uploads_need_the_file_on_disk(self):
        assert XProvider.needs_local_media is True
        assert XProvider.publish_is_async is False

    @pytest.mark.parametrize(
        ("method", "args"),
        [
            ("get_messages", ("tok",)),
            ("get_post_metrics", ("tok", "1")),
            ("get_account_metrics", ("tok", (datetime.now(UTC), datetime.now(UTC)))),
            ("publish_comment", ("tok", "1", "hi")),
            ("reply_to_comment", ("tok", "1", "hi")),
            ("reply_to_message", ("tok", "1", "hi")),
        ],
    )
    def test_billed_background_reads_are_not_implemented(self, method, args):
        """Inbox polling and analytics would spend credits unattended."""
        with patch.object(XProvider, "_request") as mock_request, pytest.raises(NotImplementedError):
            getattr(_provider(), method)(*args)
        mock_request.assert_not_called()

    def test_analytics_reports_x_as_unavailable(self):
        from apps.analytics.constants import NO_ANALYTICS_PLATFORMS
        from apps.analytics.services import CAUSE_NO_API, analytics_availability
        from apps.analytics.tasks import BACKFILL_DAYS_PER_PLATFORM

        assert "x" in NO_ANALYTICS_PLATFORMS
        assert BACKFILL_DAYS_PER_PLATFORM["x"] == 0
        assert analytics_availability("x", ["x"]).cause == CAUSE_NO_API


# ---------------------------------------------------------------------------
# OAuth
# ---------------------------------------------------------------------------


class TestGetAuthUrl:
    def test_authorize_url_carries_pkce_challenge_and_scopes(self):
        verifier = "verifier-" + "a" * 50
        url = _provider().get_auth_url(REDIRECT, "state-123", code_verifier=verifier)

        parts = urlsplit(url)
        assert f"{parts.scheme}://{parts.netloc}{parts.path}" == AUTH_URL
        query = parse_qs(parts.query)
        assert query["response_type"] == ["code"]
        assert query["client_id"] == ["x-client-id"]
        assert query["redirect_uri"] == [REDIRECT]
        assert query["state"] == ["state-123"]
        assert query["scope"] == ["tweet.read tweet.write users.read offline.access media.write"]
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        assert query["code_challenge"] == [expected]
        assert query["code_challenge_method"] == ["S256"]

    def test_scopes_are_percent_encoded_not_plus_joined(self):
        url = _provider().get_auth_url(REDIRECT, "s", code_verifier="v" * 43)
        assert "scope=tweet.read%20tweet.write%20users.read%20offline.access%20media.write" in url

    def test_challenge_matches_rfc_7636_vector(self):
        # RFC 7636 Appendix B: X uses standard S256, not TikTok's hex digest.
        assert (
            pkce_code_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")
            == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
        )

    def test_refuses_without_a_verifier(self):
        with pytest.raises(OAuthError, match="PKCE"):
            _provider().get_auth_url(REDIRECT, "s")

    def test_refuses_without_app_credentials(self):
        with pytest.raises(OAuthError, match="not configured"):
            XProvider({"client_id": "", "client_secret": ""}).get_auth_url(REDIRECT, "s", code_verifier="v" * 43)


class TestExchangeCode:
    @patch.object(XProvider, "_request")
    def test_exchanges_code_with_basic_auth_and_verifier(self, mock_request):
        mock_request.return_value = _response(
            {
                "token_type": "bearer",
                "expires_in": 7200,
                "access_token": "access-1",
                "scope": "tweet.read tweet.write users.read offline.access media.write",
                "refresh_token": "refresh-1",
            }
        )

        tokens = _provider().exchange_code("auth-code", REDIRECT, code_verifier="the-verifier")

        args, kwargs = mock_request.call_args
        assert args == ("POST", TOKEN_URL)
        assert kwargs["headers"]["Authorization"] == _expected_basic()
        assert kwargs["data"] == {
            "grant_type": "authorization_code",
            "code": "auth-code",
            "redirect_uri": REDIRECT,
            "code_verifier": "the-verifier",
            "client_id": "x-client-id",
        }
        # The confidential-client secret goes in the Basic header only.
        assert "client_secret" not in kwargs["data"]
        assert tokens.access_token == "access-1"
        assert tokens.refresh_token == "refresh-1"
        assert tokens.expires_in == 7200
        assert "offline.access" in tokens.scope

    @patch.object(XProvider, "_request")
    def test_body_without_access_token_is_an_oauth_error(self, mock_request):
        mock_request.return_value = _response({"error": "invalid_request"})
        with pytest.raises(OAuthError):
            _provider().exchange_code("auth-code", REDIRECT, code_verifier="v")

    def test_refuses_without_a_verifier(self):
        with pytest.raises(OAuthError, match="PKCE"):
            _provider().exchange_code("auth-code", REDIRECT)


class TestRefreshToken:
    @patch.object(XProvider, "_request")
    def test_refresh_returns_the_rotated_refresh_token(self, mock_request):
        mock_request.return_value = _response(
            {"token_type": "bearer", "expires_in": 7200, "access_token": "access-2", "refresh_token": "refresh-2"}
        )

        tokens = _provider().refresh_token("refresh-1")

        args, kwargs = mock_request.call_args
        assert args == ("POST", TOKEN_URL)
        assert kwargs["headers"]["Authorization"] == _expected_basic()
        assert kwargs["data"]["grant_type"] == "refresh_token"
        assert kwargs["data"]["refresh_token"] == "refresh-1"
        assert tokens.access_token == "access-2"
        assert tokens.refresh_token == "refresh-2"
        assert tokens.expires_in == 7200

    @pytest.mark.django_db
    @patch.object(XProvider, "_request")
    def test_account_refresh_persists_the_rotated_refresh_token(self, mock_request, organization):
        """X invalidates the old refresh token, so the new one must be stored."""
        from apps.social_accounts.models import SocialAccount
        from apps.workspaces.models import Workspace

        workspace = Workspace.objects.create(name="WS", organization=organization)
        account = SocialAccount.objects.create(
            workspace=workspace,
            platform="x",
            account_platform_id="42",
            account_name="Brand",
            oauth_access_token="access-1",
            oauth_refresh_token="refresh-1",
        )
        mock_request.return_value = _response(
            {"expires_in": 7200, "access_token": "access-2", "refresh_token": "refresh-2"}
        )

        account.refresh_oauth_token(_provider(), enqueue_backfill=False)

        account.refresh_from_db()
        assert account.oauth_access_token == "access-2"
        assert account.oauth_refresh_token == "refresh-2"
        assert account.token_expires_at is not None


class TestGetProfile:
    @patch.object(XProvider, "_request")
    def test_reads_users_me(self, mock_request):
        mock_request.return_value = _response(
            {
                "data": {
                    "id": "2244994945",
                    "name": "Brand Name",
                    "username": "brand",
                    "profile_image_url": "https://pbs.twimg.com/profile_images/1/a_normal.jpg",
                    "public_metrics": {"followers_count": 1234, "following_count": 5},
                }
            }
        )

        profile = _provider().get_profile("tok")

        args, kwargs = mock_request.call_args
        assert args == ("GET", f"{API_BASE}/users/me")
        assert kwargs["access_token"] == "tok"
        assert kwargs["params"] == {"user.fields": "profile_image_url,public_metrics,username,name"}
        assert profile.platform_id == "2244994945"
        assert profile.name == "Brand Name"
        assert profile.handle == "brand"
        assert profile.avatar_url.endswith("a_normal.jpg")
        assert profile.follower_count == 1234

    @patch.object(XProvider, "_request")
    def test_missing_user_is_an_error_not_a_blank_account(self, mock_request):
        mock_request.return_value = _response({"errors": [{"message": "nope"}]})
        with pytest.raises(APIError):
            _provider().get_profile("tok")

    @patch.object(XProvider, "_request")
    def test_validate_token_is_the_profile_read(self, mock_request):
        mock_request.return_value = _response({"data": {"id": "1", "username": "u"}})
        assert _provider().validate_token("tok") is True


# ---------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------


def _router(routes: dict):
    """A ``_request`` side effect answering by (method, url)."""
    calls = []

    def handler(method, url, **kwargs):
        calls.append((method, url, kwargs))
        key = (method, url)
        if key not in routes:
            raise AssertionError(f"unexpected request {method} {url}")
        answer = routes[key]
        if isinstance(answer, list):
            return answer.pop(0)
        return answer

    handler.calls = calls  # type: ignore[attr-defined]
    return handler


class TestPublishText:
    @patch.object(XProvider, "_request")
    def test_text_only_post(self, mock_request):
        mock_request.return_value = _response({"data": {"id": "1890", "text": "Hello"}})

        result = _provider(username="brand").publish_post("tok", PublishContent(text="Hello"))

        args, kwargs = mock_request.call_args
        assert args == ("POST", f"{API_BASE}/tweets")
        assert kwargs["access_token"] == "tok"
        assert kwargs["json"] == {"text": "Hello"}
        assert result.platform_post_id == "1890"
        assert result.url == "https://x.com/brand/status/1890"

    @patch.object(XProvider, "_request")
    def test_url_falls_back_when_the_handle_is_unknown(self, mock_request):
        mock_request.return_value = _response({"data": {"id": "1890"}})
        result = _provider().publish_post("tok", PublishContent(text="Hello"))
        assert result.url == "https://x.com/i/web/status/1890"

    @patch.object(XProvider, "_request")
    def test_over_length_is_refused_before_any_request(self, mock_request):
        with pytest.raises(PublishError) as excinfo:
            _provider().publish_post("tok", PublishContent(text="a" * 281))
        assert excinfo.value.retryable is False
        assert "281" in str(excinfo.value)
        mock_request.assert_not_called()

    @patch.object(XProvider, "_request")
    def test_a_long_link_counts_as_23(self, mock_request):
        mock_request.return_value = _response({"data": {"id": "1"}})
        text = "a" * 250 + " https://example.com/" + "p" * 200  # 451 typed, 274 weighted
        assert weighted_length(text) == 274
        _provider().publish_post("tok", PublishContent(text=text))
        assert mock_request.call_args.kwargs["json"] == {"text": text}

    @patch.object(XProvider, "_request")
    def test_nothing_to_post_is_refused(self, mock_request):
        with pytest.raises(PublishError) as excinfo:
            _provider().publish_post("tok", PublishContent(text="   "))
        assert excinfo.value.retryable is False
        mock_request.assert_not_called()

    @patch.object(XProvider, "_request")
    def test_no_post_id_is_not_retried_blind(self, mock_request):
        """A 2xx without an id may still be a live post; retrying risks a duplicate."""
        mock_request.return_value = _response({"data": {}})
        with pytest.raises(PublishError) as excinfo:
            _provider().publish_post("tok", PublishContent(text="Hello"))
        assert excinfo.value.retryable is False
        assert "Check the account" in str(excinfo.value)


class TestPublishMedia:
    def _write(self, tmp_path, name, data):
        path = tmp_path / name
        path.write_bytes(data)
        return str(path)

    def test_images_go_through_initialize_append_finalize(self, tmp_path):
        png = self._write(tmp_path, "one.png", PNG)
        # Extension says PNG, bytes say JPEG: the bytes win.
        jpeg = self._write(tmp_path, "two.png", JPEG)
        router = _router(
            {
                ("POST", f"{API_BASE}/media/upload/initialize"): [
                    _response({"data": {"id": "m1", "media_key": "3_m1"}}),
                    _response({"data": {"id": "m2", "media_key": "3_m2"}}),
                ],
                ("POST", f"{API_BASE}/media/upload/m1/append"): _response(None),
                ("POST", f"{API_BASE}/media/upload/m2/append"): _response(None),
                ("POST", f"{API_BASE}/media/upload/m1/finalize"): _response({"data": {"id": "m1"}}),
                ("POST", f"{API_BASE}/media/upload/m2/finalize"): _response({"data": {"id": "m2"}}),
                ("POST", f"{API_BASE}/tweets"): _response({"data": {"id": "77"}}),
            }
        )
        content = PublishContent(
            text="Two pictures",
            media_files=[png, jpeg],
            media_urls=["https://cdn/one.png", "https://cdn/two.png"],
            media_types=["image", "image"],
            post_type=PostType.IMAGE,
        )

        with patch.object(XProvider, "_request", side_effect=router):
            result = _provider().publish_post("tok", content)

        sequence = [(method, url.removeprefix(API_BASE)) for method, url, _ in router.calls]
        assert sequence == [
            ("POST", "/media/upload/initialize"),
            ("POST", "/media/upload/m1/append"),
            ("POST", "/media/upload/m1/finalize"),
            ("POST", "/media/upload/initialize"),
            ("POST", "/media/upload/m2/append"),
            ("POST", "/media/upload/m2/finalize"),
            ("POST", "/tweets"),
        ]
        init_one = router.calls[0][2]
        assert init_one["json"] == {"media_type": "image/png", "total_bytes": len(PNG), "media_category": "tweet_image"}
        assert router.calls[3][2]["json"]["media_type"] == "image/jpeg"
        append = router.calls[1][2]
        assert append["data"] == {"segment_index": "0"}
        name, payload, mime = append["files"]["media"]
        assert (name, payload, mime) == ("one.png", PNG, "image/png")
        assert router.calls[-1][2]["json"] == {"text": "Two pictures", "media": {"media_ids": ["m1", "m2"]}}
        assert result.platform_post_id == "77"

    def test_video_waits_for_processing(self, tmp_path):
        video = self._write(tmp_path, "clip.mp4", MP4)
        router = _router(
            {
                ("POST", f"{API_BASE}/media/upload/initialize"): _response({"data": {"id": "v1"}}),
                ("POST", f"{API_BASE}/media/upload/v1/append"): _response(None),
                ("POST", f"{API_BASE}/media/upload/v1/finalize"): _response(
                    {"data": {"id": "v1", "processing_info": {"state": "pending", "check_after_secs": 1}}}
                ),
                ("GET", f"{API_BASE}/media/upload"): [
                    _response(
                        {"data": {"id": "v1", "processing_info": {"state": "in_progress", "check_after_secs": 2}}}
                    ),
                    _response({"data": {"id": "v1", "processing_info": {"state": "succeeded"}}}),
                ],
                ("POST", f"{API_BASE}/tweets"): _response({"data": {"id": "88"}}),
            }
        )
        content = PublishContent(text="", media_files=[video], media_types=["video"], post_type=PostType.VIDEO)

        with patch.object(XProvider, "_request", side_effect=router), patch("providers.x.time.sleep") as sleep:
            result = _provider().publish_post("tok", content)

        assert router.calls[0][2]["json"]["media_category"] == "tweet_video"
        assert router.calls[0][2]["json"]["media_type"] == "video/mp4"
        status_calls = [kwargs for method, _url, kwargs in router.calls if method == "GET"]
        assert [c["params"] for c in status_calls] == [{"command": "STATUS", "media_id": "v1"}] * 2
        assert [c.args[0] for c in sleep.call_args_list] == [1.0, 2.0]
        # Media without text: the text field is left out rather than sent empty.
        assert router.calls[-1][2]["json"] == {"media": {"media_ids": ["v1"]}}
        assert result.platform_post_id == "88"

    def test_gif_uses_the_gif_category(self, tmp_path):
        gif = self._write(tmp_path, "loop.gif", GIF)
        router = _router(
            {
                ("POST", f"{API_BASE}/media/upload/initialize"): _response({"data": {"id": "g1"}}),
                ("POST", f"{API_BASE}/media/upload/g1/append"): _response(None),
                ("POST", f"{API_BASE}/media/upload/g1/finalize"): _response({"data": {"id": "g1"}}),
                ("POST", f"{API_BASE}/tweets"): _response({"data": {"id": "9"}}),
            }
        )
        with patch.object(XProvider, "_request", side_effect=router):
            _provider().publish_post("tok", PublishContent(text="gif", media_files=[gif], media_types=["gif"]))
        assert router.calls[0][2]["json"]["media_category"] == "tweet_gif"

    def test_failed_processing_is_not_retried(self, tmp_path):
        video = self._write(tmp_path, "clip.mp4", MP4)
        router = _router(
            {
                ("POST", f"{API_BASE}/media/upload/initialize"): _response({"data": {"id": "v1"}}),
                ("POST", f"{API_BASE}/media/upload/v1/append"): _response(None),
                ("POST", f"{API_BASE}/media/upload/v1/finalize"): _response(
                    {"data": {"processing_info": {"state": "failed", "error": {"message": "Unsupported codec"}}}}
                ),
            }
        )
        with patch.object(XProvider, "_request", side_effect=router), pytest.raises(PublishError) as excinfo:
            _provider().publish_post("tok", PublishContent(text="v", media_files=[video], media_types=["video"]))
        assert excinfo.value.retryable is False
        assert "Unsupported codec" in str(excinfo.value)

    def test_large_video_is_appended_in_segments(self, tmp_path, monkeypatch):
        monkeypatch.setattr("providers.x.SEGMENT_BYTES", 32)
        video = self._write(tmp_path, "clip.mp4", MP4)  # 80 bytes → 3 segments
        router = _router(
            {
                ("POST", f"{API_BASE}/media/upload/initialize"): _response({"data": {"id": "v1"}}),
                ("POST", f"{API_BASE}/media/upload/v1/append"): _response(None),
                ("POST", f"{API_BASE}/media/upload/v1/finalize"): _response({"data": {"id": "v1"}}),
                ("POST", f"{API_BASE}/tweets"): _response({"data": {"id": "5"}}),
            }
        )
        with patch.object(XProvider, "_request", side_effect=router):
            _provider().publish_post("tok", PublishContent(text="v", media_files=[video], media_types=["video"]))
        appends = [kwargs for _m, url, kwargs in router.calls if url.endswith("/append")]
        assert [a["data"]["segment_index"] for a in appends] == ["0", "1", "2"]
        assert b"".join(a["files"]["media"][1] for a in appends) == MP4

    @pytest.mark.parametrize(
        "files",
        [
            [("a.png", PNG)] * 5,  # more than four images
            [("a.png", PNG), ("b.mp4", MP4)],  # image + video
            [("a.mp4", MP4), ("b.mp4", MP4)],  # two videos
            [("a.gif", GIF), ("b.png", PNG)],  # GIF + image
        ],
    )
    def test_media_mixes_x_refuses_are_caught_before_uploading(self, tmp_path, files):
        paths = [self._write(tmp_path, f"{i}-{name}", data) for i, (name, data) in enumerate(files)]
        with patch.object(XProvider, "_request") as mock_request, pytest.raises(PublishError) as excinfo:
            _provider().publish_post("tok", PublishContent(text="hi", media_files=paths))
        assert str(excinfo.value) == MEDIA_MIX_MESSAGE
        assert excinfo.value.retryable is False
        mock_request.assert_not_called()

    def test_unsupported_file_type_is_refused(self, tmp_path):
        pdf = self._write(tmp_path, "doc.pdf", b"%PDF-1.7" + b"\x00" * 32)
        with patch.object(XProvider, "_request") as mock_request, pytest.raises(PublishError) as excinfo:
            _provider().publish_post("tok", PublishContent(text="hi", media_files=[pdf], media_types=["document"]))
        assert excinfo.value.retryable is False
        mock_request.assert_not_called()


class TestDeletePost:
    @patch.object(XProvider, "_request")
    def test_delete(self, mock_request):
        mock_request.return_value = _response({"data": {"deleted": True}})
        assert _provider().delete_post("tok", "1890") is True
        args, kwargs = mock_request.call_args
        assert args == ("DELETE", f"{API_BASE}/tweets/1890")
        assert kwargs["access_token"] == "tok"


# ---------------------------------------------------------------------------
# Error mapping (real _request → _error_for_response path)
# ---------------------------------------------------------------------------


class TestCreditsDepleted:
    BODY = {
        "title": "CreditsDepleted",
        "detail": "Your enrolled account does not have any credits to fulfill this request.",
        "type": "https://api.twitter.com/2/problems/credits",
    }

    def test_402_on_publish_is_a_non_retryable_publish_error_with_friendly_text(self, mock_transport):
        mock_transport(lambda request: httpx.Response(402, json=self.BODY))

        with pytest.raises(PublishError) as excinfo:
            _provider().publish_post("tok", PublishContent(text="Hello"))

        assert type(excinfo.value) is PublishError
        assert excinfo.value.retryable is False
        assert str(excinfo.value) == CREDITS_DEPLETED_MESSAGE
        assert excinfo.value.raw_response == self.BODY
        # Exactly what the composer will show: error_messages passes our text through.
        from apps.social_accounts.error_messages import friendly_publish_error

        assert friendly_publish_error(excinfo.value) == (
            "X rejected the post: the X developer account has no API credits. Add credits at console.x.com."
        )

    def test_402_from_any_call_is_a_non_retryable_api_error(self, mock_transport):
        mock_transport(lambda request: httpx.Response(402, json=self.BODY))

        with pytest.raises(APIError) as excinfo:
            _provider().get_profile("tok")

        assert excinfo.value.status_code == 402
        assert excinfo.value.retryable is False
        assert str(excinfo.value) == CREDITS_DEPLETED_MESSAGE

    def test_credits_problem_is_recognised_by_its_title_too(self):
        request = httpx.Request("POST", f"{API_BASE}/tweets")
        exc = _provider()._error_for_response(httpx.Response(403, json=self.BODY, request=request))
        assert isinstance(exc, APIError)
        assert exc.status_code == 403
        assert exc.retryable is False
        assert str(exc) == CREDITS_DEPLETED_MESSAGE

    def test_credits_refusal_during_media_upload_is_reported_the_same_way(self, mock_transport, tmp_path):
        image = tmp_path / "a.png"
        image.write_bytes(PNG)
        mock_transport(lambda request: httpx.Response(402, json=self.BODY))
        with pytest.raises(PublishError) as excinfo:
            _provider().publish_post("tok", PublishContent(text="hi", media_files=[str(image)]))
        assert str(excinfo.value) == CREDITS_DEPLETED_MESSAGE
        assert excinfo.value.retryable is False


class TestRateLimited:
    NOW = datetime(2026, 10, 2, 12, 0, 0, tzinfo=UTC)

    def _429(self, headers):
        request = httpx.Request("POST", f"{API_BASE}/tweets")
        return httpx.Response(429, json={"title": "Too Many Requests", "status": 429}, headers=headers, request=request)

    def test_429_carries_the_reset_time_from_x_rate_limit_reset(self):
        reset = int((self.NOW + timedelta(minutes=12)).timestamp())
        exc = _provider()._error_for_response(
            self._429({"x-rate-limit-limit": "100", "x-rate-limit-remaining": "0", "x-rate-limit-reset": str(reset)}),
            now=self.NOW,
        )

        assert isinstance(exc, RateLimitError)
        assert isinstance(exc, QuotaExceededError)
        assert exc.resets_at == datetime.fromtimestamp(reset, UTC)
        assert exc.retry_after == 12 * 60
        assert exc.status_code == 429
        assert exc.retryable is True

    def test_retry_after_is_the_fallback(self):
        exc = _provider()._error_for_response(self._429({"retry-after": "30"}), now=self.NOW)
        assert isinstance(exc, RateLimitError)
        assert exc.retry_after == 30
        assert exc.resets_at == self.NOW + timedelta(seconds=30)

    def test_no_headers_leaves_the_reset_unknown(self):
        exc = _provider()._error_for_response(self._429({}), now=self.NOW)
        assert isinstance(exc, RateLimitError)
        assert exc.resets_at is None
        assert exc.retry_after is None

    def test_publish_lets_the_rate_limit_through_for_the_engine_to_reschedule(self, mock_transport):
        reset = int((datetime.now(UTC) + timedelta(minutes=5)).timestamp())
        mock_transport(
            lambda request: httpx.Response(
                429, json={"title": "Too Many Requests"}, headers={"x-rate-limit-reset": str(reset)}
            )
        )
        with pytest.raises(QuotaExceededError) as excinfo:
            _provider().publish_post("tok", PublishContent(text="Hello"))
        assert excinfo.value.retryable is True
        assert excinfo.value.resets_at == datetime.fromtimestamp(reset, UTC)


class TestOtherRefusals:
    def test_duplicate_post_surfaces_xs_own_sentence(self, mock_transport):
        mock_transport(
            lambda request: httpx.Response(
                403,
                json={
                    "detail": "You are not allowed to create a Tweet with duplicate content.",
                    "type": "about:blank",
                    "title": "Forbidden",
                    "status": 403,
                },
            )
        )
        with pytest.raises(PublishError) as excinfo:
            _provider().publish_post("tok", PublishContent(text="Hello again"))
        assert excinfo.value.retryable is False
        assert (
            str(excinfo.value) == "X rejected the post: You are not allowed to create a Tweet with duplicate content."
        )

    def test_validation_error_prefers_the_specific_message(self, mock_transport):
        mock_transport(
            lambda request: httpx.Response(
                400,
                json={
                    "errors": [{"message": "Your media IDs are invalid."}],
                    "title": "Invalid Request",
                    "detail": "One or more parameters to your request was invalid.",
                },
            )
        )
        with pytest.raises(PublishError, match="Your media IDs are invalid."):
            _provider().publish_post("tok", PublishContent(text="Hello"))

    def test_401_stays_an_api_error_so_reconnect_copy_applies(self, mock_transport):
        mock_transport(lambda request: httpx.Response(401, json={"title": "Unauthorized", "status": 401}))
        with pytest.raises(APIError) as excinfo:
            _provider().publish_post("tok", PublishContent(text="Hello"))
        assert type(excinfo.value) is APIError
        assert excinfo.value.status_code == 401

    def test_server_error_stays_retryable(self, mock_transport):
        mock_transport(lambda request: httpx.Response(503, text="upstream unavailable"))
        with pytest.raises(APIError) as excinfo:
            _provider().publish_post("tok", PublishContent(text="Hello"))
        assert excinfo.value.status_code == 503
        assert excinfo.value.retryable is True


# ---------------------------------------------------------------------------
# Weighted length
# ---------------------------------------------------------------------------


class TestWeightedLength:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("", 0),
            ("hello world", 11),
            ("a" * 280, 280),
            # Every link is 23, however long or short it is typed.
            ("https://example.com/" + "x" * 100, 23),
            ("http://a.co", 23),
            ("www.example.com/page", 23),
            ("HTTPS://EXAMPLE.COM", 23),
            ("read https://a.example/x and https://b.example/y", 5 + 23 + 5 + 23),
            # Sentence punctuation after a link is not part of it.
            ("see https://example.com.", 4 + 23 + 1),
            ("(https://example.com)", 1 + 23 + 1),
            # CJK counts double; Latin, accents and typographic punctuation single.
            ("日本語", 6),
            ("café — “quoted”", 15),
            # An emoji sequence counts as one emoji.
            ("❤️", 2),
            ("👍🏽", 2),
            ("👨‍👩‍👧", 2),
            ("🇺🇸", 2),
            ("1️⃣", 2),
            # A joiner between letters joins nothing.
            ("क्‍ष", 3),
            # NFC: a decomposed accent counts once.
            ("é", 1),
        ],
    )
    def test_counts(self, text, expected):
        assert weighted_length(text) == expected

    def test_the_limit_boundary(self):
        assert weighted_length("a" * 257 + " https://example.com/long/path") == 281
        assert weighted_length("a" * 256 + " https://example.com/long/path") == 280

    def test_caption_wire_length_uses_the_weighting_for_x_only(self):
        text = "日本 https://example.com/" + "x" * 40
        assert caption_wire_length("x", text) == 4 + 1 + 23
        assert caption_wire_length("threads", text) == len(text)

    def test_the_account_limit_compares_like_with_like(self):
        from apps.social_accounts.models import SocialAccount

        account = SocialAccount(platform="x")
        assert account.char_limit == 280
        assert account.caption_wire_length("x" * 200 + " https://example.com/" + "y" * 200) == 224
        assert account.field_config["supports_first_comment"] is False
