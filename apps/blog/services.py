"""The rules a blog post lives by.

Every state change to a :class:`~apps.blog.models.BlogPost` goes through this
module so the guarantees hold in one place:

* **The approval is pinned to content.** ``fingerprint(post)`` hashes every
  field that reaches the website. Approving records it; any later change to
  that content bumps ``revision`` and withdraws the approval.
* **Only a person approves.** :func:`approve`, :func:`request_changes` and
  :func:`start_publish` require :func:`apps.approvals.actor.dashboard_approver`:
  an internal approver (``approve_posts``, not a client) signed in to the
  dashboard. The Agent API, MCP, the client portal and the worker cannot.
* **Nothing unapproved leaves the app.** Publishing starts with a database
  claim (``approved`` -> ``publishing``) that only succeeds while the approved
  fingerprint and revision still match, so two clicks or a retry race cannot
  publish twice. The background publisher re-checks the fingerprint
  immediately before its first write to GitHub and stops if it moved.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F
from django.urls import reverse
from django.utils import timezone

from apps.approvals.actor import dashboard_approver

from .models import BlogPost, BlogPostEvent

logger = logging.getLogger(__name__)

Status = BlogPost.Status
Action = BlogPostEvent.Action

# Fields an editor may change. Each one is covered by the fingerprint.
CONTENT_FIELDS = (
    "site",
    "title",
    "slug",
    "excerpt",
    "body",
    "featured_image",
    "featured_image_alt",
    "seo_title",
    "meta_description",
    "category",
    "faq",
)

TOKEN_MISSING_MESSAGE = (
    "Publishing needs BLOG_GITHUB_TOKEN on the SM Manager service: a fine-grained GitHub token with "
    "Contents and Actions read/write on {repo}."
)


class BlogWorkflowError(Exception):
    """A request the post's current state does not allow. The message is for people."""


class PublishNotConfiguredError(BlogWorkflowError):
    pass


class ApprovalStaleError(BlogWorkflowError):
    pass


class PublishConflictError(BlogWorkflowError):
    pass


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------


def _normalise_faq(faq) -> list:
    return [{"q": str(item.get("q", "")), "a": str(item.get("a", ""))} for item in (faq or [])]


def fingerprint(post: BlogPost) -> str:
    """sha256 of the canonical JSON of every field that is published.

    The featured image contributes its id *and* its stored file name, so
    replacing or editing the image in the media library changes the
    fingerprint too.
    """
    image = post.featured_image if post.featured_image_id else None
    payload = {
        "site_id": str(post.site_id) if post.site_id else None,
        "title": post.title,
        "slug": post.slug,
        "excerpt": post.excerpt,
        "body": post.body,
        "featured_image_id": str(image.id) if image else None,
        "featured_image_file": image.file.name if image else "",
        "featured_image_alt": post.featured_image_alt,
        "seo_title": post.seo_title,
        "meta_description": post.meta_description,
        "category": post.category,
        "faq": _normalise_faq(post.faq),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def record_event(post, action, *, user=None, detail="", fingerprint_value=None) -> BlogPostEvent:
    return BlogPostEvent.objects.create(
        post=post,
        user=user if getattr(user, "is_authenticated", False) else None,
        action=action,
        revision=post.revision,
        fingerprint=fingerprint_value if fingerprint_value is not None else "",
        detail=detail[:4000],
    )


def _member_permissions(user, workspace) -> dict:
    from apps.members.models import WorkspaceMembership

    if user is None or not getattr(user, "is_authenticated", False):
        return {}
    membership = (
        WorkspaceMembership.objects.filter(user=user, workspace=workspace).select_related("custom_role").first()
    )
    return membership.effective_permissions if membership else {}


def can_create(user, workspace) -> bool:
    return bool(_member_permissions(user, workspace).get("create_posts"))


def can_edit(user, post) -> bool:
    perms = _member_permissions(user, post.workspace)
    if not perms.get("create_posts"):
        return False
    return post.author_id == user.id or bool(perms.get("edit_others_posts"))


def _require_create(user, workspace):
    if not can_create(user, workspace):
        raise PermissionDenied("You need permission to create posts in this workspace.")


def _require_approver(post) -> Any:
    approver = dashboard_approver(post.workspace)
    if approver is None:
        raise PermissionDenied(
            "Only an internal approver signed in to the dashboard can approve, send back or publish a blog post."
        )
    return approver


def _lock(post) -> BlogPost:
    return (
        BlogPost.objects.select_for_update(of=("self",))
        .select_related("site", "workspace", "featured_image")
        .get(pk=post.pk)
    )


def _clear_approval(post):
    post.approved_fingerprint = ""
    post.approved_revision = None
    post.approved_by = None
    post.approved_at = None


_APPROVAL_FIELDS = ["approved_fingerprint", "approved_revision", "approved_by", "approved_at"]


def _withdraw_approval(post, *, user=None, reason: str):
    """Send an approved (or failed-after-approval) post back to review."""
    _clear_approval(post)
    post.status = Status.PENDING_REVIEW
    record_event(post, Action.APPROVAL_WITHDRAWN, user=user, detail=reason, fingerprint_value=fingerprint(post))


def _missing_for_review(post) -> list[str]:
    missing = []
    if not post.title.strip():
        missing.append("a title")
    if not post.slug.strip():
        missing.append("an address (slug)")
    if not post.body.strip():
        missing.append("a body")
    return missing


def _detail_url(post) -> str:
    path = reverse("blog:detail", kwargs={"workspace_id": post.workspace_id, "post_id": post.id})
    return f"{settings.APP_URL.rstrip('/')}{path}"


def _notify(users, event_type, title, body, post):
    """Best effort: a notification failure never blocks the workflow."""
    from apps.notifications.engine import notify

    data = {"blog_post_id": str(post.id), "workspace_id": str(post.workspace_id), "action_url": _detail_url(post)}
    for user in {u for u in users if u is not None}:
        try:
            notify(user=user, event_type=event_type, title=title, body=body, data=data)
        except Exception:
            logger.exception("Could not notify %s about blog post %s", getattr(user, "pk", None), post.pk)


def _approvers(workspace, exclude=None):
    from apps.approvals.actor import is_internal_approver
    from apps.members.models import WorkspaceMembership

    memberships = WorkspaceMembership.objects.filter(workspace=workspace).select_related("user", "custom_role")
    return [m.user for m in memberships if m.user != exclude and is_internal_approver(m.user, workspace)]


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------


def create_post(*, workspace, site, author, **fields) -> BlogPost:
    """Create a draft. Any member who may create posts can."""
    _require_create(author, workspace)
    unknown = set(fields) - set(CONTENT_FIELDS)
    if unknown:
        raise ValueError(f"Unknown blog post fields: {sorted(unknown)}")
    with transaction.atomic():
        post = BlogPost(workspace=workspace, site=site, author=author, status=Status.DRAFT, revision=1, **fields)
        post.full_clean()
        post.save()
        record_event(post, Action.CREATED, user=author, fingerprint_value=fingerprint(post))
    return post


def update_content(post, user, **changes) -> BlogPost:
    """Save content changes. Bumps the revision and withdraws a stale approval.

    A change that leaves the fingerprint as it was is not a change: no new
    revision, no event, the approval stands.
    """
    unknown = set(changes) - set(CONTENT_FIELDS)
    if unknown:
        raise ValueError(f"Unknown blog post fields: {sorted(unknown)}")
    if not can_edit(user, post):
        raise PermissionDenied("You don't have permission to edit this blog post.")

    with transaction.atomic():
        locked = _lock(post)
        if locked.status == Status.PUBLISHING:
            raise BlogWorkflowError("This post is being published right now; edit it once publishing finishes.")
        if locked.has_been_committed:
            if "slug" in changes and changes["slug"] != locked.slug:
                raise ValidationError({"slug": "The address can't change after the post has been published."})
            new_site = changes.get("site")
            if new_site is not None and new_site.pk != locked.site_id:
                raise ValidationError({"site": "The website can't change after the post has been published."})

        before = fingerprint(locked)
        for name, value in changes.items():
            setattr(locked, name, value)
        locked.full_clean()
        after = fingerprint(locked)
        if after == before:
            return locked

        locked.revision += 1
        record_event(locked, Action.EDITED, user=user, fingerprint_value=after)
        approval_stale = bool(locked.approved_fingerprint) and after != locked.approved_fingerprint
        if approval_stale and locked.status in (Status.APPROVED, Status.FAILED):
            _withdraw_approval(locked, user=user, reason="The content changed after it was approved.")
        elif locked.status == Status.PUBLISHED:
            # The live page keeps the published revision; this edit is a new
            # revision that needs its own approval before it can go out.
            _clear_approval(locked)
            locked.status = Status.PENDING_REVIEW
            record_event(
                locked,
                Action.APPROVAL_WITHDRAWN,
                user=user,
                detail="Edited after publishing; the update needs approval before it goes live.",
                fingerprint_value=after,
            )
        locked.save()
    return locked


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------


def submit_for_review(post, user) -> BlogPost:
    """draft / changes_requested -> pending_review. Any member who may create posts."""
    _require_create(user, post.workspace)
    with transaction.atomic():
        locked = _lock(post)
        if locked.status not in (Status.DRAFT, Status.CHANGES_REQUESTED):
            raise BlogWorkflowError(f"A post that is {locked.get_status_display().lower()} can't be submitted.")
        missing = _missing_for_review(locked)
        if missing:
            raise BlogWorkflowError(f"Add {', '.join(missing)} before submitting for approval.")
        locked.status = Status.PENDING_REVIEW
        locked.save(update_fields=["status", "updated_at"])
        record_event(locked, Action.SUBMITTED, user=user, fingerprint_value=fingerprint(locked))
    _notify(
        _approvers(locked.workspace, exclude=user),
        "post_submitted",
        "Blog post submitted for approval",
        f'{user.display_name} submitted "{locked.title}" for approval.',
        locked,
    )
    return locked


def approve(post, comment: str = "") -> BlogPost:
    """Approve the current revision. Only a dashboard approver."""
    approver = _require_approver(post)
    with transaction.atomic():
        locked = _lock(post)
        if locked.status != Status.PENDING_REVIEW:
            raise BlogWorkflowError(
                f"Only a post awaiting approval can be approved (this one is {locked.get_status_display().lower()})."
            )
        missing = _missing_for_review(locked)
        if missing:
            raise BlogWorkflowError(f"This post still needs {', '.join(missing)}.")
        current = fingerprint(locked)
        locked.approved_fingerprint = current
        locked.approved_revision = locked.revision
        locked.approved_by = approver
        locked.approved_at = timezone.now()
        locked.status = Status.APPROVED
        locked.last_error = ""
        locked.save(update_fields=[*_APPROVAL_FIELDS, "status", "last_error", "updated_at"])
        record_event(locked, Action.APPROVED, user=approver, detail=comment.strip(), fingerprint_value=current)
    _notify(
        [locked.author] if locked.author != approver else [],
        "post_approved",
        "Blog post approved",
        f'"{locked.title}" was approved by {approver.display_name}.',
        locked,
    )
    return locked


def request_changes(post, comment: str) -> BlogPost:
    """Send the post back to its author. Only a dashboard approver; a comment is required."""
    approver = _require_approver(post)
    comment = (comment or "").strip()
    if not comment:
        raise BlogWorkflowError("Say what needs to change.")
    with transaction.atomic():
        locked = _lock(post)
        if locked.status not in (Status.PENDING_REVIEW, Status.APPROVED, Status.FAILED):
            raise BlogWorkflowError(f"A post that is {locked.get_status_display().lower()} can't be sent back.")
        _clear_approval(locked)
        locked.status = Status.CHANGES_REQUESTED
        locked.save(update_fields=[*_APPROVAL_FIELDS, "status", "updated_at"])
        record_event(
            locked, Action.CHANGES_REQUESTED, user=approver, detail=comment, fingerprint_value=fingerprint(locked)
        )
    _notify(
        [locked.author] if locked.author != approver else [],
        "post_changes_requested",
        "Changes requested on your blog post",
        f'{approver.display_name} asked for changes to "{locked.title}": {comment}',
        locked,
    )
    return locked


# ---------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------


def github_token() -> str:
    return (getattr(settings, "BLOG_GITHUB_TOKEN", "") or "").strip()


def can_start_publish(post) -> bool:
    """Whether the post is in a state a publish may start from (ignores who asks)."""
    if post.status == Status.APPROVED:
        return True
    return post.status == Status.FAILED and post.approval_is_current


def start_publish(post) -> BlogPost:
    """Claim the post for publishing and queue the background publisher.

    Only a dashboard approver may start it. Refuses up front, leaving the post
    approved, when the GitHub token is missing. The claim is a single
    conditional UPDATE, so concurrent clicks or retries publish at most once.
    """
    from .tasks import publish_blog_post

    approver = _require_approver(post)
    post = BlogPost.objects.select_related("site", "workspace", "featured_image").get(pk=post.pk)
    if not post.site.is_enabled:
        raise BlogWorkflowError(f"Publishing to {post.site.name} is switched off.")
    if not github_token():
        raise PublishNotConfiguredError(TOKEN_MISSING_MESSAGE.format(repo=post.site.repo))
    if post.status == Status.PUBLISHING:
        raise PublishConflictError("This post is already being published.")
    if not can_start_publish(post):
        raise BlogWorkflowError(
            f"Only an approved post can be published (this one is {post.get_status_display().lower()})."
        )

    current = fingerprint(post)
    if current != post.approved_fingerprint or post.revision != post.approved_revision:
        # Committed before raising: the withdrawal must stick.
        with transaction.atomic():
            locked = _lock(post)
            moved = fingerprint(locked) != locked.approved_fingerprint or locked.revision != locked.approved_revision
            if locked.status in (Status.APPROVED, Status.FAILED) and moved:
                locked.revision += 1
                _withdraw_approval(locked, reason="The content changed after it was approved; it needs approval again.")
                locked.save()
        raise ApprovalStaleError(
            "The post changed after it was approved, so it needs approval again before publishing."
        )

    with transaction.atomic():
        attempt = post.publish_attempts + 1
        claimed = BlogPost.objects.filter(
            pk=post.pk,
            status__in=[Status.APPROVED, Status.FAILED],
            approved_fingerprint=current,
            approved_revision=post.revision,
            revision=post.revision,
            publish_attempts=post.publish_attempts,
        ).update(
            status=Status.PUBLISHING,
            publish_attempts=F("publish_attempts") + 1,
            publish_started_at=timezone.now(),
            dispatched_at=None,
            deploy_run_id=None,
            deploy_run_url="",
            deploy_status="",
            last_error="",
            updated_at=timezone.now(),
        )
        if claimed != 1:
            raise PublishConflictError(
                "Publishing has already started for this post (or it changed). Refresh the page."
            )
        post.refresh_from_db()
        record_event(
            post, Action.PUBLISH_STARTED, user=approver, detail=f"Attempt {attempt}.", fingerprint_value=current
        )
        # Queued in the same transaction as the claim: both land or neither.
        publish_blog_post(str(post.pk), attempt)
    return post


def claim_matches(post, attempt: int) -> bool:
    """Whether ``post`` is still the claimed, approved revision a task was queued for."""
    return (
        post.status == Status.PUBLISHING
        and post.publish_attempts == attempt
        and bool(post.approved_fingerprint)
        and post.approved_revision == post.revision
        and fingerprint(post) == post.approved_fingerprint
    )


def stop_stale_publish(post, *, reason: str) -> None:
    """The content moved under a claimed publish: withdraw the approval, publish nothing."""
    with transaction.atomic():
        locked = _lock(post)
        if locked.status != Status.PUBLISHING:
            return
        locked.revision += 1
        _withdraw_approval(locked, reason=reason)
        locked.last_error = reason
        locked.save()


def fail_publish(post, message: str, *, action=Action.PUBLISH_FAILED, attempt: int | None = None) -> None:
    """``publishing`` -> ``failed`` with a readable error. The approval is kept for a retry."""
    with transaction.atomic():
        qs = BlogPost.objects.filter(pk=post.pk, status=Status.PUBLISHING)
        if attempt is not None:
            qs = qs.filter(publish_attempts=attempt)
        updated = qs.update(status=Status.FAILED, last_error=message, updated_at=timezone.now())
        if not updated:
            return
        post.refresh_from_db()
        record_event(post, action, detail=message, fingerprint_value=post.approved_fingerprint)
    _notify([post.author, post.approved_by], "post_failed", "Blog post failed to publish", message, post)


def return_to_approved(post, message: str, *, attempt: int) -> None:
    """``publishing`` -> ``approved`` without having written anything (e.g. the token went away)."""
    with transaction.atomic():
        updated = BlogPost.objects.filter(pk=post.pk, status=Status.PUBLISHING, publish_attempts=attempt).update(
            status=Status.APPROVED, last_error=message, updated_at=timezone.now()
        )
        if updated:
            post.refresh_from_db()
            record_event(post, Action.PUBLISH_FAILED, detail=message, fingerprint_value=post.approved_fingerprint)


# ---------------------------------------------------------------------------
# Social drafts
# ---------------------------------------------------------------------------

# Video-only platforms cannot carry a link-and-image teaser.
_TEASER_POST_TYPES = {"image", "link", "text", "article", "pin"}


def platform_accepts_blog_teaser(platform: str) -> bool:
    from providers import PROVIDER_REGISTRY

    provider_cls = PROVIDER_REGISTRY.get(platform)
    if provider_cls is None:
        return False
    provider = provider_cls(credentials={})
    post_types = {t.value for t in provider.supported_post_types}
    media_types = {t.value for t in provider.supported_media_types}
    return bool(post_types & _TEASER_POST_TYPES) and "jpeg" in media_types


def social_caption(post, url: str) -> str:
    teaser = (post.excerpt or post.meta_description or "").strip()
    if len(teaser) > 220:
        teaser = teaser[:219].rsplit(" ", 1)[0].rstrip(",.;:") + "…"
    parts = [post.title.strip()]
    if teaser:
        parts.append(teaser)
    parts.append(f"Read more: {url}")
    return "\n\n".join(parts)


def create_social_drafts(post, user):
    """One composer draft promoting the post, for every channel that can carry it.

    Plain drafts only: they go through the normal approval workflow before
    they can be scheduled. With no suitable channel connected the draft is
    channel-less, which the composer supports.
    """
    from apps.composer.models import PlatformPost, PostMedia
    from apps.composer.models import Post as ComposerPost
    from apps.social_accounts.models import SocialAccount

    _require_create(user, post.workspace)
    post = BlogPost.objects.select_related("site", "workspace", "featured_image").get(pk=post.pk)
    if post.status not in (Status.APPROVED, Status.PUBLISHED):
        raise BlogWorkflowError("Social drafts can be created once the post is approved or published.")

    url = post.published_url or post.expected_url
    accounts = [
        account
        for account in SocialAccount.objects.filter(workspace=post.workspace)
        .exclude(
            connection_status__in=[SocialAccount.ConnectionStatus.DISCONNECTED, SocialAccount.ConnectionStatus.ERROR]
        )
        .order_by("platform", "account_name")
        if platform_accepts_blog_teaser(account.platform)
    ]
    with transaction.atomic():
        draft = ComposerPost.objects.create(
            workspace=post.workspace,
            author=user,
            title=post.title[:255],
            caption=social_caption(post, url),
            internal_notes=f'Created from the blog post "{post.title}" ({url}).',
        )
        if post.featured_image_id:
            PostMedia.objects.create(
                post=draft,
                media_asset=post.featured_image,
                position=0,
                alt_text=post.featured_image_alt or post.title,
            )
        for account in accounts:
            PlatformPost.objects.create(post=draft, social_account=account, status=PlatformPost.Status.DRAFT)
        channels = ", ".join(a.display_label or a.platform for a in accounts) or "no channels yet"
        record_event(
            post,
            Action.SOCIAL_DRAFTS_CREATED,
            user=user,
            detail=f"Draft {draft.pk} for {len(accounts)} channel(s): {channels}.",
            fingerprint_value=fingerprint(post),
        )
    return draft


def _workspace_tz(workspace):
    try:
        return ZoneInfo(workspace.effective_timezone or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def local_today(workspace) -> dt.date:
    """Today in the workspace's timezone: the date a post is published on."""
    return timezone.localdate(timezone=_workspace_tz(workspace))


def post_content(post):
    """The renderer's snapshot of ``post``, dated in the workspace's timezone."""
    from .renderers import PostContent

    tz = _workspace_tz(post.workspace)
    published_on = timezone.localtime(post.published_at, tz).date() if post.published_at else None
    return PostContent.from_post(post, today=timezone.localdate(timezone=tz), published_on=published_on)


def suggest_slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)[:100].strip("-")
