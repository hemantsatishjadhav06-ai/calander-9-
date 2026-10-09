"""Fixtures for the AI Studio tests: a workspace with people and accounts, and a fake agent team.

No test talks to Anthropic or fal.ai. ``fake_team`` replaces the four agents
with recorders that return canned, schema-valid answers, so the pipeline,
the hand-off and the approval path run for real against the database.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import pytest
from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image

from apps.accounts.models import User
from apps.media_library.models import MediaAsset
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.studio import agents, llm, pipeline
from apps.studio.roles import creative
from apps.studio.schemas import Concept, CopyAnswer, DesignAnswer, ReviewAnswer, ReviewCheck, StrategistAnswer
from apps.workspaces.models import Workspace


@dataclass
class World:
    org: Organization
    workspace: Workspace
    owner: User
    manager: User
    editor: User
    viewer: User
    outsider: User
    linkedin: SocialAccount
    x: SocialAccount


def _user(email, name):
    return User.objects.create_user(email=email, password="pw-12345678", name=name, tos_accepted_at=timezone.now())


@pytest.fixture
def world(db, settings):
    settings.ANTHROPIC_API_KEY = "sk-ant-test"
    settings.FAL_KEY = ""
    org = Organization.objects.create(name="Brands")
    ws = Workspace.objects.create(organization=org, name="Neopolis", timezone="Asia/Kolkata")
    users = {}
    for role in ("owner", "manager", "editor", "viewer"):
        user = _user(f"{role}@example.com", role.title())
        OrgMembership.objects.create(user=user, organization=org, org_role="owner" if role == "owner" else "member")
        WorkspaceMembership.objects.create(user=user, workspace=ws, workspace_role=role)
        users[role] = user
    linkedin = SocialAccount.objects.create(
        workspace=ws,
        platform="linkedin_company",
        account_platform_id="98765",
        account_name="Neopolis Infra",
        oauth_access_token="li-token",
    )
    x = SocialAccount.objects.create(
        workspace=ws,
        platform="x",
        account_platform_id="111",
        account_name="neopolisinfra",
        oauth_access_token="x-token",
    )
    return World(
        org,
        ws,
        users["owner"],
        users["manager"],
        users["editor"],
        users["viewer"],
        _user("o@example.com", "Out"),
        linkedin,
        x,
    )


def jpeg_bytes(width=1200, height=900, color=(90, 120, 160)):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def photo(world):
    def make(data=None, filename="tower.jpg", **fields):
        data = data if data is not None else jpeg_bytes()
        asset = MediaAsset.objects.create(
            organization=world.org,
            workspace=world.workspace,
            uploaded_by=world.owner,
            filename=filename,
            media_type=MediaAsset.MediaType.IMAGE,
            file_size=len(data),
            **fields,
        )
        asset.file.save(filename, ContentFile(data), save=True)
        return asset

    return make


def _result(output):
    return llm.AgentResult(
        output=output,
        model="claude-opus-5-5",
        input_tokens=1200,
        output_tokens=600,
        cache_read_tokens=800,
        duration_ms=1500,
    )


def concepts_answer():
    return StrategistAnswer(
        concepts=[
            Concept(
                title="What a landlord's share is",
                hook="Same tower, same spec — so why is one flat cheaper?",
                angle="Explain the landowner's allocation in a joint development.",
                key_points=["Joint development splits flats", "Same building and amenities"],
                post_format="single_image",
                rationale="Answers the buyer's first question.",
                recommended=False,
            ),
            Concept(
                title="The 8–14% gap",
                hook="Landlord shares typically sit 8–14% under comparable resale.",
                angle="Lead with the number from the facts.",
                key_points=["The gap", "Why it exists"],
                post_format="stat",
                rationale="A concrete number stops the scroll.",
                recommended=True,
            ),
            Concept(
                title="Title first",
                hook="We check the title before you see the flat.",
                angle="Trust through process.",
                key_points=["Title", "Plans", "Allocation in writing"],
                post_format="tips",
                rationale="Reassures cautious buyers.",
                recommended=False,
            ),
        ]
    )


def copy_answer(**overrides):
    fields = {
        "caption": (
            "Landlord shares typically sit 8–14% under comparable resale.\n\n"
            "**Same tower.** Same spec. A fairer number.\n\n"
            "WhatsApp or call +91 95336 86567.\n\n#LandlordShare #WestHyderabad"
        ),
        "hashtags": ["LandlordShare", "#West Hyderabad", "#HyderabadRealEstate", "#LandlordShare"],
        "first_comment": "How the share works: https://www.neopolisinfra.com/#/the-share",
        "short_caption": "Landlord shares: same tower, typically 8–14% under resale. https://www.neopolisinfra.com/#/the-share",
        "alt_text": "Navy graphic: 8–14% under comparable resale, Neopolis Infra.",
        "headline": "Same tower. A fairer number.",
        "subheadline": "Landlord shares typically sit 8–14% under comparable resale.",
        "kicker": "Landlord share",
        "cta_label": "WhatsApp +91 95336 86567",
        "stat_value": "8–14%",
        "stat_label": "under comparable resale",
        "notes": "Led with the number from the facts.",
    }
    fields.update(overrides)
    return CopyAnswer(**fields)


def design_answer(**overrides):
    fields = {
        "template": "stat",
        "format": "portrait",
        "grade": "brand_tint",
        "use_picture": True,
        "picture_style": "Architectural photograph at blue hour, cool crisp light",
        "picture_prompt": "Modern residential towers in Kokapet at blue hour, wide shot, calm sky",
        "kicker": "Landlord share",
        "headline": "Same tower. A fairer number.",
        "subheadline": "Typically 8–14% under comparable resale.",
        "stat_value": "8–14%",
        "stat_label": "under comparable resale",
        "cta_label": "WhatsApp +91 95336 86567",
        "overlay_strength": 0.7,
        "consistency_notes": "First post of the series.",
        "design_rationale": "The number carries the message.",
    }
    fields.update(overrides)
    return DesignAnswer(**fields)


def review_answer(verdict="approve", **overrides):
    fields = {
        "verdict": verdict,
        "score": 9 if verdict == "approve" else 5,
        "checks": [ReviewCheck(name="Facts", passed=verdict == "approve", note="All from the facts.")],
        "risk_flags": [] if verdict == "approve" else ["'best price' is not in the facts"],
        "copy_fixes": [] if verdict == "approve" else ["Remove 'best price'."],
        "design_fixes": [],
        "regenerate_picture": False,
        "summary": "Clear and on brand." if verdict == "approve" else "One unsupported claim.",
    }
    fields.update(overrides)
    return ReviewAnswer(**fields)


@dataclass
class FakeTeam:
    calls: dict = field(
        default_factory=lambda: {"strategist": [], "copywriter": [], "art_director": [], "reviewer": []}
    )
    verdicts: list = field(default_factory=lambda: ["approve"])
    design: dict = field(default_factory=dict)
    copy: dict = field(default_factory=dict)
    fail: dict = field(default_factory=dict)

    def _maybe_fail(self, agent):
        message = self.fail.get(agent)
        if message:
            raise llm.StudioAgentError(message)

    def strategist(self, brief, profile, recent):
        self.calls["strategist"].append({"brief": brief, "recent": recent})
        self._maybe_fail("strategist")
        return _result(concepts_answer())

    def copywriter(self, brief, profile, concept, recent, *, previous=None, feedback="", fixes=None):
        self.calls["copywriter"].append(
            {"concept": concept, "previous": previous, "feedback": feedback, "fixes": list(fixes or [])}
        )
        self._maybe_fail("copywriter")
        return _result(copy_answer(**self.copy))

    def art_director(self, brief, profile, concept, post_copy, reference, **kwargs):
        self.calls["art_director"].append({"reference": reference, **kwargs})
        self._maybe_fail("art_director")
        return _result(design_answer(**self.design))

    def reviewer(self, brief, profile, post_copy, spec, graphic, reference_image=None):
        self.calls["reviewer"].append({"graphic": graphic, "reference_image": reference_image, "spec": spec})
        self._maybe_fail("reviewer")
        verdict = self.verdicts.pop(0) if len(self.verdicts) > 1 else self.verdicts[0]
        return _result(review_answer(verdict))

    def prompt_engineer(self, profile, spec, memory, *, reference_images=None):
        self.calls.setdefault("prompt_engineer", []).append(
            {"spec": spec, "memory": memory, "images": reference_images}
        )
        self._maybe_fail("prompt_engineer")
        return _result(
            creative.PromptAnswer(
                prompt=(
                    "Warm evening light on contemporary residential towers seen from street level, calm sky "
                    "in the upper half, navy shadows, small figures walking away, 35mm, light haze"
                ),
                picture_style="Warm dusk architectural photography, 35mm, navy shadows",
                references_used="The warm dusk light of the brand's best post.",
            )
        )

    def channel_editor(self, profile, post_copy, destinations):
        self.calls.setdefault("channel_editor", []).append({"destinations": destinations})
        self._maybe_fail("channel_editor")
        versions = [
            creative.ChannelVersion(platform=d["platform"], caption=f"Version for {d['platform']}. Link in bio.")
            for d in destinations
        ]
        return _result(creative.ChannelAnswer(versions=versions, notes="Shorter for Instagram."))


@pytest.fixture
def fake_team(monkeypatch):
    team = FakeTeam()
    for name in ("strategist", "copywriter", "art_director", "reviewer"):
        monkeypatch.setattr(agents, name, getattr(team, name))
    for name in ("prompt_engineer", "channel_editor"):
        monkeypatch.setattr(creative, name, getattr(team, name))
    queued = []
    monkeypatch.setattr(pipeline, "enqueue", lambda brief, stage: queued.append((brief.pk, brief.revision, stage)))
    team.queued = queued  # type: ignore[attr-defined]
    return team


def run_all(brief, limit=30):
    """Drive the pipeline synchronously until the team stops."""
    for _ in range(limit):
        brief.refresh_from_db()
        if not brief.is_active:
            return brief
        pipeline.run_step(str(brief.pk), brief.revision, brief.stage)
    raise AssertionError("The pipeline did not finish")


def make_brief(world, *, accounts=None, author=None, **fields):
    from apps.studio import services

    fields.setdefault("idea", "Explain landlord shares to first-time buyers")
    return services.create_brief(
        world.workspace,
        author or world.editor,
        accounts=accounts if accounts is not None else [world.linkedin],
        **fields,
    )
