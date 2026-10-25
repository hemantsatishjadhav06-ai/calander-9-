"""Golden paths 1 (sign in with email and with Google) and 11 (workspace isolation).

Path 1 posts the real login form and goes through allauth's Google flow; these steps register the
profile Google would return, make a fresh member of workspace A for the "existing email" case, and
read back the sessions and accounts the sign-in left in the database.

Path 11 asks the URL resolver for every pattern that takes a ``workspace_id`` (so a new page is
covered the day it is added), makes rows in workspace B for the object URLs, and reads those rows
back so a test can show that a refused request changed nothing.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.urls import URLPattern, URLResolver, get_resolver, resolve
from django.utils import timezone

from .. import mocks, seed
from ..registry import PayloadError, fixture, optional_str, probe, require_str

# ---------------------------------------------------------------------------
# Path 1: sign in
# ---------------------------------------------------------------------------

_WORKSPACE_ROLES = ("owner", "manager", "editor", "client")


def _user_by_email(email: str) -> Any:
    from apps.accounts.models import User

    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        raise PayloadError(f"No user with the email {email!r}.")
    return user


def _authenticated_sessions(user_id: str) -> list[str]:
    """The keys of the unexpired sessions signed in as ``user_id``."""
    from django.contrib.sessions.models import Session

    keys = []
    for session in Session.objects.filter(expire_date__gt=timezone.now()):
        if str(session.get_decoded().get(SESSION_KEY, "")) == user_id:
            keys.append(session.session_key)
    return keys


@fixture("google_profile")
def google_profile(payload: dict[str, Any]) -> dict[str, Any]:
    """What Google says about the next person to come back from it: ``{"email", "name"?}``.

    Returns the authorization ``code`` the test puts on the callback URL, and the Google ``sub``.
    """
    email = require_str(payload, "email")
    name = optional_str(payload, "name") or "Gia Google"
    token = uuid.uuid4().hex
    code = f"e2e-google-{token[:20]}"
    sub = str(int(token[:12], 16))
    given, _space, family = name.partition(" ")
    mocks.register_google_profile(
        code,
        {"sub": sub, "email": email, "email_verified": True, "name": name, "given_name": given, "family_name": family},
    )
    return {"code": code, "sub": sub, "email": email}


@fixture("member_of_a")
def member_of_a(payload: dict[str, Any]) -> dict[str, Any]:
    """A fresh person in workspace A who has signed in before: ``{"role"?}`` (default editor).

    The terms are accepted, A is where they land, and they have no workspace of their own.
    """
    from apps.members.models import OrgMembership, WorkspaceMembership
    from apps.workspaces.models import Workspace

    role = optional_str(payload, "role") or "editor"
    if role not in _WORKSPACE_ROLES:
        raise PayloadError(f"Unknown role {role!r}; use one of {', '.join(_WORKSPACE_ROLES)}.")
    workspace = Workspace.objects.get(pk=seed.WORKSPACE_A_ID)
    email = f"member-{uuid.uuid4().hex[:12]}@e2e.test"
    user = seed._person(email, "Mo Member")
    OrgMembership.objects.create(user=user, organization=workspace.organization, org_role="member")
    WorkspaceMembership.objects.create(user=user, workspace=workspace, workspace_role=role)
    user.last_workspace_id = workspace.pk
    user.save(update_fields=["last_workspace_id"])
    return {"id": str(user.pk), "email": user.email, "role": role}


@probe("session_user")
def session_user(params: dict[str, Any]) -> dict[str, Any]:
    """Who the session with this cookie value is signed in as: ``?key=`` -> ``{"exists", "user"}``."""
    from django.contrib.sessions.models import Session

    from apps.accounts.models import User

    key = require_str(params, "key")
    session = Session.objects.filter(session_key=key, expire_date__gt=timezone.now()).first()
    if session is None:
        return {"exists": False, "user": None}
    user_id = session.get_decoded().get(SESSION_KEY)
    user = User.objects.filter(pk=user_id).first() if user_id else None
    return {"exists": True, "user": {"id": str(user.pk), "email": user.email} if user else None}


@probe("auth_sessions")
def auth_sessions(params: dict[str, Any]) -> dict[str, Any]:
    """How many unexpired sessions are signed in as this person: ``?email=`` -> ``{"count"}``.

    With the session cookie's name, so a spec can find the cookie in the browser.
    """
    user = _user_by_email(require_str(params, "email"))
    return {"count": len(_authenticated_sessions(str(user.pk))), "cookie_name": settings.SESSION_COOKIE_NAME}


@probe("user_account")
def user_account(params: dict[str, Any]) -> dict[str, Any]:
    """A person's account as a sign-in left it: ``?email=``.

    ``users`` counts the accounts with that email (one, whether a Google sign-in made it or reused
    it); the rest describes that account: its Google links, the terms, its workspaces, the
    organisations it belongs to and its signed-in sessions.
    """
    from allauth.socialaccount.models import SocialAccount

    from apps.accounts.models import OAuthConnection, User
    from apps.members.models import OrgMembership, WorkspaceMembership

    email = require_str(params, "email")
    users = User.objects.filter(email__iexact=email)
    user = users.first()
    if user is None:
        return {"users": 0}
    memberships = WorkspaceMembership.objects.filter(user=user).select_related("workspace").order_by("workspace__name")
    org_memberships = OrgMembership.objects.filter(user=user).select_related("organization")
    return {
        "users": users.count(),
        "id": str(user.pk),
        "email": user.email,
        "name": user.name,
        "tos_accepted": user.tos_accepted_at is not None,
        "last_workspace_id": str(user.last_workspace_id) if user.last_workspace_id else None,
        "google_uids": sorted(SocialAccount.objects.filter(user=user, provider="google").values_list("uid", flat=True)),
        "google_connections": sorted(
            OAuthConnection.objects.filter(user=user, provider="google").values_list("provider_user_id", flat=True)
        ),
        "workspaces": [
            {"id": str(m.workspace_id), "name": m.workspace.name, "role": m.workspace_role} for m in memberships
        ],
        "organisations": [
            {
                "id": str(m.organization_id),
                "role": m.org_role,
                "timezone": m.organization.default_timezone,
            }
            for m in org_memberships
        ],
        "sessions": len(_authenticated_sessions(str(user.pk))),
    }


# ---------------------------------------------------------------------------
# Path 11: workspace isolation
# ---------------------------------------------------------------------------

#: A sample value per path converter, for the parts of a URL that are not an object the test names.
_SAMPLES = {"uuid": "00000000-0000-4000-8000-0000000000ff", "int": "1", "str": "e2e", "slug": "e2e", "path": "e2e"}
_PART = re.compile(r"<(?:(?P<converter>[^>:]+):)?(?P<name>[^>]+)>")


def _routes(patterns: list[Any], prefix: str = "", namespace: str = "") -> list[tuple[str, str]]:
    """``(route, name)`` for every pattern under ``patterns``, with include prefixes joined."""
    found: list[tuple[str, str]] = []
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            inner = ":".join(part for part in (namespace, pattern.namespace) if part)
            found += _routes(pattern.url_patterns, prefix + str(pattern.pattern), inner)
        elif isinstance(pattern, URLPattern):
            name = f"{namespace}:{pattern.name}" if namespace and pattern.name else pattern.name or ""
            found.append((prefix + str(pattern.pattern), name))
    return found


@probe("isolation_urls")
def isolation_urls(params: dict[str, Any]) -> dict[str, Any]:
    """Every URL pattern that takes a ``workspace_id``, filled in: ``?workspace_id=&<part>=<id>...``.

    Each other part of the path takes the value of the parameter with its name (``post_id``,
    ``brief_id``, ...) when the test sends one, and a sample of its type otherwise. Each URL comes
    back with its pattern's name and the parts that were the test's own objects (``objects``).
    """
    workspace_id = require_str(params, "workspace_id")
    objects = {key: str(value) for key, value in params.items() if key != "workspace_id"}
    urls = []
    used: set[str] = set()
    for route, name in _routes(get_resolver().url_patterns):
        parts = list(_PART.finditer(route))
        if "workspace_id" not in {part["name"] for part in parts}:
            continue
        if route.startswith("^") or "(?P<" in route:
            raise PayloadError(f"The pattern {name or route!r} is a regular expression; teach this probe to fill it.")
        filled: list[str] = []

        def value(match: re.Match[str], filled: list[str] = filled) -> str:
            part = match["name"]
            if part == "workspace_id":
                return workspace_id
            if part in objects:
                filled.append(part)
                return objects[part]
            return _SAMPLES.get(match["converter"] or "str", "e2e")

        path = "/" + _PART.sub(value, route)
        used.update(filled)
        resolved = resolve(path)
        urls.append({"name": name, "route": route, "path": path, "objects": filled, "resolves_to": resolved.view_name})
    unknown = sorted(set(objects) - used)
    if unknown:
        raise PayloadError(f"No workspace URL takes {', '.join(unknown)}.")
    return {"count": len(urls), "urls": urls}


@fixture("isolation_b_objects")
def isolation_b_objects(payload: dict[str, Any]) -> dict[str, Any]:
    """Rows in workspace B for the object URLs: an account, a post waiting for review, a brief, an idea.

    Each carries B's name, so a page that showed one to a member of A would be caught by its text.
    """
    from apps.composer.models import Idea, PlatformPost, Post
    from apps.social_accounts.models import SocialAccount
    from apps.studio.models import StudioBrief
    from apps.workspaces.models import Workspace

    workspace = Workspace.objects.get(pk=seed.WORKSPACE_B_ID)
    author = _user_by_email(seed.USERS["owner_b"][0])
    tag = uuid.uuid4().hex[:8]
    account = SocialAccount(
        workspace=workspace,
        platform="linkedin_company",
        account_platform_id=f"e2e-li-bayside-{tag}",
        account_name=f"{workspace.name} page {tag}",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        oauth_access_token=f"e2e-token-bayside-{tag}",
    )
    # Connected long ago, as in the seed: no first-connect analytics backfill (it would meet the mock).
    account.__dict__["_skip_analytics_backfill"] = True
    account.save()
    post = Post.objects.create(
        workspace=workspace, author=author, title=f"{workspace.name} launch {tag}", caption=f"{workspace.name} {tag}"
    )
    platform_post = PlatformPost.objects.create(
        post=post, social_account=account, status=PlatformPost.Status.PENDING_REVIEW
    )
    brief = StudioBrief.objects.create(
        workspace=workspace,
        author=author,
        idea=f"{workspace.name} open day {tag}",
        status=StudioBrief.Status.READY,
        post=post,
    )
    idea = Idea.objects.create(workspace=workspace, author=author, title=f"{workspace.name} idea {tag}")
    return {
        "workspace_id": str(workspace.pk),
        "workspace_name": workspace.name,
        "account_id": str(account.pk),
        "post_id": str(post.pk),
        "platform_post_id": str(platform_post.pk),
        "brief_id": str(brief.pk),
        "idea_id": str(idea.pk),
    }


@probe("isolation_b_state")
def isolation_b_state(params: dict[str, Any]) -> dict[str, Any]:
    """The rows :func:`isolation_b_objects` made, as they are now: ``?account_id&post_id&...``.

    A test reads them before and after its refused requests; any field that moved is a request
    that got through.
    """
    from apps.approvals.models import ApprovalAction, PostComment
    from apps.composer.models import Idea, PlatformPost, Post
    from apps.social_accounts.models import SocialAccount
    from apps.studio.models import StudioBrief

    def one(model: Any, key: str, fields: tuple[str, ...]) -> dict[str, Any] | None:
        row = model.objects.filter(pk=require_str(params, key)).values(*fields).first()
        return {field: str(value) for field, value in row.items()} if row else None

    post_id = require_str(params, "post_id")
    return {
        "account": one(SocialAccount, "account_id", ("workspace_id", "connection_status", "account_name")),
        "post": one(Post, "post_id", ("workspace_id", "title", "caption", "updated_at")),
        "platform_post": one(
            PlatformPost,
            "platform_post_id",
            ("status", "scheduled_at", "approved_fingerprint", "approved_by_id", "updated_at"),
        ),
        "brief": one(StudioBrief, "brief_id", ("workspace_id", "status", "idea", "post_id", "updated_at")),
        "idea": one(Idea, "idea_id", ("workspace_id", "title", "status", "updated_at")),
        "posts_in_workspace": Post.objects.filter(workspace_id=seed.WORKSPACE_B_ID).count(),
        "approval_actions": ApprovalAction.objects.filter(post_id=post_id).count(),
        "comments": PostComment.objects.filter(post_id=post_id).count(),
    }
