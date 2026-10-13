"""Measured graphic text loss stops approval handoff without blocking advisory QA."""

import io

import pytest
from PIL import Image

from apps.composer.models import PlatformPost, Post
from apps.studio import design, pipeline, services
from apps.studio.brand_defaults import ensure_profile
from apps.studio.models import CreativeInsight, StudioBrief
from apps.studio.tests.conftest import design_answer, jpeg_bytes, make_brief, run_all

LOOK = design.Look(
    primary=(8, 29, 74), accent=(204, 167, 79), font="outfit", wordmark="NEOPOLIS", domain="neopolisinfra.com"
)


@pytest.mark.parametrize("template", design.TEMPLATES)
@pytest.mark.parametrize("fmt", list(design.CANVASES))
def test_readable_copy_fits_every_layout_and_canvas(template, fmt):
    with design.collect_text_issues() as issues:
        graphic = design.render(design_answer(template=template, format=fmt).model_dump(), LOOK, jpeg_bytes())
    assert issues == []
    with Image.open(io.BytesIO(graphic)) as image:
        assert image.size == design.canvas_size(fmt)


def test_character_limit_loss_is_measured_before_the_spec_is_shortened():
    with design.collect_text_issues() as issues:
        design.render(design_answer(headline="A precise point " * 20).model_dump(), LOOK)
    assert any(
        issue["field"] == "headline" and issue["reason"] == "truncated" and issue["blocking"] for issue in issues
    )


def test_fitted_text_loss_is_measured_even_below_the_character_limit():
    headline = "W" * 90
    assert len(headline) < 160
    with design.collect_text_issues() as issues:
        design.render(design_answer(template="split", format="landscape", headline=headline).model_dump(), LOOK)
    assert any(issue["field"] == "headline" and issue["reason"] == "ellipsis" for issue in issues)


def test_the_call_to_action_cannot_silently_lose_its_last_characters():
    with design.collect_text_issues() as issues:
        design.render(design_answer(cta_label="W" * 50).model_dump(), LOOK)
    assert any(
        issue["field"] == "cta_label" and issue["reason"] == "truncated" and issue["blocking"] for issue in issues
    )


def test_statistic_labels_are_measured_with_the_actual_letter_spacing():
    with design.collect_text_issues() as issues:
        design.render(design_answer(template="stat", format="landscape", stat_label="M" * 26).model_dump(), LOOK)
    assert any(issue["field"] == "stat_label" and issue["reason"] == "overflow" for issue in issues)


@pytest.mark.parametrize("template", ["editorial", "split", "statement"])
def test_unused_statistic_fields_cannot_block_a_layout_that_does_not_display_them(template):
    with design.collect_text_issues() as issues:
        design.render(design_answer(template=template, stat_value="W" * 40, stat_label="W" * 90).model_dump(), LOOK)
    assert issues == []


def test_literal_ellipsis_in_fitting_copy_is_not_treated_as_text_loss():
    with design.collect_text_issues() as issues:
        design.render(design_answer(headline="Before you buy...").model_dump(), LOOK)
    assert not any(issue["field"] == "headline" for issue in issues)


def test_a_missing_headline_is_reported_instead_of_passing_the_brand_name_as_copy():
    with design.collect_text_issues() as issues:
        design.render(design_answer(headline=" ").model_dump(), LOOK)
    assert any(issue["field"] == "headline" and issue["reason"] == "missing" for issue in issues)


def test_optional_kicker_loss_is_an_advisory_design_note():
    with design.collect_text_issues() as issues:
        design.render(design_answer(template="editorial", kicker="A long descriptive label " * 5).model_dump(), LOOK)
    assert any(issue["field"] == "kicker" and not issue["blocking"] for issue in issues)
    assert not any(issue["blocking"] for issue in issues)


def test_diagnostic_collectors_do_not_mix_nested_renders():
    with design.collect_text_issues() as outer:
        design.render(design_answer(headline=" ").model_dump(), LOOK)
        before = list(outer)
        with design.collect_text_issues() as inner:
            design.render(design_answer(cta_label="W" * 50).model_dump(), LOOK)
        assert outer == before
        assert any(issue["field"] == "cta_label" for issue in inner)


def test_art_direction_receives_curated_reference_images_and_memory(world, photo, fake_team):
    profile = ensure_profile(world.workspace)
    profile.house_style = "Quiet architectural light and a single strong headline."
    profile.save(update_fields=["house_style"])
    image = photo()
    CreativeInsight.objects.create(
        workspace=world.workspace,
        media_asset=image,
        is_reference=True,
        description="Architectural detail, warm light, generous space for the headline.",
        reference_note="Keep the restrained spacing.",
    )
    brief = run_all(make_brief(world))
    assert brief.status == StudioBrief.Status.READY, brief.error
    art = fake_team.calls["art_director"][0]
    assert art["creative_memory"]["house_style"] == profile.house_style
    assert "generous space" in art["creative_memory"]["references"][0]
    assert art["reference_images"] == [jpeg_bytes()]


def test_essential_graphic_copy_loss_cannot_create_an_approval_post(world, fake_team):
    fake_team.design = {"headline": "W" * 90, "template": "split", "format": "landscape"}
    brief = run_all(make_brief(world))
    assert brief.status == StudioBrief.Status.FAILED and brief.stage == "handoff"
    assert "headline" in brief.error and "fit in full" in brief.error
    assert not Post.objects.filter(workspace=world.workspace).exists()
    assert not PlatformPost.objects.exists()
    assert any(check.get("blocks_handoff") for check in brief.review_notes["qa"]["checks"])
    assert any(issue["field"] == "headline" for issue in fake_team.calls["reviewer"][0]["spec"]["_render_issues"])


def test_requesting_shorter_graphic_copy_recovers_without_automatic_retry_loops(world, fake_team):
    fake_team.design = {"headline": "W" * 90, "template": "split", "format": "landscape"}
    brief = run_all(make_brief(world))
    assert brief.status == StudioBrief.Status.FAILED
    fake_team.design = {"headline": "Check the title first", "template": "split", "format": "landscape"}
    services.request_changes(brief, "Shorten the headline; keep all contact details.")
    brief = run_all(brief)
    assert brief.status == StudioBrief.Status.READY, brief.error
    assert brief.revision == 2 and brief.auto_revisions == 0
    assert brief.post.platform_posts.get().status == PlatformPost.Status.PENDING_REVIEW
    assert brief.review_notes["render"]["issues"] == []


def test_advisory_qa_and_optional_kicker_loss_leave_the_post_for_a_human(world, fake_team):
    fake_team.design = {"template": "editorial", "kicker": "A long descriptive label " * 5}
    fake_team.copy = {"alt_text": ""}
    brief = run_all(make_brief(world))
    assert brief.status == StudioBrief.Status.READY, brief.error
    assert any(check["name"] == "Alt text" and not check["passed"] for check in brief.review_notes["qa"]["checks"])
    assert not any(check.get("blocks_handoff") for check in brief.review_notes["qa"]["checks"])
    assert brief.post.platform_posts.get().status == PlatformPost.Status.PENDING_REVIEW


def test_old_graphics_without_a_report_are_remeasured_before_handoff(world, fake_team):
    fake_team.design = {"headline": "W" * 90, "template": "split", "format": "landscape"}
    brief = make_brief(world)
    while brief.stage != "handoff":
        pipeline.run_step(str(brief.pk), brief.revision, brief.stage)
        brief.refresh_from_db()
        assert brief.is_active, brief.error
    StudioBrief.objects.filter(pk=brief.pk).update(review_notes={})
    pipeline.run_step(str(brief.pk), brief.revision, "handoff")
    brief.refresh_from_db()
    assert brief.status == StudioBrief.Status.FAILED and "headline" in brief.error
    assert brief.post_id is None
