"""The built-in steps every spec uses: sign in, reopen the login form, slow the team, a portal link,
and what the network guard refused."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from importlib import import_module
from typing import Any

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
from django.core.cache import cache
from django.utils import timezone

from .. import fakes, mocks, netguard, seed, worker
from ..registry import PayloadError, fixture, optional_number, probe, require_number, require_str

_LOOPBACK_ADDRESSES = ("127.0.0.1", "::1")


@fixture("session")
def session(payload: dict[str, Any]) -> dict[str, Any]:
    """Sign a seeded person in without the login form: ``{"role": ...}`` or ``{"email": ...}``.

    The session is created on the server, as Django's test client does for ``force_login``; the
    browser only receives the cookie. Only golden path 1 posts the form (it is rate limited).
    """
    from apps.accounts.models import User

    if "role" in payload:
        role = require_str(payload, "role")
        if role not in seed.USERS:
            raise PayloadError(f"Unknown role {role!r}; use one of {', '.join(seed.USERS)}.")
        email = seed.USERS[role][0]
    elif "email" in payload:
        email = require_str(payload, "email")
    else:
        raise PayloadError("Send a 'role' or an 'email'.")
    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if user is None:
        raise PayloadError(f"No active user with the email {email!r}.")

    engine = import_module(settings.SESSION_ENGINE)
    store = engine.SessionStore()
    store[SESSION_KEY] = user._meta.pk.value_to_string(user)
    store[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
    store[HASH_SESSION_KEY] = user.get_session_auth_hash()
    store.save()
    return {
        "cookie": {"name": settings.SESSION_COOKIE_NAME, "value": store.session_key},
        "user": {"id": str(user.pk), "email": user.email},
    }


@fixture("reset_login_limits")
def reset_login_limits(payload: dict[str, Any]) -> dict[str, Any]:
    """Forget the login rate limits for loopback: the middleware's 10 a minute and allauth's own."""
    from allauth.core.internal.ratelimit import truncate_ip
    from django.contrib.sites.models import Site

    from apps.accounts.models import User

    keys = [f"auth_ratelimit:{hashlib.md5(address.encode()).hexdigest()}" for address in _LOOPBACK_ADDRESSES]
    actions = list(getattr(settings, "ACCOUNT_RATE_LIMITS", {}) or {})
    for address in _LOOPBACK_ADDRESSES:
        keys += [f"allauth:rl:{action}:ip:{truncate_ip(address)}" for action in actions]
    domain = Site.objects.get_current().domain
    for email in User.objects.values_list("email", flat=True):
        digest = hashlib.sha256(f"{domain}:{email.lower()}".encode()).hexdigest()
        keys += [f"allauth:rl:{action}:{digest}" for action in actions]
    cleared = sum(1 for key in keys if cache.delete(key))
    return {"cleared": cleared}


@fixture("set_agent_delay")
def set_agent_delay(payload: dict[str, Any]) -> dict[str, Any]:
    """Make every fake agent turn take ``seconds`` (0 to 60), so a test can watch the team work."""
    seconds = require_number(payload, "seconds")
    try:
        fakes.set_agent_delay(seconds)
    except ValueError as exc:
        raise PayloadError(str(exc)) from exc
    return {"seconds": fakes.agent_delay()}


@fixture("magic_link")
def magic_link(payload: dict[str, Any]) -> dict[str, Any]:
    """A fresh portal link for a client of a workspace: ``{"email", "workspace_id"}`` -> ``{"url"}``."""
    from apps.accounts.models import User
    from apps.client_portal.models import MagicLinkToken
    from apps.members.models import WorkspaceMembership

    email = require_str(payload, "email")
    workspace_id = require_str(payload, "workspace_id")
    user = User.objects.filter(email__iexact=email).first()
    membership = (
        WorkspaceMembership.objects.filter(
            user=user, workspace_id=workspace_id, workspace_role=WorkspaceMembership.WorkspaceRole.CLIENT
        ).first()
        if user is not None
        else None
    )
    if membership is None:
        raise PayloadError(f"{email!r} is not a client of workspace {workspace_id}.")
    token = MagicLinkToken.objects.create(
        user=membership.user, workspace_id=membership.workspace_id, expires_at=timezone.now() + timedelta(days=1)
    )
    return {"url": f"/portal/{token.token}/"}


@probe("refused_network")
def refused_network(params: dict[str, Any]) -> dict[str, Any]:
    """What the socket guard refused and what the mock transport would not answer (``?since=<epoch>``)."""
    since = optional_number(params, "since")
    refused = netguard.refused(since)
    unanswered = mocks.unanswered(since)
    hosts = sorted({str(item["host"]) for item in [*refused, *unanswered] if item.get("host")})
    return {"hosts": hosts, "refused": refused, "unanswered": unanswered}


@probe("worker")
def worker_status(params: dict[str, Any]) -> dict[str, Any]:
    """Whether the in-process worker is running, how many tasks it ran, and any error that stopped it."""
    return worker.status()
