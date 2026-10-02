"""Dashboard pages for writing, approving and publishing blog posts.

Every URL is under ``/workspace/<workspace_id>/blog/``; the RBAC middleware
has already refused non-members (403) by the time a view runs. The rules
about who may approve or publish live in :mod:`apps.blog.services` — these
views only decide which buttons to show and translate refusals into messages.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.approvals.actor import dashboard_approver
from apps.members.decorators import require_permission

from . import services
from .forms import BlogPostForm
from .models import BlogPost, BlogSite
from .publisher import commit_link
from .renderers import absolutize_urls, render_post_page

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
    posts = (
        BlogPost.objects.filter(workspace=workspace, status__in=statuses)
        .select_related("site", "author", "featured_image")
        .order_by("-updated_at")
    )
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
        },
    )


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
    return render(
        request,
        "blog/post_form.html",
        {"workspace": workspace, "form": form, "post": None, "form_state": form.alpine_state()},
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
    stored = BlogPost.objects.get(pk=post.pk)
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
    if post.featured_image_id and post.featured_image.file:
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
