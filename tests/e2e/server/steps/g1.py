"""Golden paths 1 (sign in with email and with Google) and 11 (workspace isolation).

Path 1 posts the real login form and goes through allauth's Google flow; these steps register the
profile Google would return, make a fresh member of workspace A for the "existing email" case, and
read back the sessions and accounts the sign-in left in the database.

Path 11 asks the URL resolver for every pattern that takes a ``workspace_id`` (so a new page is
covered the day it is added), with the methods each view accepts; makes one row of every kind those
URLs name in workspace B; reads those rows back so a test can show that a refused request changed
nothing; and clears the views' rate-limit counters around the sweep that posts every action once.
"""

from __future__ import annotations

import hashlib
import io
import re
import uuid
from datetime import timedelta
from typing import Any, cast

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


def _person(email: str, name: str) -> Any:
    """A new user who has accepted the terms, without the organisation every new user is given.

    The same steps the seed takes for its own people (``seed.py``): create the user with the seed's
    password, then remove the "My Workspace" organisation and memberships that
    ``apps/accounts/signals.py`` makes for every new user, so they land where a test puts them.
    """
    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership
    from apps.organizations.models import Organization

    user = User.objects.create_user(email=email, password=seed.PASSWORD, name=name, tos_accepted_at=timezone.now())
    auto_orgs = list(OrgMembership.objects.filter(user=user).values_list("organization_id", flat=True))
    WorkspaceMembership.objects.filter(user=user).delete()
    OrgMembership.objects.filter(user=user).delete()
    Organization.objects.filter(id__in=auto_orgs).delete()
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
    user = _person(email, "Mo Member")
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

#: The rows :func:`isolation_b_objects` makes in workspace B, by the key a URL part is filled from,
#: with each model's path to its workspace. A key is a part name (``asset_id``), or a namespace or a
#: URL name and the part, where the same part names another kind of row (``blog:post_id`` is an
#: article, ``inbox:saved_reply_edit:reply_id`` a saved reply); the most specific key wins.
_B_ROWS: dict[str, tuple[str, str]] = {
    "account_id": ("social_accounts.SocialAccount", "workspace"),
    "post_id": ("composer.Post", "workspace"),
    "platform_post_id": ("composer.PlatformPost", "post__workspace"),
    "media_id": ("composer.PostMedia", "post__workspace"),
    "idea_id": ("composer.Idea", "workspace"),
    "group_id": ("composer.IdeaGroup", "workspace"),
    "category_id": ("composer.ContentCategory", "workspace"),
    "template_id": ("composer.PostTemplate", "workspace"),
    "feed_id": ("composer.Feed", "workspace"),
    "comment_id": ("approvals.PostComment", "post__workspace"),
    "slot_id": ("calendar.PostingSlot", "social_account__workspace"),
    "queue_id": ("calendar.Queue", "workspace"),
    "entry_id": ("calendar.QueueEntry", "queue__workspace"),
    "event_id": ("calendar.CustomCalendarEvent", "workspace"),
    "message_id": ("inbox.InboxMessage", "workspace"),
    "reply_id": ("inbox.InboxReply", "inbox_message__workspace"),
    "inbox:saved_reply_edit:reply_id": ("inbox.SavedReply", "workspace"),
    "inbox:saved_reply_delete:reply_id": ("inbox.SavedReply", "workspace"),
    "asset_id": ("media_library.MediaAsset", "workspace"),
    "version_id": ("media_library.MediaAssetVersion", "media_asset__workspace"),
    "folder_id": ("media_library.MediaFolder", "workspace"),
    "membership_id": ("members.WorkspaceMembership", "workspace"),
    "link_id": ("onboarding.ConnectionLink", "workspace"),
    "blog:post_id": ("blog.BlogPost", "workspace"),
    "blog_post_id": ("blog.BlogPost", "workspace"),
    "site_id": ("blog.BlogSite", "workspace"),
    "blog:job_id": ("studio.AgencyJob", "workspace"),
    "job_id": ("studio.AgencyJob", "workspace"),
    "brief_id": ("studio.StudioBrief", "workspace"),
    "concept_id": ("studio.StudioConcept", "brief__workspace"),
    "insight_id": ("studio.CreativeInsight", "workspace"),
    "conversation_id": ("studio.Conversation", "workspace"),
    "routine_id": ("studio.Routine", "workspace"),
}

#: Rows a request that got through would add under B's rows, counted before and after.
_B_CHILDREN: tuple[tuple[str, str], ...] = (
    ("approvals.ApprovalAction", "post__workspace"),
    ("composer.PostVersion", "post__workspace"),
    ("inbox.InternalNote", "inbox_message__workspace"),
    ("studio.Message", "conversation__workspace"),
    ("studio.RoutineRun", "routine__workspace"),
    ("client_portal.MagicLinkToken", "workspace"),
)


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


def _methods(view: Any) -> list[str] | None:
    """The HTTP methods a view accepts, or ``None`` when it does not restrict them.

    Read from Django's ``require_http_methods`` (and ``require_POST``/``require_GET``) closure, or a
    class-based view's handlers, through the decorators that wrap it.
    """
    seen: set[int] = set()
    current = view
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        view_class = getattr(current, "view_class", None)
        if view_class is not None:
            names = [name for name in view_class.http_method_names if name != "options" and hasattr(view_class, name)]
            return sorted(name.upper() for name in names)
        code = getattr(current, "__code__", None)
        closure = getattr(current, "__closure__", None)
        if code is not None and closure:
            cells = dict(zip(code.co_freevars, closure, strict=True))
            if "request_method_list" in cells:
                return sorted(str(method) for method in cells["request_method_list"].cell_contents)
        current = getattr(current, "__wrapped__", None)
    return None


def _object_key(objects: dict[str, str], name: str, part: str) -> str | None:
    """Which of the test's keys fills ``part`` of the URL called ``name``: the most specific one sent."""
    keys = [f"{name}:{part}"]
    namespace = name.rpartition(":")[0]
    while namespace:
        keys.append(f"{namespace}:{part}")
        namespace = namespace.rpartition(":")[0]
    keys.append(part)
    return next((key for key in keys if key in objects), None)


@probe("isolation_urls")
def isolation_urls(params: dict[str, Any]) -> dict[str, Any]:
    """Every URL pattern that takes a ``workspace_id``, filled in: ``?workspace_id=&<key>=<id>...``.

    Each other part of the path takes the test's id for it (``post_id``, or a more specific key such
    as ``blog:post_id``; see ``_B_ROWS``) and a sample of its type otherwise. Each URL comes back
    with its pattern's name, the parts that were the test's own objects (``objects``), the parts left
    at a sample (``samples``), and the methods its view accepts (``methods``, ``None`` for any).
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
        pieces: list[str] = []
        filled: list[str] = []
        samples: list[str] = []
        end = 0
        for match in parts:
            pieces.append(route[end : match.start()])
            end = match.end()
            part = match["name"]
            if part == "workspace_id":
                pieces.append(workspace_id)
                continue
            key = _object_key(objects, name, part)
            if key is None:
                pieces.append(_SAMPLES.get(match["converter"] or "str", "e2e"))
                samples.append(part)
            else:
                pieces.append(objects[key])
                filled.append(part)
                used.add(key)
        path = "/" + "".join(pieces) + route[end:]
        resolved = resolve(path)
        urls.append(
            {
                "name": name,
                "route": route,
                "path": path,
                "objects": filled,
                "samples": samples,
                "methods": _methods(resolved.func),
                "resolves_to": resolved.view_name,
            }
        )
    unknown = sorted(set(objects) - used)
    if unknown:
        raise PayloadError(f"No workspace URL takes {', '.join(unknown)}.")
    return {"count": len(urls), "urls": urls}


def _tiny_png() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (240, 240), (30, 37, 51)).save(buffer, format="PNG")
    return buffer.getvalue()


@fixture("isolation_b_objects")
def isolation_b_objects(payload: dict[str, Any]) -> dict[str, Any]:
    """One row of every kind a workspace URL names, in workspace B (see ``_B_ROWS``).

    Each row is made the way B's own people would leave it (an account with its queue and slots, a
    post waiting for review with a comment, a library image, a comment in the inbox with a draft
    reply, an article, finished jobs, a thread, a paused routine, a client) and carries B's name
    where it has text, so a page that showed one to a member of A would be caught by its words.
    Nothing here is due to run or to publish, so the worker leaves the rows as they are. Returns
    ``{"workspace_id", "workspace_name", "objects": {key: id}}``.
    """
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.approvals.models import PostComment
    from apps.blog.models import BlogPost, BlogSite
    from apps.calendar.models import CustomCalendarEvent, PostingSlot, Queue, QueueEntry
    from apps.calendar.services import create_default_queue_and_slots
    from apps.composer.models import ContentCategory, Feed, Idea, IdeaGroup, PlatformPost, Post, PostMedia, PostTemplate
    from apps.inbox.models import InboxMessage, InboxReply, SavedReply
    from apps.media_library.models import MediaAssetVersion, MediaFolder
    from apps.media_library.services import create_asset
    from apps.media_library.tasks import process_media_asset
    from apps.members.models import OrgMembership, WorkspaceMembership
    from apps.onboarding.models import ConnectionLink
    from apps.social_accounts.models import SocialAccount
    from apps.studio.models import AgencyJob, Conversation, CreativeInsight, Routine, StudioBrief, StudioConcept
    from apps.workspaces.models import Workspace

    workspace = Workspace.objects.get(pk=seed.WORKSPACE_B_ID)
    organization = workspace.organization
    author = _user_by_email(seed.USERS["owner_b"][0])
    tag = uuid.uuid4().hex[:8]
    name = workspace.name
    now = timezone.now()

    account = SocialAccount(
        workspace=workspace,
        platform="linkedin_company",
        account_platform_id=f"e2e-li-bayside-{tag}",
        account_name=f"{name} page {tag}",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        oauth_access_token=f"e2e-token-bayside-{tag}",
    )
    # Connected long ago, as in the seed: no first-connect analytics backfill (it would meet the mock).
    account.__dict__["_skip_analytics_backfill"] = True
    account.save()
    create_default_queue_and_slots(account)
    queue = Queue.objects.get(social_account=account)
    slot = PostingSlot.objects.filter(social_account=account).order_by("day_of_week", "time").first()

    post = Post.objects.create(
        workspace=workspace, author=author, title=f"{name} launch {tag}", caption=f"{name} {tag}"
    )
    platform_post = PlatformPost.objects.create(
        post=post, social_account=account, status=PlatformPost.Status.PENDING_REVIEW
    )
    comment = PostComment.objects.create(post=post, author=author, body=f"{name} comment {tag}")
    entry = QueueEntry.objects.create(queue=queue, post=post)

    folder = MediaFolder.objects.create(organization=organization, workspace=workspace, name=f"{name} folder {tag}")
    upload = SimpleUploadedFile(f"bayside-{tag}.png", _tiny_png(), content_type="image/png")
    asset = create_asset(organization, workspace, upload, author, title=f"{name} photo {tag}", alt_text=f"{name}")
    process_media_asset.now(str(asset.id))
    asset.refresh_from_db()
    version = MediaAssetVersion.objects.create(
        media_asset=asset,
        version_number=1,
        file=asset.file.name,
        change_description=f"{name} original",
        created_by=author,
    )
    media = PostMedia.objects.create(post=post, media_asset=asset, alt_text=f"{name} photo")

    brief = StudioBrief.objects.create(
        workspace=workspace, author=author, idea=f"{name} open day {tag}", status=StudioBrief.Status.READY, post=post
    )
    concept = StudioConcept.objects.create(brief=brief, title=f"{name} angle {tag}", hook=f"{name} hook {tag}")
    idea = Idea.objects.create(workspace=workspace, author=author, title=f"{name} idea {tag}")
    group = IdeaGroup.objects.create(workspace=workspace, name=f"{name} column {tag}")
    category = ContentCategory.objects.create(workspace=workspace, name=f"{name} category {tag}")
    template = PostTemplate.objects.create(
        workspace=workspace,
        name=f"{name} template {tag}",
        created_by=author,
        template_data={"caption": f"{name} {tag}"},
    )
    feed = Feed.objects.create(
        workspace=workspace, name=f"{name} news {tag}", url=f"https://bayside-{tag}.e2e.test/feed.xml", added_by=author
    )
    event = CustomCalendarEvent.objects.create(
        workspace=workspace,
        title=f"{name} open day {tag}",
        start_date=now.date(),
        end_date=now.date(),
        created_by=author,
    )

    message = InboxMessage.objects.create(
        workspace=workspace,
        social_account=account,
        platform_message_id=f"e2e-bayside-comment-{tag}",
        sender_name=f"{name} customer",
        body=f"{name} question {tag}",
        received_at=now,
    )
    reply = InboxReply.objects.create(inbox_message=message, author=author, body=f"{name} reply {tag}")
    saved_reply = SavedReply.objects.create(
        workspace=workspace, title=f"{name} saved reply {tag}", body=f"{name} thanks {tag}", created_by=author
    )

    client = _person(f"client-b-{tag}@e2e.test", f"{name} client")
    OrgMembership.objects.create(user=client, organization=organization, org_role="member")
    membership = WorkspaceMembership.objects.create(
        user=client, workspace=workspace, workspace_role=WorkspaceMembership.WorkspaceRole.CLIENT
    )
    client.last_workspace_id = workspace.pk
    client.save(update_fields=["last_workspace_id"])
    link = ConnectionLink.objects.create(workspace=workspace, created_by=author, expires_at=now + timedelta(days=1))

    site = BlogSite.objects.create(
        workspace=workspace,
        name=f"{name} website {tag}",
        kind=BlogSite.Kind.NEOPOLIS_STATIC,
        site_url=f"https://bayside-{tag}.e2e.test",
        repo=f"bayside/site-{tag}",
        workflow_file="deploy.yml",
    )
    article = BlogPost.objects.create(
        workspace=workspace, site=site, author=author, title=f"{name} article {tag}", slug=f"bayside-article-{tag}"
    )
    finished = {"status": AgencyJob.Status.DONE, "requested_by": author, "finished_at": now}
    job = AgencyJob.objects.create(
        workspace=workspace, kind=AgencyJob.Kind.REPORT, title=f"{name} report {tag}", **finished
    )
    blog_job = AgencyJob.objects.create(
        workspace=workspace, kind=AgencyJob.Kind.BLOG, title=f"{name} article job {tag}", blog_post=article, **finished
    )
    insight = CreativeInsight.objects.create(
        workspace=workspace,
        media_asset=asset,
        source=CreativeInsight.Source.UPLOAD,
        is_reference=True,
        reference_note=f"{name} reference {tag}",
    )
    conversation = Conversation.objects.create(workspace=workspace, title=f"{name} thread {tag}", created_by=author)
    routine = Routine.objects.create(
        workspace=workspace,
        created_by=author,
        title=f"{name} routine {tag}",
        instruction=f"{name} weekly round-up {tag}",
        enabled=False,
    )

    rows = {
        "account_id": account,
        "post_id": post,
        "platform_post_id": platform_post,
        "media_id": media,
        "idea_id": idea,
        "group_id": group,
        "category_id": category,
        "template_id": template,
        "feed_id": feed,
        "comment_id": comment,
        "slot_id": slot,
        "queue_id": queue,
        "entry_id": entry,
        "event_id": event,
        "message_id": message,
        "reply_id": reply,
        "inbox:saved_reply_edit:reply_id": saved_reply,
        "inbox:saved_reply_delete:reply_id": saved_reply,
        "asset_id": asset,
        "version_id": version,
        "folder_id": folder,
        "membership_id": membership,
        "link_id": link,
        "blog:post_id": article,
        "blog_post_id": article,
        "site_id": site,
        "blog:job_id": blog_job,
        "job_id": job,
        "brief_id": brief,
        "concept_id": concept,
        "insight_id": insight,
        "conversation_id": conversation,
        "routine_id": routine,
    }
    missing = sorted(set(_B_ROWS) ^ set(rows))
    if missing:
        raise PayloadError(f"isolation_b_objects and _B_ROWS disagree about {', '.join(missing)}.")
    return {
        "workspace_id": str(workspace.pk),
        "workspace_name": workspace.name,
        "objects": {key: str(row.pk) for key, row in rows.items()},
    }


def _digest(value: Any) -> str:
    """A short fingerprint of a column's value: enough to see it move, without echoing it."""
    return hashlib.sha256(repr(value).encode()).hexdigest()[:16]


@probe("isolation_b_state")
def isolation_b_state(params: dict[str, Any]) -> dict[str, Any]:
    """B's rows as they are now: ``?<key>=<id>...``, the ``objects`` :func:`isolation_b_objects` made.

    Every column of every row, as a fingerprint (so a credential column is never echoed), and how many
    rows of each kind B has, including the ones a request would add under B's rows (an approval, a
    note, a message, a run, a portal link). A test reads it before and after its refused requests;
    anything that moved is a request that got through.
    """
    from django.apps import apps

    unknown = sorted(set(params) - set(_B_ROWS))
    if unknown:
        raise PayloadError(f"Unknown keys {', '.join(unknown)}; send the objects isolation_b_objects made.")
    rows: dict[str, dict[str, str] | None] = {}
    for key in sorted(_B_ROWS):
        model = apps.get_model(_B_ROWS[key][0])
        row = model._base_manager.filter(pk=require_str(params, key)).values().first()
        rows[key] = {column: _digest(value) for column, value in row.items()} if row else None
    counts: dict[str, int] = {}
    for label, path in sorted({*_B_ROWS.values(), *_B_CHILDREN}):
        counts[label] = apps.get_model(label)._base_manager.filter(**{path: seed.WORKSPACE_B_ID}).count()
    return {"rows": rows, "counts": counts}


@fixture("reset_rate_limits")
def reset_rate_limits(payload: dict[str, Any]) -> dict[str, Any]:
    """Forget every view's rate-limit counters (django-ratelimit's, in the server's own cache).

    Path 11 posts each action under A once, the rate-limited ones included; it calls this before and
    after, so it is never refused for an earlier test's requests and leaves everyone's allowance as
    it found it. The login limits have their own fixture (``reset_login_limits``).
    """
    from django.core.cache import caches
    from django.core.cache.backends.locmem import LocMemCache

    cache = caches[getattr(settings, "RATELIMIT_USE_CACHE", "default")]
    if not isinstance(cache, LocMemCache):
        raise PayloadError("The rate-limit cache is not the local-memory one config.settings.e2e sets.")
    prefix = cache.make_key(getattr(settings, "RATELIMIT_CACHE_PREFIX", "rl:"))
    store = cast(Any, cache)
    with store._lock:
        keys = [key for key in store._cache if key.startswith(prefix)]
        cleared = sum(1 for key in keys if store._delete(key))
    return {"cleared": cleared}
