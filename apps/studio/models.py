"""AI Studio: a creative team of agents that turns a small idea into a post.

A ``BrandProfile`` is what the team works from: how the brand sounds, the
facts it may state, and how its graphics look. A ``StudioBrief`` is one run —
the idea someone typed, the angles the strategist proposed
(``StudioConcept``), the copy, the design spec and the finished graphic — and
it ends as an ordinary composer ``Post`` that goes through the workspace's
approval workflow like any other. ``AgentRun`` is the team's timeline: one row
per agent per revision, with what it produced and what it cost.

Nothing here publishes. The hand-off creates a draft and submits it for
review; only an approver signed in to the dashboard can send it out (see
``apps.approvals.gate``).
"""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.managers import WorkspaceScopedManager
from apps.common.validators import validate_hex_color


class DesignTemplate(models.TextChoices):
    EDITORIAL = "editorial", "Editorial — the picture full-bleed, the headline over it"
    SPLIT = "split", "Split — the picture above, a brand panel below"
    STATEMENT = "statement", "Statement — bold type on the brand colour"
    STAT = "stat", "Stat card — one big number, with a picture strip"


class DesignFormat(models.TextChoices):
    PORTRAIT = "portrait", "Portrait 4:5 (1080×1350) — most room in the feed"
    SQUARE = "square", "Square 1:1 (1080×1080)"
    LANDSCAPE = "landscape", "Landscape 1.91:1 (1200×628)"


class PhotoGrade(models.TextChoices):
    NATURAL = "natural", "Natural colour"
    BRAND_TINT = "brand_tint", "Brand tint — pictures pulled towards the brand colour"
    DUOTONE = "duotone", "Duotone in the brand colours"
    MONO = "mono", "Black and white"


class DisplayFont(models.TextChoices):
    OSWALD = "oswald", "Oswald — condensed and bold"
    OUTFIT = "outfit", "Outfit — geometric and modern"


class BrandProfile(models.Model):
    """How one workspace's brand sounds and looks.

    The text fields are the agents' only source of facts: a number, a price, a
    phone number or a claim that isn't here (or in the idea itself) must not
    appear in a post. The look fields drive the graphic designer until a
    previous post sets the style (see ``apps.studio.style``).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.OneToOneField(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="brand_profile",
    )

    # How it sounds, and what it may say.
    brand_name = models.CharField(max_length=100)
    about = models.CharField(
        max_length=500, blank=True, default="", help_text="One or two sentences: what the company does, for whom."
    )
    audience = models.TextField(blank=True, default="", help_text="Who the posts are for, and what they care about.")
    voice = models.TextField(blank=True, default="", help_text="Tone of voice, in a few lines.")
    facts = models.TextField(
        blank=True,
        default="",
        help_text=(
            "Facts the team may use: offerings, projects, numbers, contact details, links. "
            "The agents state nothing that isn't here or in the idea."
        ),
    )
    dos = models.TextField(blank=True, default="", help_text="Always do.")
    donts = models.TextField(blank=True, default="", help_text="Never do.")
    compliance = models.TextField(
        blank=True, default="", help_text="Legal or regulatory rules, e.g. registration numbers or disclaimers."
    )
    default_cta = models.CharField(max_length=200, blank=True, default="", help_text="The usual call to action.")
    website = models.URLField(blank=True, default="")
    hashtags = models.JSONField(default=list, blank=True, help_text="Hashtags the brand uses.")

    # How it looks.
    primary_color = models.CharField(max_length=7, default="#081D4A", validators=[validate_hex_color])
    accent_color = models.CharField(max_length=7, default="#FF6600", validators=[validate_hex_color])
    display_font = models.CharField(max_length=20, choices=DisplayFont.choices, default=DisplayFont.OSWALD)
    wordmark = models.CharField(max_length=60, help_text="The name as it is set on graphics, e.g. NEOPOLIS INFRA.")
    domain = models.CharField(max_length=100, blank=True, default="", help_text="Shown at the foot of graphics.")
    logo = models.ForeignKey(
        "media_library.MediaAsset",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Optional. A PNG with a transparent background works best; without it the wordmark is set in type.",
    )
    photo_style = models.TextField(
        blank=True,
        default="",
        help_text="What the pictures look like: subject matter, light, lens, mood.",
    )
    house_style = models.TextField(
        blank=True,
        default="",
        db_default="",
        help_text=(
            "The look of your best work in a few lines, written by the creative memory curator from your "
            "references and best-performing posts. You can edit it; the art director and prompt engineer use it."
        ),
    )
    house_style_updated_at = models.DateTimeField(null=True, blank=True)
    default_template = models.CharField(max_length=20, choices=DesignTemplate.choices, default=DesignTemplate.EDITORIAL)
    default_format = models.CharField(max_length=20, choices=DesignFormat.choices, default=DesignFormat.PORTRAIT)
    default_grade = models.CharField(max_length=20, choices=PhotoGrade.choices, default=PhotoGrade.BRAND_TINT)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = WorkspaceScopedManager()

    class Meta:
        db_table = "studio_brand_profile"

    def __str__(self):
        return f"BrandProfile({self.brand_name})"


class StudioBrief(models.Model):
    """One run of the creative team, from a small idea to a post awaiting approval."""

    class Status(models.TextChoices):
        PLANNED = "planned", "Planned — waiting its turn"
        QUEUED = "queued", "Queued"
        WORKING = "working", "The team is working"
        READY = "ready", "Ready for approval"
        APPROVED = "approved", "Approved"
        FAILED = "failed", "Failed"
        DISCARDED = "discarded", "Discarded"

    class Stage(models.TextChoices):
        STRATEGY = "strategy", "Strategist"
        COPY = "copy", "Copywriter"
        ART = "art", "Art director"
        PICTURE = "picture", "Illustrator"
        RENDER = "render", "Designer"
        REVIEW = "review", "Brand reviewer"
        CHANNEL = "channel", "Channel editor"
        QA = "qa", "QA inspector"
        SCHEDULE = "schedule", "Scheduler"
        HANDOFF = "handoff", "Producer"
        DONE = "done", "Done"

    class Origin(models.TextChoices):
        MANUAL = "manual", "Briefed by a person"
        AUTOPILOT = "autopilot", "Planned by autopilot"
        CHAT = "chat", "Asked for in the team thread"
        REPURPOSE = "repurpose", "Made from a blog article"

    class Goal(models.TextChoices):
        AWARENESS = "awareness", "Build awareness"
        EDUCATION = "education", "Teach something useful"
        ENGAGEMENT = "engagement", "Start a conversation"
        LEADS = "leads", "Get enquiries"
        ANNOUNCEMENT = "announcement", "Announce news"

    #: Statuses in which the team is (or is about to be) busy.
    ACTIVE_STATUSES = (Status.QUEUED, Status.WORKING)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="studio_briefs",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="studio_briefs",
    )

    # What was asked.
    idea = models.TextField()
    notes = models.TextField(blank=True, default="")
    goal = models.CharField(max_length=20, choices=Goal.choices, blank=True, default="")
    social_accounts = models.ManyToManyField("social_accounts.SocialAccount", blank=True, related_name="+")
    style_lock = models.BooleanField(
        default=True, help_text="Design the graphic in the same look as the last post this workspace made."
    )
    source_picture = models.ForeignKey(
        "media_library.MediaAsset",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="A photo from the media library to use instead of a generated picture.",
    )
    origin = models.CharField(max_length=20, choices=Origin.choices, default=Origin.MANUAL, db_default=Origin.MANUAL)
    job = models.ForeignKey(
        "AgencyJob",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="briefs",
        help_text="The plan, chat or article job that asked for this brief.",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Who asked for it, when that isn't the author (for example a client in the team thread).",
    )

    # Where the team is.
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED, db_index=True)
    stage = models.CharField(max_length=20, choices=Stage.choices, default=Stage.STRATEGY)
    revision = models.PositiveIntegerField(default=1)
    feedback = models.TextField(blank=True, default="", help_text="The latest change request, if any.")
    error = models.TextField(blank=True, default="")
    auto_revisions = models.PositiveSmallIntegerField(
        default=0, help_text="Revisions the brand reviewer asked for in this revision (capped)."
    )
    regenerate_picture = models.BooleanField(
        default=False, help_text="Paint a new picture on the next pass instead of keeping the current one."
    )

    # What the team made.
    chosen_concept = models.ForeignKey(
        "StudioConcept", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    post_copy = models.JSONField(default=dict, blank=True)
    design_spec = models.JSONField(default=dict, blank=True)
    review_notes = models.JSONField(default=dict, blank=True)
    style_reference = models.JSONField(default=dict, blank=True)
    picture = models.ForeignKey(
        "media_library.MediaAsset", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    graphic = models.ForeignKey(
        "media_library.MediaAsset", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    post = models.ForeignKey(
        "composer.Post", on_delete=models.SET_NULL, null=True, blank=True, related_name="studio_briefs"
    )
    proposed_publish_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    objects = WorkspaceScopedManager()

    class Meta:
        db_table = "studio_brief"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["workspace", "status"], name="idx_studio_brief_ws_status")]

    def __str__(self):
        return f"StudioBrief({self.status}): {self.idea[:50]}"

    @property
    def is_active(self) -> bool:
        return self.status in self.ACTIVE_STATUSES

    @property
    def headline(self) -> str:
        return (self.design_spec or {}).get("headline") or (self.post_copy or {}).get("headline") or ""

    @property
    def title(self) -> str:
        """What lists show for this brief: the headline once there is one, else the idea."""
        return self.headline or (self.chosen_concept.title if self.chosen_concept else "") or self.idea[:120]

    @property
    def caption(self) -> str:
        return (self.post_copy or {}).get("caption", "")

    @property
    def usage_totals(self) -> dict:
        totals = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "images": 0}
        for run in self.runs.all():
            totals["input_tokens"] += run.input_tokens
            totals["output_tokens"] += run.output_tokens
            totals["cache_read_tokens"] += run.cache_read_tokens
            if run.agent == AgentRun.Agent.ILLUSTRATOR and run.status == AgentRun.Status.SUCCEEDED:
                totals["images"] += 1
        return totals


class StudioConcept(models.Model):
    """One angle the strategist proposed for a brief."""

    class PostFormat(models.TextChoices):
        SINGLE_IMAGE = "single_image", "Single image"
        STAT = "stat", "A number that matters"
        QUOTE = "quote", "Point of view"
        TIPS = "tips", "Tips or checklist"
        ANNOUNCEMENT = "announcement", "Announcement"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brief = models.ForeignKey(StudioBrief, on_delete=models.CASCADE, related_name="concepts")
    revision = models.PositiveIntegerField(default=1)
    position = models.PositiveSmallIntegerField(default=0)
    title = models.CharField(max_length=200)
    hook = models.TextField()
    angle = models.TextField(blank=True, default="")
    key_points = models.JSONField(default=list, blank=True)
    post_format = models.CharField(max_length=20, choices=PostFormat.choices, default=PostFormat.SINGLE_IMAGE)
    rationale = models.TextField(blank=True, default="")
    recommended = models.BooleanField(default=False)
    saved_idea = models.ForeignKey("composer.Idea", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "studio_concept"
        ordering = ["revision", "position"]

    def __str__(self):
        return f"StudioConcept({self.position}): {self.title[:50]}"


class AgentRun(models.Model):
    """One agent's turn on a brief or a job: what it made, how long it took, what it cost.

    ``agent`` is a slug from ``apps.studio.team`` (no fixed choices, so the
    team can grow without a migration).
    """

    class Agent:
        """Slugs of the post team, for code that names them."""

        STRATEGIST = "strategist"
        COPYWRITER = "copywriter"
        ART_DIRECTOR = "art_director"
        PROMPT_ENGINEER = "prompt_engineer"
        ILLUSTRATOR = "illustrator"
        DESIGNER = "designer"
        REVIEWER = "reviewer"
        CHANNEL_EDITOR = "channel_editor"
        QA_INSPECTOR = "qa_inspector"
        SCHEDULER = "scheduler"
        PRODUCER = "producer"

    class Status(models.TextChoices):
        RUNNING = "running", "Working"
        SUCCEEDED = "succeeded", "Done"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, null=True, blank=True, related_name="agent_runs"
    )
    brief = models.ForeignKey(StudioBrief, on_delete=models.CASCADE, null=True, blank=True, related_name="runs")
    job = models.ForeignKey("AgencyJob", on_delete=models.CASCADE, null=True, blank=True, related_name="runs")
    revision = models.PositiveIntegerField(default=1)
    agent = models.CharField(max_length=40)
    # Database defaults too, so the previous release can keep writing rows while
    # this one migrates (see apps/inbox/migrations/0003_inboxreply_column_defaults.py).
    stage = models.CharField(max_length=30, blank=True, default="", db_default="")
    effort = models.CharField(max_length=10, blank=True, default="", db_default="")
    fallback_used = models.BooleanField(default=False, db_default=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RUNNING)
    summary = models.CharField(max_length=500, blank=True, default="")
    output = models.JSONField(default=dict, blank=True)
    model = models.CharField(max_length=100, blank=True, default="")
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cache_read_tokens = models.PositiveIntegerField(default=0)
    duration_ms = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "studio_agent_run"
        ordering = ["started_at"]
        indexes = [models.Index(fields=["workspace", "started_at"], name="idx_agent_run_ws_started")]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(brief__isnull=False) | models.Q(job__isnull=False),
                name="agent_run_has_brief_or_job",
            )
        ]

    def __str__(self):
        return f"AgentRun({self.agent} r{self.revision}): {self.status}"

    def save(self, *args, **kwargs):
        if self.workspace_id is None:
            owner = self.brief if self.brief_id else self.job
            if owner is not None:
                self.workspace_id = owner.workspace_id
        super().save(*args, **kwargs)

    @property
    def seconds(self) -> int:
        return round(self.duration_ms / 1000)

    @property
    def agent_name(self) -> str:
        from . import team

        return team.name(self.agent)

    @property
    def agent_spec(self):
        from . import team

        return team.get(self.agent)


# ---------------------------------------------------------------------------
# The agency: jobs beyond a single post, autopilot, the team thread, memory
# ---------------------------------------------------------------------------


class AgencyJob(models.Model):
    """A piece of agency work that isn't one post: a weekly plan, an article, a reply in the thread...

    It moves through the stages of its kind (``apps.studio.jobs``) one worker
    task at a time, with the same rules as a brief: revision-guarded writes,
    tasks that never raise, lower priority than publishing. A job may create
    briefs (a plan), a blog draft (an article) or inbox reply drafts; it never
    approves, schedules or publishes.
    """

    class Kind(models.TextChoices):
        PLAN = "plan", "Weekly plan"
        BLOG = "blog", "Blog article"
        CHAT = "chat", "Reply in the team thread"
        INBOX = "inbox", "Inbox reply drafts"
        REPORT = "report", "Client report"
        LEARN = "learn", "Creative memory refresh"
        REPURPOSE = "repurpose", "Posts from an article"
        SEO = "seo", "SEO check-up"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        WORKING = "working", "Working"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    ACTIVE_STATUSES = (Status.QUEUED, Status.WORKING)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey("workspaces.Workspace", on_delete=models.CASCADE, related_name="agency_jobs")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED, db_index=True)
    stage = models.CharField(max_length=30, blank=True, default="")
    revision = models.PositiveIntegerField(default=1)
    title = models.CharField(max_length=200, blank=True, default="")
    input = models.JSONField(default=dict, blank=True)
    state = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True, default="")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    parent = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="children")
    brief = models.ForeignKey(StudioBrief, on_delete=models.SET_NULL, null=True, blank=True, related_name="jobs")
    blog_post = models.ForeignKey(
        "blog.BlogPost", on_delete=models.SET_NULL, null=True, blank=True, related_name="agency_jobs"
    )
    conversation = models.ForeignKey(
        "Conversation", on_delete=models.SET_NULL, null=True, blank=True, related_name="jobs"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    objects = WorkspaceScopedManager()

    class Meta:
        db_table = "studio_agency_job"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workspace", "status"], name="idx_agency_job_ws_status"),
            models.Index(fields=["kind", "status"], name="idx_agency_job_kind_status"),
        ]

    def __str__(self):
        return f"AgencyJob({self.kind}, {self.status}): {self.title[:50]}"

    @property
    def is_active(self) -> bool:
        return self.status in self.ACTIVE_STATUSES


class AgencySettings(models.Model):
    """One workspace's agency switches: autopilot, budget, who the drafts are from."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.OneToOneField("workspaces.Workspace", on_delete=models.CASCADE, related_name="agency_settings")
    autopilot_enabled = models.BooleanField(
        default=False, help_text="Plan and prepare next week's posts every week. Every post still needs approval."
    )
    posts_per_week = models.PositiveSmallIntegerField(default=5)
    accounts = models.ManyToManyField("social_accounts.SocialAccount", blank=True, related_name="+")
    pillars = models.JSONField(default=list, blank=True, help_text="Themes the planner rotates between.")
    plan_weekday = models.PositiveSmallIntegerField(default=4, help_text="0 is Monday. The default is Friday.")
    plan_hour = models.PositiveSmallIntegerField(default=16, help_text="Hour of day in the workspace timezone.")
    blog_posts_per_month = models.PositiveSmallIntegerField(default=0)
    blog_site = models.ForeignKey("blog.BlogSite", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    monthly_budget_usd = models.DecimalField(
        max_digits=8, decimal_places=2, default=150, help_text="The team starts no new model work past this."
    )
    lead = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Drafts the team makes on its own carry this person's name. An owner or manager.",
    )
    learn_from_best = models.BooleanField(
        default=False,
        help_text="Let the art director start from your best creatives and references, not only the last post.",
    )
    inbox_drafts_enabled = models.BooleanField(
        default=False, help_text="Draft replies to new comments, messages and reviews for a person to send."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = WorkspaceScopedManager()

    class Meta:
        db_table = "studio_agency_settings"

    def __str__(self):
        return f"AgencySettings({self.workspace_id})"


class AutopilotWeek(models.Model):
    """One planned week per workspace. The unique row makes a double tick (two workers) harmless."""

    class Status(models.TextChoices):
        PLANNING = "planning", "Planning"
        PLANNED = "planned", "Planned"
        SKIPPED = "skipped", "Skipped"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey("workspaces.Workspace", on_delete=models.CASCADE, related_name="autopilot_weeks")
    week_start = models.DateField(help_text="The Monday of the week being planned, in the workspace timezone.")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PLANNING)
    job = models.ForeignKey(AgencyJob, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    note = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "studio_autopilot_week"
        ordering = ["-week_start"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "week_start"], name="autopilot_week_unique_per_workspace")
        ]

    def __str__(self):
        return f"AutopilotWeek({self.workspace_id}, {self.week_start}): {self.status}"


class CreativeInsight(models.Model):
    """One creative the team learns from: a post that performed, or a reference a person picked.

    ``score`` is the post's percentile among its own account's posts (0–1,
    higher is better) on that platform's main metric; ``ratio`` is its value
    against the account's median. Both stay empty for references and for
    accounts with too few measured posts.
    """

    class Source(models.TextChoices):
        STUDIO = "studio", "Made by the team"
        EXTERNAL = "external", "Made elsewhere"
        UPLOAD = "upload", "Uploaded reference"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey("workspaces.Workspace", on_delete=models.CASCADE, related_name="creative_insights")
    post = models.ForeignKey("composer.Post", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    platform_post = models.ForeignKey(
        "composer.PlatformPost", on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    media_asset = models.ForeignKey(
        "media_library.MediaAsset", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    social_account = models.ForeignKey(
        "social_accounts.SocialAccount", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    platform = models.CharField(max_length=40, blank=True, default="")
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.EXTERNAL)
    score = models.FloatField(null=True, blank=True)
    ratio = models.FloatField(null=True, blank=True)
    metrics = models.JSONField(default=dict, blank=True)
    features = models.JSONField(default=dict, blank=True)
    caption = models.TextField(blank=True, default="")
    description = models.TextField(blank=True, default="", help_text="The curator's description of the look.")
    is_reference = models.BooleanField(default=False, help_text="A person picked it: learn from this.")
    reference_note = models.CharField(max_length=300, blank=True, default="")
    published_at = models.DateTimeField(null=True, blank=True)
    described_at = models.DateTimeField(null=True, blank=True)
    computed_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = WorkspaceScopedManager()

    class Meta:
        db_table = "studio_creative_insight"
        ordering = ["-is_reference", "-score", "-published_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "platform_post"],
                condition=models.Q(platform_post__isnull=False),
                name="creative_insight_unique_platform_post",
            ),
            models.UniqueConstraint(
                fields=["workspace", "media_asset"],
                condition=models.Q(platform_post__isnull=True, media_asset__isnull=False),
                name="creative_insight_unique_upload",
            ),
        ]
        indexes = [models.Index(fields=["workspace", "is_reference", "score"], name="idx_creative_ws_ref_score")]

    def __str__(self):
        return f"CreativeInsight({self.source}, {self.score})"


class Conversation(models.Model):
    """A thread between people (staff or a client) and the team, about the workspace or one item."""

    class Audience(models.TextChoices):
        CLIENT = "client", "With the client"
        INTERNAL = "internal", "Internal"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey("workspaces.Workspace", on_delete=models.CASCADE, related_name="conversations")
    audience = models.CharField(max_length=20, choices=Audience.choices, default=Audience.INTERNAL)
    title = models.CharField(max_length=200, blank=True, default="")
    brief = models.ForeignKey(
        StudioBrief, on_delete=models.CASCADE, null=True, blank=True, related_name="conversations"
    )
    post = models.ForeignKey("composer.Post", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    blog_post = models.ForeignKey(
        "blog.BlogPost", on_delete=models.CASCADE, null=True, blank=True, related_name="conversations"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    last_message_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = WorkspaceScopedManager()

    class Meta:
        db_table = "studio_conversation"
        ordering = ["-last_message_at", "-created_at"]
        indexes = [models.Index(fields=["workspace", "audience"], name="idx_conversation_ws_audience")]

    def __str__(self):
        return f"Conversation({self.audience}): {self.title[:50]}"


class Message(models.Model):
    """One message in a thread: from a person, or from an agent (usually the account manager)."""

    class AuthorKind(models.TextChoices):
        CLIENT = "client", "Client"
        STAFF = "staff", "Team member"
        AGENT = "agent", "Agent"
        SYSTEM = "system", "System"

    class ActionStatus(models.TextChoices):
        NONE = "", "No action"
        DONE = "done", "Done"
        STARTED = "started", "The team is on it"
        NEEDS_HUMAN = "needs_human", "Waiting for a person"
        DECLINED = "declined", "Not possible"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    author_kind = models.CharField(max_length=20, choices=AuthorKind.choices)
    agent = models.CharField(max_length=40, blank=True, default="")
    body = models.TextField()
    is_internal = models.BooleanField(
        default=False, help_text="A note for the team only; never shown to a client, even in a client thread."
    )
    action = models.CharField(max_length=30, blank=True, default="")
    action_status = models.CharField(max_length=20, choices=ActionStatus.choices, blank=True, default="")
    job = models.ForeignKey(AgencyJob, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "studio_message"
        ordering = ["created_at"]
        indexes = [models.Index(fields=["conversation", "created_at"], name="idx_message_conv_created")]

    def __str__(self):
        return f"Message({self.author_kind}): {self.body[:50]}"

    @property
    def sender_name(self) -> str:
        if self.author_kind == self.AuthorKind.AGENT:
            from . import team

            return team.name(self.agent or "account_manager")
        if self.author is not None:
            return self.author.name or self.author.email.split("@")[0]
        return "Team"
