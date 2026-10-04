"""Blog posts for the brands' own websites.

A ``BlogSite`` is one static website whose blog this workspace writes for: the
GitHub repository its pages live in and the workflow that deploys it. A
``BlogPost`` is written and approved here, then committed into that repository
and deployed by the workflow. Nothing about a post leaves the app until an
internal approver has approved the exact revision that goes out — see
``apps.blog.services`` for the rules and ``BlogPostEvent`` for the audit trail.

No secrets live in these tables: the GitHub token is ``BLOG_GITHUB_TOKEN`` in
the environment.
"""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

SLUG_RE = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
# Slugs that would overwrite something other than a post's own page.
RESERVED_SLUGS = frozenset({"index", "img", "blog", "assets", "css", "js"})

validate_slug_format = RegexValidator(
    SLUG_RE,
    "Use lowercase letters, numbers and single hyphens only (for example: flats-in-kokapet-2026).",
)
validate_repo = RegexValidator(
    r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$",
    'Enter the repository as "owner/name".',
)


def validate_slug(value):
    validate_slug_format(value)
    if value in RESERVED_SLUGS:
        raise ValidationError(f'"{value}" is reserved on the website; choose another address.')


class BlogSite(models.Model):
    """A static website this workspace publishes blog posts to."""

    class Kind(models.TextChoices):
        NEOPOLIS_STATIC = "neopolis_static", "Neopolis static site (publish-payload3)"
        MORESPACE_STATIC = "morespace_static", "More Space static site (blog/)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="blog_sites",
    )
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=30, choices=Kind.choices)
    site_url = models.URLField(help_text="The live website, e.g. https://www.neopolisinfra.com")
    repo = models.CharField(max_length=200, validators=[validate_repo], help_text='GitHub repository, "owner/name".')
    branch = models.CharField(max_length=100, default="main")
    workflow_file = models.CharField(max_length=200, help_text="Workflow that deploys the site, e.g. publish3.yml")
    netlify_site_id = models.CharField(max_length=64, blank=True, default="")
    is_enabled = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "blog_site"
        ordering = ["name"]
        constraints = [
            # Two sites writing the same repository would each rebuild its blog
            # index from only their own posts.
            models.UniqueConstraint(fields=["workspace", "repo"], name="blog_site_unique_repo_per_workspace"),
        ]

    def __str__(self):
        return f"{self.name} ({self.repo})"

    @property
    def origin(self) -> str:
        return self.site_url.rstrip("/")

    def live_url_for(self, slug: str) -> str:
        """The public address a post with ``slug`` is served at."""
        if self.kind == self.Kind.MORESPACE_STATIC:
            return f"{self.origin}/blog/{slug}.html"
        # Netlify pretty URLs: /blog/<slug> (the .html form redirects here).
        return f"{self.origin}/blog/{slug}"


class BlogPost(models.Model):
    class CoverStyle(models.TextChoices):
        # The hero image the website shows (see apps.blog.covers).
        DESIGNED = "designed", "Designed cover: the title set over the picture in the brand's look"
        PLAIN = "plain", "Plain: the featured image as uploaded (no image, no hero)"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING_REVIEW = "pending_review", "Awaiting approval"
        CHANGES_REQUESTED = "changes_requested", "Changes requested"
        APPROVED = "approved", "Approved"
        PUBLISHING = "publishing", "Publishing"
        PUBLISHED = "published", "Published"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="blog_posts",
    )
    site = models.ForeignKey(BlogSite, on_delete=models.PROTECT, related_name="posts")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="blog_posts",
    )

    # Content. Every field here is part of the fingerprint the approval is
    # pinned to (apps.blog.services.fingerprint).
    title = models.CharField(max_length=200)
    slug = models.CharField(max_length=100, validators=[validate_slug])
    excerpt = models.TextField(blank=True, default="", max_length=400)
    body = models.TextField(blank=True, default="", help_text="Markdown.")
    # SET_NULL changes what would be published, so the publisher's fingerprint
    # re-check withdraws the approval rather than publishing without the image.
    featured_image = models.ForeignKey(
        "media_library.MediaAsset",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="blog_posts",
    )
    featured_image_alt = models.CharField(max_length=300, blank=True, default="")
    # How the hero is made from the featured image (or, for a designed cover,
    # from the brand background when there is no picture). Part of the
    # fingerprint: switching styles changes what the website shows.
    cover_style = models.CharField(
        max_length=20, choices=CoverStyle.choices, default=CoverStyle.DESIGNED, db_default=CoverStyle.DESIGNED
    )
    seo_title = models.CharField(max_length=60, blank=True, default="")
    meta_description = models.CharField(max_length=160, blank=True, default="")
    category = models.CharField(max_length=60, blank=True, default="")
    faq = models.JSONField(default=list, blank=True, help_text='List of {"q": ..., "a": ...}.')

    status = models.CharField(max_length=30, choices=Status.choices, default=Status.DRAFT, db_index=True)
    # +1 on every content change; the approval records which one it covered.
    revision = models.PositiveIntegerField(default=1)

    approved_fingerprint = models.CharField(max_length=64, blank=True, default="")
    approved_revision = models.PositiveIntegerField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    published_url = models.URLField(blank=True, default="")
    published_at = models.DateTimeField(null=True, blank=True)
    # What the website's blog index shows for this post: the card of the
    # revision that was committed, never the current (possibly unapproved)
    # edit. Empty until the first commit.
    published_card = models.JSONField(default=dict, blank=True)
    commit_sha = models.CharField(max_length=64, blank=True, default="")
    deploy_run_id = models.BigIntegerField(null=True, blank=True)
    deploy_run_url = models.URLField(blank=True, default="")
    deploy_status = models.CharField(max_length=40, blank=True, default="")
    last_error = models.TextField(blank=True, default="")
    publish_attempts = models.PositiveIntegerField(default=0)
    publish_started_at = models.DateTimeField(null=True, blank=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "blog_post"
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["site", "slug"], name="blog_post_unique_slug_per_site"),
        ]

    def __str__(self):
        return self.title or str(self.id)

    @property
    def expected_url(self) -> str:
        return self.site.live_url_for(self.slug)

    @property
    def has_been_committed(self) -> bool:
        """True once a revision of this post has landed in the site's repository."""
        return bool(self.published_card)

    @property
    def is_editable(self) -> bool:
        return self.status != self.Status.PUBLISHING

    @property
    def approval_is_current(self) -> bool:
        return bool(self.approved_fingerprint) and self.approved_revision == self.revision

    def clean(self):
        super().clean()
        if self.site_id and self.workspace_id and self.site.workspace_id != self.workspace_id:
            raise ValidationError({"site": "That website belongs to another workspace."})
        if self.featured_image_id:
            asset = self.featured_image
            if asset.media_type != asset.MediaType.IMAGE:
                raise ValidationError(
                    {"featured_image": "The featured image must be a still image (JPEG, PNG or WebP)."}
                )
            same_ws = asset.workspace_id == self.workspace_id
            shared = asset.workspace_id is None and asset.organization_id == self.workspace.organization_id
            if not (same_ws or shared):
                raise ValidationError({"featured_image": "That image is not in this workspace's media library."})
        _validate_faq(self.faq)


def _validate_faq(faq):
    if faq in (None, ""):
        return
    if not isinstance(faq, list):
        raise ValidationError({"faq": "FAQ must be a list of questions and answers."})
    for item in faq:
        if not isinstance(item, dict) or set(item) != {"q", "a"}:
            raise ValidationError({"faq": 'Each FAQ entry needs exactly a "q" and an "a".'})
        if not str(item["q"]).strip() or not str(item["a"]).strip():
            raise ValidationError({"faq": "Every FAQ entry needs both a question and an answer."})


class BlogPostEvent(models.Model):
    """Append-only audit trail of everything that happened to a blog post."""

    class Action(models.TextChoices):
        CREATED = "created", "Created"
        EDITED = "edited", "Edited"
        SUBMITTED = "submitted", "Submitted for approval"
        APPROVED = "approved", "Approved"
        CHANGES_REQUESTED = "changes_requested", "Changes requested"
        APPROVAL_WITHDRAWN = "approval_withdrawn", "Approval withdrawn"
        PUBLISH_STARTED = "publish_started", "Publishing started"
        COMMITTED = "committed", "Committed to the website repository"
        DEPLOY_SUCCEEDED = "deploy_succeeded", "Deploy succeeded"
        DEPLOY_FAILED = "deploy_failed", "Deploy failed"
        VERIFIED = "verified", "Verified live"
        PUBLISH_FAILED = "publish_failed", "Publishing failed"
        SOCIAL_DRAFTS_CREATED = "social_drafts_created", "Social drafts created"

    post = models.ForeignKey(BlogPost, on_delete=models.CASCADE, related_name="events")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    action = models.CharField(max_length=40, choices=Action.choices)
    revision = models.PositiveIntegerField()
    fingerprint = models.CharField(max_length=64, blank=True, default="")
    detail = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "blog_post_event"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["post", "-created_at"])]

    def __str__(self):
        return f"{self.get_action_display()} (r{self.revision})"
