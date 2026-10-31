"""Provider HTTP for the e2e server: the few platform calls the browser paths make, and nothing else.

Every ``httpx.Client`` (and ``AsyncClient``) the process creates after :func:`install` sends through
one ``httpx.MockTransport`` (the pattern of ``tests/providers/test_x.py``), whatever transport, mounts
or proxy the caller asked for. It answers:

* X: the OAuth token exchange and ``GET /2/users/me`` (connecting an account);
* Facebook: a reply to a comment (``POST /<comment>/comments``, the inbox's *Send reply*).

Every other request is refused with ``httpx.ConnectError``, as an outage would be, and recorded
(method, host and path; never the query string, and with credential-like path segments redacted) for
the ``refused_network`` probe.

Google sign-in goes through allauth, which uses ``requests``, so its two network steps are replaced
the way ``apps/accounts/tests/test_google_signin.py`` replaces them, keyed by the authorization
``code`` the browser brings back: a test registers a profile for a code with
:func:`register_google_profile` and routes the Google authorize URL to the callback with that code.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import httpx
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client, OAuth2Error

from providers import facebook as facebook_provider
from providers import x as x_provider

Setter = Callable[[Any, str, Any], None]

X_TOKEN: dict[str, Any] = {
    "access_token": "e2e-x-access-token",
    "refresh_token": "e2e-x-refresh-token",
    "expires_in": 7200,
    "token_type": "bearer",
    "scope": " ".join(x_provider.SCOPES),
}
X_USER: dict[str, Any] = {
    "id": "4400000001",
    "username": "neopolis_e2e",
    "name": "Neopolis E2E",
    "public_metrics": {"followers_count": 1500},
}

_MAX_RECORDS = 500
_lock = threading.Lock()
_answered: list[dict[str, Any]] = []
_unanswered: list[dict[str, Any]] = []
GOOGLE_PROFILES: dict[str, dict[str, Any]] = {}
_GOOGLE_TOKEN_PREFIX = "e2e-google:"
_SECRET_LIKE = re.compile(r"[^/]*:[^/]*|[A-Za-z0-9_\-.~]{40,}")

Responder = Callable[[httpx.Request, re.Match[str]], httpx.Response]


def _route(
    method: str, url: str, responder: Responder, *, then: str = ""
) -> tuple[str, str, re.Pattern[str], Responder]:
    """``url`` is literal (taken from the provider module); ``then`` is a pattern for the rest of the path."""
    parts = urlsplit(url)
    return method, parts.hostname or "", re.compile(re.escape(parts.path) + then), responder


_ROUTES = [
    _route("POST", x_provider.TOKEN_URL, lambda request, match: httpx.Response(200, json=X_TOKEN)),
    _route("GET", f"{x_provider.API_BASE}/users/me", lambda request, match: httpx.Response(200, json={"data": X_USER})),
    _route(
        "POST",
        facebook_provider.BASE_URL,
        lambda request, match: httpx.Response(200, json={"id": f"e2e-reply-{match['target']}"}),
        then="/(?P<target>[^/]+)/comments",
    ),
]


def _safe_url(scheme: str, host: str, path: str) -> str:
    segments = ["<redacted>" if _SECRET_LIKE.fullmatch(part) else part for part in path.split("/")]
    return f"{scheme}://{host}{'/'.join(segments)}"


def _note(records: list[dict[str, Any]], method: str, scheme: str, host: str, path: str) -> None:
    with _lock:
        records.append({"method": method, "host": host, "url": _safe_url(scheme, host, path), "at": time.time()})
        del records[:-_MAX_RECORDS]


def handler(request: httpx.Request) -> httpx.Response:
    url = request.url
    for method, host, pattern, respond in _ROUTES:
        match = pattern.fullmatch(url.path)
        if request.method == method and url.host == host and match:
            _note(_answered, request.method, url.scheme, url.host, url.path)
            return respond(request, match)
    _note(_unanswered, request.method, url.scheme, url.host, url.path)
    raise httpx.ConnectError(
        f"e2e: no mocked answer for {request.method} {url.host}; connections outside this machine are off.",
        request=request,
    )


TRANSPORT = httpx.MockTransport(handler)
_RealClient = httpx.Client
_RealAsyncClient = httpx.AsyncClient


class MockedClient(_RealClient):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        for key in ("transport", "mounts", "proxy"):
            kwargs.pop(key, None)
        super().__init__(*args, transport=TRANSPORT, **kwargs)


class MockedAsyncClient(_RealAsyncClient):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        for key in ("transport", "mounts", "proxy"):
            kwargs.pop(key, None)
        super().__init__(*args, transport=TRANSPORT, **kwargs)


# ---------------------------------------------------------------------------
# Google sign-in, keyed by the authorization code
# ---------------------------------------------------------------------------


def register_google_profile(code: str, profile: dict[str, Any]) -> None:
    """What Google says about the person who comes back with ``code`` (``sub`` and ``email`` at least)."""
    if not code or not isinstance(profile.get("sub"), str) or not isinstance(profile.get("email"), str):
        raise ValueError("A Google profile needs a code, a 'sub' and an 'email'.")
    GOOGLE_PROFILES[code] = {"email_verified": True, **profile}


def _google_token_url() -> str:
    return str(getattr(GoogleOAuth2Adapter, "access_token_url", "https://oauth2.googleapis.com/token"))


def _google_access_token(
    self: OAuth2Client, code: str, pkce_code_verifier: str | None = None, extra_data: Any = None
) -> dict[str, Any]:
    if code not in GOOGLE_PROFILES:
        parts = urlsplit(_google_token_url())
        _note(_unanswered, "POST", parts.scheme, parts.hostname or "", parts.path)
        raise OAuth2Error("e2e: no Google profile is registered for this authorization code.")
    return {"access_token": f"{_GOOGLE_TOKEN_PREFIX}{code}", "expires_in": 3599, "token_type": "Bearer"}


def _google_complete_login(self: GoogleOAuth2Adapter, request: Any, app: Any, token: Any, **kwargs: Any) -> Any:
    code = str(getattr(token, "token", "")).removeprefix(_GOOGLE_TOKEN_PREFIX)
    profile = GOOGLE_PROFILES.get(code)
    if profile is None:
        raise OAuth2Error("e2e: no Google profile is registered for this authorization code.")
    return self.get_provider().sociallogin_from_response(request, dict(profile))


# ---------------------------------------------------------------------------
# Installing, and what the probes read
# ---------------------------------------------------------------------------


def install(setter: Setter = setattr) -> None:
    """Route the process's provider HTTP through the mock. Tests pass ``monkeypatch.setattr``."""
    setter(httpx, "Client", MockedClient)
    setter(httpx, "AsyncClient", MockedAsyncClient)
    setter(OAuth2Client, "get_access_token", _google_access_token)
    setter(GoogleOAuth2Adapter, "complete_login", _google_complete_login)


def answered(since: float | None = None) -> list[dict[str, Any]]:
    with _lock:
        return [dict(item) for item in _answered if since is None or item["at"] >= since]


def unanswered(since: float | None = None) -> list[dict[str, Any]]:
    with _lock:
        return [dict(item) for item in _unanswered if since is None or item["at"] >= since]


def reset() -> None:
    with _lock:
        _answered.clear()
        _unanswered.clear()
    GOOGLE_PROFILES.clear()
