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
        HANDOFF = "handoff", "Producer"
        DONE = "done", "Done"

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
    """One agent's turn on a brief: what it made, how long it took, what it cost."""

    class Agent(models.TextChoices):
        STRATEGIST = "strategist", "Strategist"
        COPYWRITER = "copywriter", "Copywriter"
        ART_DIRECTOR = "art_director", "Art director"
        ILLUSTRATOR = "illustrator", "Illustrator"
        DESIGNER = "designer", "Designer"
        REVIEWER = "reviewer", "Brand reviewer"
        PRODUCER = "producer", "Producer"

    class Status(models.TextChoices):
        RUNNING = "running", "Working"
        SUCCEEDED = "succeeded", "Done"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brief = models.ForeignKey(StudioBrief, on_delete=models.CASCADE, related_name="runs")
    revision = models.PositiveIntegerField(default=1)
    agent = models.CharField(max_length=20, choices=Agent.choices)
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

    def __str__(self):
        return f"AgentRun({self.agent} r{self.revision}): {self.status}"

    @property
    def seconds(self) -> int:
        return round(self.duration_ms / 1000)
