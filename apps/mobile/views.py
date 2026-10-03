"""Phone screens (Today, More, a post's review page) and the installable-app plumbing.

The phone layout is the same Django app the laptop uses: the same sign-in, the
same permissions, the same endpoints for approving, scheduling and replying.
These views only add the screens a phone needs that the desktop layout does not
have, plus the web-app manifest, the service worker and the offline page that
make the site installable from the browser.
"""

from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET

from apps.composer.models import Post

from . import services

#: Where the installed app's shortcuts (long-press on the icon) lead.
LAUNCH_TARGETS = ("today", "approvals", "new-post", "inbox")
#: The theme colour of the app chrome: the page background, so the status bar
#: blends into the app bar.
THEME_COLOR = "#F7F6F2"


def _workspace(request, workspace_id):
    # RBACMiddleware has already resolved (or refused, with a 403) the workspace
    # from the URL; anything else here would be a routing mistake.
    workspace = getattr(request, "workspace", None)
    if workspace is None or str(workspace.id) != str(workspace_id):
        raise Http404
    return workspace


# ---------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------


@login_required
@require_GET
def today(request, workspace_id):
    """What needs the team today: approvals, this week's schedule, new messages."""
    workspace = _workspace(request, workspace_id)
    context = {"workspace": workspace, **services.today_context(request, workspace)}
    return render(request, "mobile/today.html", context)


@login_required
@require_GET
def more(request, workspace_id):
    """Everything that is not a tab: brands, every other page, the app and the account."""
    workspace = _workspace(request, workspace_id)
    org_membership = getattr(request, "org_membership", None)
    membership = getattr(request, "workspace_membership", None)
    context = {
        "workspace": workspace,
        "role_label": _role_label(membership),
        "is_org_admin": bool(org_membership and org_membership.org_role in ("owner", "admin")),
        "blog": services.blog_counts(workspace),
        "drafts_count": _drafts_count(workspace),
    }
    return render(request, "mobile/more.html", context)


def _role_label(membership) -> str:
    if membership is None:
        return ""
    if membership.custom_role_id:
        return membership.custom_role.name
    return membership.get_workspace_role_display()


def _drafts_count(workspace) -> int:
    from apps.composer.models import PlatformPost

    return (
        PlatformPost.objects.filter(post__workspace_id=workspace.id, status="draft")
        .values("post_id")
        .distinct()
        .count()
    )


@login_required
@require_GET
def post_detail(request, workspace_id, post_id):
    """One post as it will go out on each channel, with the approver's actions."""
    from apps.approvals.models import PostComment

    workspace = _workspace(request, workspace_id)
    post = get_object_or_404(
        Post.objects.for_workspace(workspace.id)
        .select_related("author")
        .prefetch_related(
            "platform_posts__social_account",
            "platform_posts__approved_by",
            "media_attachments__media_asset",
            "versions",
        ),
        pk=post_id,
    )
    services.decorate(post)
    is_client = bool(request.workspace_membership and request.workspace_membership.workspace_role == "client")
    comments = (
        PostComment.objects.filter(post=post, deleted_at__isnull=True, parent_comment__isnull=True)
        .select_related("author")
        .prefetch_related(
            Prefetch("replies", queryset=PostComment.objects.filter(deleted_at__isnull=True).select_related("author"))
        )
        .order_by("created_at")
    )
    if is_client:
        comments = comments.filter(visibility=PostComment.Visibility.EXTERNAL)
    channels = list(post.platform_posts.all())
    for pp in channels:
        pp.public_url = _public_url(pp)
    context = {
        "workspace": workspace,
        "post": post,
        "channels": channels,
        "media": [m for m in post.media_attachments.all() if m.media_asset is not None],
        "comments": list(comments),
        "versions": len(post.versions.all()),
        "can_approve": services.can_approve(request),
        "can_edit": post.is_editable and not is_client,
        "display_timezone": str(services.workspace_tz(workspace)),
    }
    return render(request, "mobile/post.html", context)


def _public_url(pp) -> str:
    """The published post's address on the platform, when the publisher recorded one."""
    if pp.status != "published":
        return ""
    extra = pp.platform_extra or {}
    for key in ("permalink", "permalink_url", "url", "post_url"):
        value = extra.get(key)
        if isinstance(value, str) and value.startswith("https://"):
            return value
    return ""


@login_required
@require_GET
def app_launch(request, target="today"):
    """Where the installed app opens: Today in the brand used last (or a shortcut's screen)."""
    if target not in LAUNCH_TARGETS:
        raise Http404
    workspace = getattr(request, "workspace", None)
    if workspace is None:
        from apps.members.models import WorkspaceMembership

        first = (
            WorkspaceMembership.objects.filter(user=request.user, workspace__is_archived=False)
            .select_related("workspace")
            .order_by("workspace__name")
            .first()
        )
        workspace = first.workspace if first else None
    if workspace is None:
        return redirect("dashboard")
    kwargs = {"workspace_id": workspace.id}
    if target == "approvals":
        return redirect(f"{reverse('calendar:calendar', kwargs=kwargs)}?mode=list&tab=approvals")
    if target == "new-post":
        return redirect("composer:compose", **kwargs)
    if target == "inbox":
        return redirect("inbox:feed", **kwargs)
    return redirect("mobile:today", **kwargs)


# ---------------------------------------------------------------------------
# Installable app: manifest, service worker, offline page
# ---------------------------------------------------------------------------


def _icon(path, size, purpose="any"):
    return {"src": static(path), "sizes": f"{size}x{size}", "type": "image/png", "purpose": purpose}


@require_GET
@cache_control(max_age=3600, public=True)
def manifest(request):
    """The web-app manifest: name, icons and how the installed app opens."""
    name = getattr(settings, "SITE_NAME", "SM Manager")

    def shortcut(label, target, icon):
        return {
            "name": label,
            "short_name": label,
            "url": f"/app/{target}/?source=shortcut",
            "icons": [{"src": static(icon), "sizes": "96x96", "type": "image/png"}],
        }

    data = {
        "id": "/app/",
        "name": name,
        "short_name": name if len(name) <= 12 else name.split()[0],
        "description": "Approve, schedule and answer for every brand from your phone.",
        "lang": "en",
        "dir": "ltr",
        "start_url": "/app/?source=pwa",
        "scope": "/",
        "display": "standalone",
        "background_color": THEME_COLOR,
        "theme_color": THEME_COLOR,
        "categories": ["business", "productivity", "social"],
        "icons": [
            _icon("pwa/icon-192.png", 192),
            _icon("pwa/icon-512.png", 512),
            _icon("pwa/icon-maskable-192.png", 192, "maskable"),
            _icon("pwa/icon-maskable-512.png", 512, "maskable"),
        ],
        "shortcuts": [
            shortcut("Approvals", "approvals", "pwa/shortcut-approvals.png"),
            shortcut("New post", "new-post", "pwa/shortcut-new.png"),
            shortcut("Inbox", "inbox", "pwa/shortcut-inbox.png"),
        ],
    }
    response = JsonResponse(data, json_dumps_params={"indent": 2})
    response["Content-Type"] = "application/manifest+json"
    return response


#: Files the offline page needs, cached when the service worker installs.
OFFLINE_ASSETS = ("pwa/icon-192.png",)


@lru_cache(maxsize=1)
def _build_id() -> str:
    """Changes on every deploy, so browsers pick up a new service worker (and drop old caches)."""
    for key in ("RAILWAY_GIT_COMMIT_SHA", "RENDER_GIT_COMMIT", "SOURCE_COMMIT", "GIT_COMMIT"):
        value = os.environ.get(key, "").strip()
        if value:
            return value[:12]
    template = render_to_string("pwa/sw.js", {"build_id": "", "offline_url": "", "precache": "[]"})
    return hashlib.sha256(template.encode()).hexdigest()[:12]


@require_GET
def service_worker(request):
    """The service worker, served from the root so it can look after every page."""
    body = render_to_string(
        "pwa/sw.js",
        {
            "build_id": _build_id(),
            "offline_url": reverse("pwa_offline"),
            "precache": json.dumps([reverse("pwa_offline"), *(static(p) for p in OFFLINE_ASSETS)]),
        },
    )
    response = HttpResponse(body, content_type="application/javascript; charset=utf-8")
    # Always revalidated: a stale worker would keep serving yesterday's rules.
    response["Cache-Control"] = "no-cache"
    response["Service-Worker-Allowed"] = "/"
    return response


@require_GET
@cache_control(max_age=86400)
def offline(request):
    """Shown by the service worker when a page cannot load without a connection.

    Rendered without the request's context processors: it is the same page for
    everyone and the worker stores it, so it carries no account data. The
    worker stores the response whole, so the script nonce in the body keeps
    matching the Content-Security-Policy header it was served with.
    """
    context = {"theme_color": THEME_COLOR, "SITE_NAME": settings.SITE_NAME, "nonce": str(request.csp_nonce)}
    return HttpResponse(render_to_string("pwa/offline.html", context))
