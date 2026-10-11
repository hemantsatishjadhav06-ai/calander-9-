"""Dashboard pages for writing, approving and publishing blog posts.

Every URL is under ``/workspace/<workspace_id>/blog/``; the RBAC middleware
has already refused non-members (403) by the time a view runs. The rules
about who may approve or publish live in :mod:`apps.blog.services` — these
views only decide which buttons to show and translate refusals into messages.
"""

import uuid
from typing import Any
from urllib.parse import urlsplit

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django_ratelimit.decorators import ratelimit

from apps.approvals.actor import dashboard_approver
from apps.members.decorators import require_permission

from . import ai_images, search_console, seo, services
from .covers import cover_for_post
from .forms import BlogPostForm, parse_faq
from .models import BlogPost, BlogSite
from .publisher import commit_link
from .renderers import PostContent, absolutize_urls, render_post_page

Status = BlogPost.Status

TABS = (
    ("drafts", "Drafts", (Status.DRAFT, Status.CHANGES_REQUESTED)),
    ("review", "Awaiting approval", (Status.PENDING_REVIEW,)),
    ("approved", "Approved", (Status.APPROVED, Status.PUBLISHING)),
    ("published", "Published", (Status.PUBLISHED,)),
    ("failed", "Failed", (Status.FAILED,)),
)
_EMPTY_STATES = {
    "drafts": ("No drafts", "Start a blog post for one of this workspace's websites."),
    "review": ("Nothing awaiting approval", "Posts submitted for approval appear here."),
    "approved": ("No approved posts", "Approved posts wait here until someone publishes them."),
    "published": ("Nothing published yet", "Posts appear here once they are live on the website."),
    "failed": ("No failed publishes", "If a publish fails, the post and the reason appear here."),
}


def _workspace(request, workspace_id):
    workspace = request.workspace
    if workspace is None or workspace.id != workspace_id:
        raise PermissionDenied("You do not have access to this workspace.")
    return workspace


def _get_post(request, workspace_id, post_id):
    workspace = _workspace(request, workspace_id)
    post = get_object_or_404(
        BlogPost.objects.select_related("site", "author", "approved_by", "featured_image", "workspace"),
        pk=post_id,
        workspace=workspace,
    )
    return workspace, post


def _detail_redirect(post):
    return redirect("blog:detail", workspace_id=post.workspace_id, post_id=post.pk)


def is_staff(request) -> bool:
    """A member of the agency's own team — not a client, who signs off in the client portal."""
    from apps.studio.views import is_plain_client

    return request.workspace_membership is not None and not is_plain_client(request.workspace_membership)


def _staff_workspace(request, workspace_id):
    workspace = _workspace(request, workspace_id)
    if not is_staff(request):
        raise PermissionDenied("This part of SM Bean is for your agency team. Your approvals are in the client portal.")
    return workspace


# ---------------------------------------------------------------------------
# The SEO score, the Google preview and the rankings (apps.blog.seo / search_console)
# ---------------------------------------------------------------------------

#: The live score reads at most this much of the article (a long guide is ~30k).
SEO_BODY_LIMIT = 200_000
_RING_RADIUS = 26


def _values_from_post(post) -> dict:
    return {
        "site": str(post.site_id or ""),
        "title": post.title,
        "slug": post.slug,
        "body": post.body,
        "seo_title": post.seo_title,
        "meta_description": post.meta_description,
        "excerpt": post.excerpt,
        "focus_keyword": post.focus_keyword,
        "secondary_keywords": ", ".join(post.secondary_keywords or []),
        "faq": post.faq or [],
        "featured_image_alt": post.featured_image_alt,
        "featured_image": str(post.featured_image_id or ""),
        "cover_style": post.cover_style,
    }


def _seo_inputs(data, workspace, post=None) -> dict:
    """The editor's current values as score arguments. Reads only; nothing is saved."""
    sites = BlogSite.objects.filter(workspace=workspace)
    site = None
    try:
        site = sites.filter(pk=uuid.UUID(str(data.get("site") or ""))).first()
    except ValueError:
        site = None
    if post is not None and (site is None or post.has_been_committed):
        site = post.site
    if site is None:
        site = sites.filter(is_enabled=True).order_by("name").first() or sites.order_by("name").first()
    slug = str(data.get("slug") or "").strip().lower()
    if post is not None and (not slug or post.has_been_committed):
        slug = post.slug
    faq = data.get("faq")
    if faq is None:
        try:
            faq = parse_faq(str(data.get("faq_text") or ""))
        except ValidationError:
            faq = []
    raw_terms = str(data.get("secondary_keywords") or "")
    try:
        secondary = services.clean_keywords(raw_terms)
    except ValidationError:
        secondary = [t.strip() for t in raw_terms.split(",") if t.strip()]
    cover_style = str(data.get("cover_style") or BlogPost.CoverStyle.DESIGNED)

    def text(name, limit=2000):
        return str(data.get(name) or "")[:limit]

    return {
        "site": site,
        "title": text("title", 300),
        "slug": slug[:120],
        "body": str(data.get("body") or "")[:SEO_BODY_LIMIT],
        "seo_title": text("seo_title", 300),
        "meta_description": text("meta_description", 1000),
        "excerpt": text("excerpt", 1000),
        "focus_keyword": services.clean_keyword(text("focus_keyword", 200)),
        "secondary_keywords": secondary,
        "faq": faq,
        "image_alt": text("featured_image_alt", 500),
        "has_image": bool(data.get("featured_image")) or cover_style == BlogPost.CoverStyle.DESIGNED,
    }


def _ring(score: int) -> dict:
    circumference = round(2 * 3.14159265 * _RING_RADIUS, 2)
    return {"radius": _RING_RADIUS, "circumference": circumference, "dash": round(circumference * score / 100, 2)}


def _google_preview(site, values: dict, report) -> dict:
    slug = values["slug"] or "your-article"
    url = site.live_url_for(slug) if site else f"https://example.com/blog/{slug}"
    parts = urlsplit(url)
    crumbs = [parts.netloc] + [p.removesuffix(".html") for p in parts.path.split("/") if p]
    description = PostContent(
        title=values["title"],
        slug=slug,
        excerpt=values["excerpt"].strip(),
        body_md=values["body"],
        meta_description=values["meta_description"].strip(),
    ).description
    return {"crumbs": crumbs, "title": report.title_tag, "description": description}


def seo_panel_context(workspace, values: dict, post=None) -> dict:
    """Everything the SEO panel shows for these values: the score, the checks, the Google preview."""
    values = dict(values)
    site = values.pop("site")
    others = BlogPost.objects.filter(site=site) if site else BlogPost.objects.none()
    if post is not None:
        others = others.exclude(pk=post.pk)
    report = seo.score(
        **values,
        site_kind=site.kind if site else "",
        site_origin=site.origin if site else "",
        other_titles=list(others.values_list("title", flat=True)[:500]),
    )
    return {
        "report": report,
        "ring": _ring(report.score),
        "preview": _google_preview(site, {**values, "site": site}, report),
    }


def ranking_context(post, report=None) -> dict:
    """The post's Google rankings over 28 days, when its website is connected to Search Console."""
    connection = search_console.connection_for(post.site)
    context: dict[str, Any] = {
        "configured": search_console.is_configured(),
        "connected": search_console.is_connected(connection),
        "connection": connection,
    }
    if not context["connected"]:
        return context
    trend = search_console.page_trend(post.site, post.published_url or post.expected_url)
    context["trend"] = trend
    if post.status == Status.PUBLISHED:
        context["suggestion"] = seo.suggestion(report, trend)
    return context


@login_required
@require_GET
def post_list(request, workspace_id):
    workspace = _workspace(request, workspace_id)
    active = request.GET.get("tab", "drafts")
    if active not in {key for key, _label, _statuses in TABS}:
        active = "drafts"
    counts = BlogPost.objects.filter(workspace=workspace).aggregate(
        **{key: Count("pk", filter=Q(status__in=statuses)) for key, _label, statuses in TABS}
    )
    statuses = next(statuses for key, _label, statuses in TABS if key == active)
    posts = list(
        BlogPost.objects.filter(workspace=workspace, status__in=statuses)
        .select_related("site", "author", "featured_image")
        .order_by("-updated_at")
    )
    # One query for the sites' titles, then the pure score per post.
    reports = seo.score_posts(posts)
    for post in posts:
        post.seo_report = reports[post.pk]  # type: ignore[attr-defined]
    empty_title, empty_body = _EMPTY_STATES[active]
    return render(
        request,
        "blog/post_list.html",
        {
            "workspace": workspace,
            "tabs": [(key, label, counts[key]) for key, label, _statuses in TABS],
            "active_tab": active,
            "posts": posts,
            "empty_title": empty_title,
            "empty_body": empty_body,
            "has_sites": BlogSite.objects.filter(workspace=workspace).exists(),
            "can_create": services.can_create(request.user, workspace),
            **_search_overview(request, workspace),
        },
    )


def _search_overview(request, workspace) -> dict:
    """The list page's "Google Search" section: each website's rankings and the latest SEO check-up."""
    from apps.studio.models import AgencyJob

    staff = is_staff(request)
    perms = request.workspace_membership.effective_permissions if request.workspace_membership else {}
    sites = []
    for site in BlogSite.objects.filter(workspace=workspace).select_related("search_console").order_by("name"):
        connection = getattr(site, "search_console", None)
        entry: dict[str, Any] = {
            "site": site,
            "connection": connection,
            "has_token": search_console.has_token(connection),
            "connected": search_console.is_connected(connection),
        }
        if entry["connected"]:
            entry["overview"] = search_console.site_overview(site)
            by_path = {
                _page_path(p.published_url or p.expected_url): p
                for p in BlogPost.objects.filter(site=site, status=Status.PUBLISHED).select_related("site")
            }
            for page in entry["overview"]["pages"]:
                page["post"] = by_path.get(_page_path(page["page"]))
        sites.append(entry)
    checkup = (
        AgencyJob.objects.filter(workspace=workspace, kind=AgencyJob.Kind.SEO).order_by("-created_at").first()
        if staff
        else None
    )
    return {
        "search_sites": sites,
        "search_configured": search_console.is_configured(),
        "can_manage_search": staff and bool(perms.get("manage_workspace_settings")),
        "can_run_checkup": staff and bool(perms.get("create_posts")),
        "checkup": checkup,
        "checkup_pages": (checkup.result.get("pages") or [])[:5] if checkup and checkup.result else [],
    }


def _page_path(url: str) -> str:
    """An article's address without host, ``.html`` or trailing slash: how Google's rows are matched to posts."""
    return urlsplit(url).path.rstrip("/").removesuffix(".html")


def _save_form(request, workspace, form, post=None):
    """Create or update from a valid form and say so; returns the post, or None with errors on the form."""
    changes = form.content_changes()
    try:
        if post is None:
            created = services.create_post(workspace=workspace, author=request.user, **changes)
            messages.success(request, "Draft saved.")
            return created
        before_status, before_revision = post.status, post.revision
        updated = services.update_content(post, request.user, **changes)
        if (
            before_status in (Status.APPROVED, Status.FAILED, Status.PUBLISHED)
            and updated.status == Status.PENDING_REVIEW
        ):
            messages.warning(request, "Saved. The changes need approval again before they can be published.")
        elif updated.revision == before_revision:
            messages.info(request, "Nothing changed.")
        else:
            messages.success(request, f"Saved as revision {updated.revision}.")
        return updated
    except ValidationError as exc:
        if hasattr(exc, "error_dict"):
            for field, errors in exc.message_dict.items():
                form.add_error(field if field in form.fields else None, errors)
        else:
            form.add_error(None, exc.messages)
    except services.BlogWorkflowError as exc:
        form.add_error(None, str(exc))
    return None


@login_required
@require_permission("create_posts")
@require_http_methods(["GET", "POST"])
def post_create(request, workspace_id):
    workspace = _workspace(request, workspace_id)
    if not BlogSite.objects.filter(workspace=workspace, is_enabled=True).exists():
        return render(request, "blog/no_sites.html", {"workspace": workspace}, status=200)
    instance = BlogPost(workspace=workspace, author=request.user)
    form = BlogPostForm(request.POST or None, instance=instance, workspace=workspace)
    if request.method == "POST" and form.is_valid():
        post = _save_form(request, workspace, form)
        if post is not None:
            return _detail_redirect(post)
    values = request.POST if request.method == "POST" else {}
    return render(
        request,
        "blog/post_form.html",
        {
            "workspace": workspace,
            "form": form,
            "post": None,
            "form_state": form.alpine_state(),
            "ai_configured": ai_images.is_configured(),
            "ai_model": ai_images.model_id(),
            "seo_score_url": reverse("blog:seo_score", kwargs={"workspace_id": workspace.id}),
            "show_seo_panel": is_staff(request),
            **seo_panel_context(workspace, _seo_inputs(values, workspace)),
        },
    )


@login_required
@require_permission("create_posts")
@require_http_methods(["GET", "POST"])
def post_edit(request, workspace_id, post_id):
    workspace, post = _get_post(request, workspace_id, post_id)
    if not services.can_edit(request.user, post):
        raise PermissionDenied("You don't have permission to edit this blog post.")
    if post.status == Status.PUBLISHING:
        messages.info(request, "This post is being published; you can edit it once publishing finishes.")
        return _detail_redirect(post)
    form = BlogPostForm(request.POST or None, instance=post, workspace=workspace)
    if request.method == "POST" and form.is_valid():
        # The form has written its values onto ``post``; the service re-reads
        # the stored row so the change is measured against what was approved.
        saved = _save_form(request, workspace, form, post=BlogPost.objects.get(pk=post.pk))
        if saved is not None:
            return _detail_redirect(saved)
    stored = BlogPost.objects.select_related("site").get(pk=post.pk)
    values = request.POST if request.method == "POST" else _values_from_post(stored)
    panel = seo_panel_context(workspace, _seo_inputs(values, workspace, stored), stored)
    return render(
        request,
        "blog/post_form.html",
        {
            "workspace": workspace,
            "form": form,
            "post": stored,
            "warn_withdraw": stored.status in (Status.APPROVED, Status.FAILED, Status.PUBLISHED),
            "slug_locked": form.slug_locked,
            "form_state": form.alpine_state(),
            "ai_configured": ai_images.is_configured(),
            "ai_model": ai_images.model_id(),
            "seo_score_url": reverse("blog:post_seo_score", kwargs={"workspace_id": workspace.id, "post_id": post.id}),
            "show_seo_panel": is_staff(request),
            **panel,
            "ranking": ranking_context(stored, panel["report"]) if stored.status == Status.PUBLISHED else None,
        },
    )


def _actions(request, post):
    user = request.user
    approver = dashboard_approver(post.workspace) is not None
    editable = services.can_edit(user, post)
    creator = services.can_create(user, post.workspace)
    return {
        "can_edit": editable and post.status != Status.PUBLISHING,
        "can_submit": creator and post.status in (Status.DRAFT, Status.CHANGES_REQUESTED),
        "can_approve": approver and post.status == Status.PENDING_REVIEW,
        "can_request_changes": approver and post.status in (Status.PENDING_REVIEW, Status.APPROVED, Status.FAILED),
        "can_publish": approver and post.status == Status.APPROVED,
        "can_retry": approver and post.status == Status.FAILED and post.approval_is_current,
        "can_social": creator and post.status in (Status.APPROVED, Status.PUBLISHED),
        "is_approver": approver,
    }


@login_required
@require_GET
def post_detail(request, workspace_id, post_id):
    workspace, post = _get_post(request, workspace_id, post_id)
    events = post.events.select_related("user").all()[:100]
    report = seo.score_post(post)
    return render(
        request,
        "blog/post_detail.html",
        {
            "workspace": workspace,
            "post": post,
            "events": events,
            "commit_url": commit_link(post),
            "token_configured": bool(services.github_token()),
            "approval_matches": post.approval_is_current,
            "report": report,
            "ring": _ring(report.score),
            "ranking": ranking_context(post, report) if post.status == Status.PUBLISHED else None,
            "can_manage_search": is_staff(request)
            and bool(
                request.workspace_membership
                and request.workspace_membership.effective_permissions.get("manage_workspace_settings")
            ),
            **_actions(request, post),
        },
    )


@login_required
@require_GET
def post_status(request, workspace_id, post_id):
    """The publish-status panel, polled by HTMX while a publish runs."""
    workspace, post = _get_post(request, workspace_id, post_id)
    response = render(
        request,
        "blog/partials/publish_status.html",
        {"workspace": workspace, "post": post, "commit_url": commit_link(post)},
    )
    if post.status != Status.PUBLISHING and request.headers.get("HX-Request"):
        # Publishing finished: reload so the buttons and audit trail catch up.
        response["HX-Refresh"] = "true"
    return response


# The preview runs the website's own CSS and scripts. A sandboxed CSP gives
# the page an opaque origin, so those scripts can never read the dashboard's
# cookies or call it as the signed-in user.
def _preview_csp(site, request) -> str:
    app_origin = f"{request.scheme}://{request.get_host()}"
    return "; ".join(
        [
            "sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox",
            "default-src 'none'",
            f"script-src {site.origin}",
            "style-src 'unsafe-inline' https:",
            f"img-src https: data: {app_origin}",
            "font-src https: data:",
            f"base-uri {site.origin}",
            "form-action 'none'",
            "frame-ancestors 'self'",
        ]
    )


@login_required
@require_GET
def post_preview(request, workspace_id, post_id):
    """The page exactly as it will be published, with asset URLs made absolute."""
    _workspace_obj, post = _get_post(request, workspace_id, post_id)
    hero_src = None
    if post.cover_style == BlogPost.CoverStyle.DESIGNED:
        hero_src = (
            request.build_absolute_uri(
                reverse("blog:cover", kwargs={"workspace_id": post.workspace_id, "post_id": post.id})
            )
            + f"?v={post.revision}"
        )
    elif post.featured_image_id and post.featured_image.file:
        hero_src = request.build_absolute_uri(post.featured_image.file.url)
    page = render_post_page(post.site, services.post_content(post), hero_src=hero_src)
    page = absolutize_urls(page, post.expected_url)
    response = HttpResponse(page, content_type="text/html; charset=utf-8")
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Cache-Control"] = "private, no-store"
    response["Content-Security-Policy"] = _preview_csp(post.site, request)
    response["Referrer-Policy"] = "no-referrer"
    response._csp_exempt = True
    return response


def _run(request, post, action, success_message):
    try:
        action()
    except PermissionDenied:
        raise
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    except services.BlogWorkflowError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, success_message)
    return _detail_redirect(post)


@login_required
@require_permission("create_posts")
@require_POST
def post_submit(request, workspace_id, post_id):
    _ws, post = _get_post(request, workspace_id, post_id)
    return _run(
        request,
        post,
        lambda: services.submit_for_review(post, request.user),
        "Submitted for approval. Approvers have been notified.",
    )


@login_required
@require_permission("approve_posts")
@require_POST
def post_approve(request, workspace_id, post_id):
    _ws, post = _get_post(request, workspace_id, post_id)
    return _run(
        request,
        post,
        lambda: services.approve(post, request.POST.get("comment", "")),
        f"Approved revision {post.revision}. It can be published now.",
    )


@login_required
@require_permission("approve_posts")
@require_POST
def post_request_changes(request, workspace_id, post_id):
    _ws, post = _get_post(request, workspace_id, post_id)
    return _run(
        request,
        post,
        lambda: services.request_changes(post, request.POST.get("comment", "")),
        "Sent back to the author with your comments.",
    )


@login_required
@require_permission("approve_posts")
@require_POST
def post_publish(request, workspace_id, post_id):
    _ws, post = _get_post(request, workspace_id, post_id)
    return _run(
        request,
        post,
        lambda: services.start_publish(post),
        f"Publishing to {post.site.name}. This usually takes a few minutes; this page updates by itself.",
    )


@login_required
@require_permission("create_posts")
@require_POST
def post_social_drafts(request, workspace_id, post_id):
    _ws, post = _get_post(request, workspace_id, post_id)
    try:
        draft = services.create_social_drafts(post, request.user)
    except services.BlogWorkflowError as exc:
        messages.error(request, str(exc))
        return _detail_redirect(post)
    channels = draft.platform_posts.count()
    if channels:
        messages.success(
            request,
            f"Created a social draft for {channels} channel{'s' if channels != 1 else ''}. "
            "It goes through approval like any other post.",
        )
    else:
        messages.success(request, "Created a social draft. Connect a channel and pick it in the composer.")
    return redirect(reverse("composer:compose_edit", kwargs={"workspace_id": post.workspace_id, "post_id": draft.pk}))


@login_required
@require_GET
def post_cover(request, workspace_id, post_id):
    """The designed cover for this post's current content, as a JPEG.

    Shown in the editor, the detail page and the preview; the publisher
    renders the same bytes for the website (see ``apps.blog.covers``).
    """
    _ws, post = _get_post(request, workspace_id, post_id)
    try:
        data = cover_for_post(post, services.post_content(post))
    except ValueError as exc:
        return HttpResponse(str(exc), status=422, content_type="text/plain; charset=utf-8")
    response = HttpResponse(data, content_type="image/jpeg")
    response["Cache-Control"] = "private, no-store"
    response["X-Robots-Tag"] = "noindex"
    return response


@login_required
@require_permission("create_posts")
@require_POST
def post_generate_image(request, workspace_id, post_id):
    """Ask fal.ai for a picture for this post and make it the featured image."""
    from django.core.files.base import ContentFile

    from apps.media_library.models import MediaAsset
    from apps.media_library.quotas import StorageQuotaExceededError, enforce_storage_quota
    from apps.media_library.tasks import process_media_asset

    workspace, post = _get_post(request, workspace_id, post_id)
    edit_url = reverse("blog:edit", kwargs={"workspace_id": workspace.id, "post_id": post.id})
    if not services.can_edit(request.user, post):
        raise PermissionDenied("You don't have permission to edit this blog post.")
    if post.status == Status.PUBLISHING:
        messages.info(request, "This post is being published; change its picture once publishing finishes.")
        return _detail_redirect(post)

    brief = (request.POST.get("brief") or "").strip()[:600]
    try:
        generated = ai_images.generate_image(
            title=post.title, category=post.category, site_kind=post.site.kind, brief=brief, seed=post.slug
        )
        width, height = ai_images.validate_image(generated.content)
        enforce_storage_quota(workspace.organization, len(generated.content))
    except ai_images.ImageGenerationError as exc:
        messages.error(request, str(exc))
        return redirect(edit_url)
    except StorageQuotaExceededError:
        messages.error(request, "You're out of storage. Delete unused media, or ask your admin to raise the limit.")
        return redirect(edit_url)

    filename = f"ai-cover-{post.slug or post.pk}-r{post.revision}.{generated.extension}"
    asset = MediaAsset.objects.create(
        organization=workspace.organization,
        workspace=workspace,
        uploaded_by=request.user,
        file=ContentFile(generated.content, name=filename),
        filename=filename,
        title=f"AI picture: {post.title}"[:255],
        media_type=MediaAsset.MediaType.IMAGE,
        mime_type=generated.content_type,
        file_size=len(generated.content),
        width=width,
        height=height,
        source="fal.ai",
        attribution=f"Generated with {generated.model} on fal.ai",
        alt_text=(post.featured_image_alt or post.title)[:500],
        tags=["ai", "blog-cover"],
    )
    process_media_asset(str(asset.id))

    changes = {"featured_image": asset}
    if not (post.featured_image_alt or "").strip():
        changes["featured_image_alt"] = post.title[:300]
    try:
        updated = services.update_content(BlogPost.objects.get(pk=post.pk), request.user, **changes)
    except (ValidationError, services.BlogWorkflowError) as exc:
        messages.error(request, f"The picture was saved to the media library but couldn't be attached: {exc}")
        return redirect(edit_url)
    if updated.status == Status.PENDING_REVIEW and post.status in (Status.APPROVED, Status.FAILED, Status.PUBLISHED):
        messages.warning(
            request, "Picture generated and attached. The change needs approval again before it goes live."
        )
    else:
        messages.success(request, f"Picture generated with {generated.model} and set as the featured image.")
    return redirect(edit_url)


# ---------------------------------------------------------------------------
# SEO: the live score in the editor and the on-demand check-up
# ---------------------------------------------------------------------------


@login_required
@require_POST
@require_permission("create_posts")
# Re-scored as the writer types (debounced in the page): generous, but bounded.
@ratelimit(key="user", rate="240/m", method="POST", block=True)
def seo_score(request, workspace_id, post_id=None):
    """The SEO panel for the editor's current, unsaved values. Saves nothing.

    The per-post variant scores against the site's *other* articles and keeps
    a published post's fixed address.
    """
    workspace = _staff_workspace(request, workspace_id)
    post = None
    if post_id is not None:
        _ws, post = _get_post(request, workspace_id, post_id)
    context = seo_panel_context(workspace, _seo_inputs(request.POST, workspace, post), post)
    return render(request, "blog/partials/seo_panel.html", {"workspace": workspace, "post": post, **context})


@login_required
@require_POST
@require_permission("create_posts")
@ratelimit(key="user", rate="10/m", method="POST", block=True)
def seo_checkup(request, workspace_id):
    """Ask the SEO monitor to check every published article now (it also runs weekly by itself).

    The monitor is plain code — scores and Search Console numbers, no model —
    so it costs nothing against the AI budget. It runs in the worker.
    """
    from apps.studio import engine
    from apps.studio.models import AgencyJob

    workspace = _staff_workspace(request, workspace_id)
    active = AgencyJob.objects.filter(
        workspace=workspace, kind=AgencyJob.Kind.SEO, status__in=AgencyJob.ACTIVE_STATUSES
    ).first()
    if active is not None:
        messages.info(request, "The SEO monitor is already checking your articles.")
        return redirect("studio:job", workspace_id=workspace.id, job_id=active.pk)
    job = engine.create(workspace, AgencyJob.Kind.SEO, title="SEO check-up", requested_by=request.user)
    messages.success(request, "The SEO monitor is checking your published articles. It takes a minute.")
    return redirect("studio:job", workspace_id=workspace.id, job_id=job.pk)
