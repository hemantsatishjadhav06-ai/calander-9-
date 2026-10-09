"""Creative memory: the learn job, the memory page, and the cycle that keeps it fresh."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.members.models import WorkspaceMembership
from apps.studio import autopilot, engine
from apps.studio.brand_defaults import ensure_profile
from apps.studio.jobtypes import learn
from apps.studio.models import AgencyJob, AgentRun, BrandProfile, CreativeInsight, StudioBrief
from apps.studio.tests.conftest import jpeg_bytes
from apps.studio.tests.test_insights import (
    agency_settings,
    drive,
    install_fake_agency,
    overspend,
    published_post,
)


@pytest.fixture
def agency(monkeypatch):
    return install_fake_agency(monkeypatch)


def _url(name, world, **kwargs):
    return reverse(name, kwargs={"workspace_id": world.workspace.id, **kwargs})


@pytest.fixture
def ranked(world, photo):
    """Six measured LinkedIn posts with pictures; the newest is 12× the others' scale."""
    posts = []
    for n, value in enumerate([1, 2, 3, 4, 5, 12]):
        image = photo(filename=f"post-{n}.jpg", data=jpeg_bytes(color=(10 * n, 80, 120)))
        posts.append(
            published_post(world, world.linkedin, days_ago=10 - n, value=value, image=image, caption=f"Hook {n}\nBody")
        )
    return posts


def _learn(world, **fields):
    return engine.create(world.workspace, "learn", title="Refresh", **fields)


# ---------------------------------------------------------------------------
# The learn job
# ---------------------------------------------------------------------------


def test_learning_ranks_pictured_posts_and_the_curator_writes_the_house_style(world, agency, ranked):
    from apps.composer.models import PostMedia

    best = ranked[-1]
    brief = StudioBrief.objects.create(
        workspace=world.workspace,
        author=world.owner,
        idea="x",
        post=best.post,
        status=StudioBrief.Status.APPROVED,
        design_spec={"template": "split", "grade": "duotone", "picture_style": "dusk", "picture_prompt": "towers"},
    )

    job = drive(_learn(world))

    assert job.status == AgencyJob.Status.DONE, job.error
    rows = CreativeInsight.objects.filter(workspace=world.workspace)
    assert rows.count() == 6
    top = rows.get(platform_post=best)
    assert top.score == pytest.approx(11 / 12, abs=1e-3) and top.ratio == pytest.approx(12 / 3.5, rel=1e-3)
    assert top.source == CreativeInsight.Source.STUDIO and brief.post_id == top.post_id
    assert top.features["template"] == "split" and top.features["picture_prompt"] == "towers"
    assert top.features["hook"] == "Hook 5"
    assert top.media_asset_id == PostMedia.objects.get(post=best.post).media_asset_id
    assert rows.exclude(pk=top.pk).first().source == CreativeInsight.Source.EXTERNAL
    # The curator looked at the top pictures and described them by the keys it was shown.
    shown = agency.calls["creative_curator"][0]["images"]
    assert 1 <= len(shown) <= learn.TOP_FOR_CURATOR
    assert rows.exclude(description="").count() == len(shown)
    profile = BrandProfile.objects.get(workspace=world.workspace)
    assert profile.house_style == agency.house_style and profile.house_style_updated_at is not None
    assert job.result["house_style_written"] == agency.house_style
    assert job.result["learned"][0].startswith("Your strongest recent post did 3.4×")
    curator = job.runs.get(agent="creative_curator")
    assert curator.status == AgentRun.Status.SUCCEEDED and curator.input_tokens == 1000


def test_a_house_style_a_person_wrote_is_kept_for_30_days(world, agency, ranked):
    profile = ensure_profile(world.workspace)
    BrandProfile.objects.filter(pk=profile.pk).update(
        house_style="Our own words about the look.", house_style_updated_at=timezone.now() - timedelta(days=3)
    )

    job = drive(_learn(world))

    profile.refresh_from_db()
    assert profile.house_style == "Our own words about the look."
    assert "kept the house style a person wrote" in job.runs.get(agent="creative_curator").summary
    assert CreativeInsight.objects.exclude(description="").exists()  # it still described the creatives

    BrandProfile.objects.filter(pk=profile.pk).update(house_style_updated_at=timezone.now() - timedelta(days=31))
    CreativeInsight.objects.update(description="", described_at=None)
    drive(_learn(world))
    profile.refresh_from_db()
    assert profile.house_style == agency.house_style


def test_the_curator_rewrites_its_own_house_style(world, agency, ranked):
    drive(_learn(world))
    agency.house_style = "A newer reading of the best work."
    CreativeInsight.objects.update(description="", described_at=None)

    drive(_learn(world))

    assert BrandProfile.objects.get(workspace=world.workspace).house_style == "A newer reading of the best work."


def test_references_keep_their_mark_and_new_ones_are_described(world, agency, ranked, photo):
    drive(_learn(world))
    marked = CreativeInsight.objects.filter(workspace=world.workspace).order_by("score").first()
    CreativeInsight.objects.filter(pk=marked.pk).update(is_reference=True, reference_note="The light")
    upload = CreativeInsight.objects.create(
        workspace=world.workspace,
        media_asset=photo(filename="ref.jpg"),
        source=CreativeInsight.Source.UPLOAD,
        is_reference=True,
    )

    drive(_learn(world))

    marked.refresh_from_db()
    upload.refresh_from_db()
    assert marked.is_reference and marked.reference_note == "The light"
    assert upload.description and upload.described_at
    last = agency.calls["creative_curator"][-1]
    assert [image["context"] for image in last["images"]] == [
        "A reference the team picked as their best designer's work."
    ]
    # The reference described last time is passed as text, with the person's note.
    assert any("Note from the team: The light" in line for line in last["described"])


def test_nothing_new_means_no_model_call(world, agency):
    job = drive(_learn(world))

    assert job.status == AgencyJob.Status.DONE
    assert "creative_curator" not in agency.calls
    assert job.runs.get(agent="creative_curator").status == AgentRun.Status.SKIPPED


def test_over_budget_the_curator_is_skipped(world, agency, ranked):
    agency_settings(world, monthly_budget_usd=5)
    overspend(world.workspace)

    job = drive(_learn(world))

    assert job.status == AgencyJob.Status.DONE
    assert "creative_curator" not in agency.calls
    assert "budget" in job.runs.get(agent="creative_curator").summary
    assert CreativeInsight.objects.filter(workspace=world.workspace).count() == 6  # ranking is free


def test_a_broken_picture_is_skipped_not_sent(world, agency, photo):
    CreativeInsight.objects.create(
        workspace=world.workspace,
        media_asset=photo(data=b"not an image at all", filename="broken.jpg"),
        source=CreativeInsight.Source.UPLOAD,
        is_reference=True,
    )
    good = CreativeInsight.objects.create(
        workspace=world.workspace, media_asset=photo(filename="good.jpg"), source="upload", is_reference=True
    )

    job = drive(_learn(world))

    assert job.status == AgencyJob.Status.DONE
    images = agency.calls["creative_curator"][0]["images"]
    assert len(images) == 1
    good.refresh_from_db()
    assert good.description


def test_another_workspaces_posts_are_never_learned(world, agency, photo):
    from apps.social_accounts.models import SocialAccount
    from apps.workspaces.models import Workspace

    other_ws = Workspace.objects.create(organization=world.org, name="Other")
    other = SocialAccount.objects.create(workspace=other_ws, platform="linkedin_company", account_platform_id="9")
    for n in range(6):
        published_post(world, other, days_ago=5 + n, value=n + 1, image=photo(filename=f"o{n}.jpg"), workspace=other_ws)

    drive(_learn(world))

    assert not CreativeInsight.objects.filter(workspace=world.workspace).exists()
    assert not CreativeInsight.objects.filter(workspace=other_ws).exists()


def test_a_failed_curator_fails_the_job_with_a_sentence(world, agency, ranked):
    agency.fail = {"creative_curator": "Claude is rate-limiting this account right now."}

    job = drive(_learn(world))

    assert job.status == AgencyJob.Status.FAILED and "rate-limiting" in job.error
    assert CreativeInsight.objects.filter(workspace=world.workspace).count() == 6


# ---------------------------------------------------------------------------
# The memory page
# ---------------------------------------------------------------------------


def test_the_memory_page_shows_style_references_and_best_posts(client, world, agency, ranked):
    drive(_learn(world))
    client.force_login(world.owner)

    html = client.get(_url("studio:memory", world)).content.decode()

    assert "Creative memory" in html and "Your best designer" in html and "Best-performing posts" in html
    assert agency.house_style in html and "creative memory curator" in html
    assert "Top 8%" in html and "3.4× usual" in html and "Use as reference" in html
    assert 'aria-current="page"' in html and "Refresh what we learned" in html


def test_clients_and_people_who_cant_create_posts_are_refused(client, world):
    client_user = world.viewer.__class__.objects.create_user(
        email="client@example.com", password="pw-12345678", name="Client", tos_accepted_at=timezone.now()
    )
    WorkspaceMembership.objects.create(user=client_user, workspace=world.workspace, workspace_role="client")
    for user in (client_user, world.viewer, world.outsider):
        client.force_login(user)
        assert client.get(_url("studio:memory", world)).status_code in (403, 404)
        assert client.post(_url("studio:memory_refresh", world)).status_code in (403, 404)


def test_use_as_reference_and_stop(client, world, agency, ranked):
    drive(_learn(world))
    insight = CreativeInsight.objects.filter(workspace=world.workspace).first()
    client.force_login(world.editor)

    client.post(_url("studio:memory_reference", world, insight_id=insight.id), {"learn": "1"})
    insight.refresh_from_db()
    assert insight.is_reference

    client.post(_url("studio:memory_reference", world, insight_id=insight.id), {"learn": "0"})
    insight.refresh_from_db()
    assert not insight.is_reference


def test_another_workspaces_creative_cant_be_toggled(client, world, photo):
    from apps.workspaces.models import Workspace

    other_ws = Workspace.objects.create(organization=world.org, name="Other")
    foreign = CreativeInsight.objects.create(workspace=other_ws, media_asset=photo(), source="upload")
    client.force_login(world.owner)

    response = client.post(_url("studio:memory_reference", world, insight_id=foreign.id), {"learn": "1"})

    assert response.status_code == 404
    foreign.refresh_from_db()
    assert not foreign.is_reference


def test_uploading_references(client, world):
    client.force_login(world.editor)
    picture = SimpleUploadedFile("best.jpg", jpeg_bytes(), content_type="image/jpeg")

    response = client.post(_url("studio:memory_upload", world), {"images": [picture], "note": "The calm layout"})

    assert response.status_code == 302
    insight = CreativeInsight.objects.get(workspace=world.workspace)
    assert insight.is_reference and insight.source == CreativeInsight.Source.UPLOAD
    assert insight.reference_note == "The calm layout"
    asset = insight.media_asset
    assert asset.workspace == world.workspace and asset.uploaded_by == world.editor and "studio-reference" in asset.tags


def test_a_non_picture_upload_is_rejected(client, world):
    client.force_login(world.editor)
    fake = SimpleUploadedFile("notes.jpg", b"%PDF-1.4 not a picture", content_type="image/jpeg")

    response = client.post(_url("studio:memory_upload", world), {"images": [fake]}, follow=True)

    assert not CreativeInsight.objects.exists()
    assert response.status_code in (200, 400)


def test_the_house_style_is_edited_by_managers_only(client, world):
    client.force_login(world.editor)
    response = client.post(_url("studio:memory_house_style", world), {"house_style": "Editor's look"})
    assert response.status_code == 403

    client.force_login(world.manager)
    client.post(_url("studio:memory_house_style", world), {"house_style": "  Warm dusk,   calm  type. "})
    profile = BrandProfile.objects.get(workspace=world.workspace)
    assert profile.house_style == "Warm dusk, calm type." and profile.house_style_updated_at is not None
    assert learn.person_holds_house_style(profile)


def test_refresh_queues_a_learn_job_within_budget(client, world, agency):
    client.force_login(world.editor)

    response = client.post(_url("studio:memory_refresh", world))

    job = AgencyJob.objects.get(workspace=world.workspace, kind="learn")
    assert response.status_code == 302 and str(job.pk) in response["Location"]
    assert job.requested_by == world.editor and job.status == AgencyJob.Status.QUEUED
    # A second press while it runs doesn't queue another.
    client.post(_url("studio:memory_refresh", world))
    assert AgencyJob.objects.filter(workspace=world.workspace, kind="learn").count() == 1


def test_refresh_is_refused_over_budget_or_without_claude(client, world, agency, settings):
    agency_settings(world, monthly_budget_usd=5)
    overspend(world.workspace)
    client.force_login(world.owner)

    response = client.post(_url("studio:memory_refresh", world), follow=True)
    assert "budget" in response.content.decode()
    assert not AgencyJob.objects.filter(workspace=world.workspace, kind="learn", status="queued").exists()

    settings.ANTHROPIC_API_KEY = ""
    response = client.post(_url("studio:memory_refresh", world), follow=True)
    assert not AgencyJob.objects.filter(workspace=world.workspace, kind="learn", status="queued").exists()


# ---------------------------------------------------------------------------
# The cycle keeps memory fresh
# ---------------------------------------------------------------------------


def test_memory_is_refreshed_when_there_is_something_new(world, agency, ranked):
    ensure_profile(world.workspace)

    assert autopilot.refresh_memory_due() == 1
    assert autopilot.refresh_memory_due() == 0  # one is already queued
    job = AgencyJob.objects.get(workspace=world.workspace, kind="learn")
    drive(job)

    # Within a day, nothing more; after a day with no new posts or references, nothing either.
    assert autopilot.refresh_memory_due() == 0
    AgencyJob.objects.filter(pk=job.pk).update(created_at=timezone.now() - timedelta(days=2))
    assert autopilot.refresh_memory_due() == 0

    CreativeInsight.objects.filter(pk=CreativeInsight.objects.first().pk).update(
        is_reference=True, description="", described_at=None
    )
    assert autopilot.refresh_memory_due() == 1


def test_memory_refresh_skips_archived_over_budget_and_unused_workspaces(world, agency, ranked):
    from apps.organizations.models import Organization

    # No brand profile: the Studio isn't used here.
    assert autopilot.refresh_memory_due() == 0

    ensure_profile(world.workspace)
    world.workspace.is_archived = True
    world.workspace.save(update_fields=["is_archived"])
    assert autopilot.refresh_memory_due() == 0

    world.workspace.is_archived = False
    world.workspace.save(update_fields=["is_archived"])
    Organization.objects.filter(pk=world.org.pk).update(deletion_requested_at=timezone.now())
    assert autopilot.refresh_memory_due() == 0

    Organization.objects.filter(pk=world.org.pk).update(deletion_requested_at=None)
    agency_settings(world, monthly_budget_usd=5)
    overspend(world.workspace)
    assert autopilot.refresh_memory_due() == 0
