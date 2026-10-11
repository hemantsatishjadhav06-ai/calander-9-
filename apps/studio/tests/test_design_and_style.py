"""The graphic designer, the "same look as the last post" lock, and brand defaults.

The designer is deterministic Pillow code, so these tests look at real
renders: sizes, that type stays inside the typeface, that layouts fall back
sensibly. The lock picks what the next graphic follows from real rows.
"""

import io
from datetime import timedelta

import pytest
from django.utils import timezone
from PIL import Image

from apps.composer.models import PlatformPost, Post, PostMedia
from apps.settings_manager.models import WorkspaceSetting
from apps.studio import design, style
from apps.studio.brand_defaults import defaults_for, ensure_profile
from apps.studio.models import StudioBrief
from apps.studio.tests.conftest import jpeg_bytes, make_brief, run_all
from apps.workspaces.brands import BRAND_KEY

LOOK = design.Look(
    primary=(8, 29, 74), accent=(255, 102, 0), font="oswald", wordmark="NEOPOLIS", domain="neopolisinfra.com"
)

SPEC = {
    "kicker": "Landlord share",
    "headline": "Same tower. A fairer number.",
    "subheadline": "Landlord shares typically sit 8–14% under comparable resale.",
    "stat_value": "8–14%",
    "stat_label": "under comparable resale",
    "cta_label": "WhatsApp +91 95336 86567",
}


def _image(data):
    return Image.open(io.BytesIO(data))


class TestRendering:
    @pytest.mark.parametrize("template", design.TEMPLATES)
    @pytest.mark.parametrize("fmt", ["portrait", "square", "landscape"])
    def test_every_layout_renders_at_its_canvas_size(self, template, fmt):
        data = design.render({**SPEC, "template": template, "format": fmt}, LOOK, jpeg_bytes())

        with _image(data) as image:
            assert image.format == "JPEG"
            assert image.size == design.canvas_size(fmt)

    def test_without_a_picture_the_brand_background_is_used(self):
        with _image(design.render({**SPEC, "template": "editorial"}, LOOK)) as image:
            assert image.size == (1080, 1350)

    def test_a_broken_picture_is_an_error_not_a_silent_blank(self):
        with pytest.raises((ValueError, OSError)):
            design.render({**SPEC, "template": "editorial"}, LOOK, b"not an image")

    def test_the_picture_box_is_what_the_layout_shows(self):
        assert design.picture_box("editorial", "portrait") == (1080, 1350)
        assert design.picture_box("split", "portrait") == (1080, round(1350 * design.SPLIT_PORTRAIT))
        assert design.picture_box("split", "landscape") == (round(1200 * design.SPLIT_SIDE), 628)
        assert design.picture_box("stat", "square") == (1080, round(1080 * design.STAT_SQUARE))


class TestTheSpecIsCleaned:
    def test_a_stat_layout_without_a_number_becomes_editorial(self):
        spec = design.normalise_spec({**SPEC, "template": "stat", "stat_value": " "}, LOOK)
        assert spec["template"] == "editorial"

    def test_unknown_values_fall_back_and_the_scrim_is_clamped(self):
        spec = design.normalise_spec(
            {"template": "collage", "format": "story", "grade": "neon", "overlay_strength": 3}, LOOK
        )
        assert (spec["template"], spec["format"], spec["grade"]) == ("editorial", "portrait", "brand_tint")
        assert spec["overlay"] == 0.9
        assert spec["headline"] == "NEOPOLIS"  # never an empty headline

    def test_type_only_uses_characters_the_typeface_has(self):
        # Oswald has no arrow, and no one wants a tofu box in an ad; emoji and
        # dingbats (check marks included) are dropped.
        assert design.clean_text("Book now → today ✓ 🎉", "oswald") == "Book now – today"
        # Outfit has no rupee sign.
        assert design.clean_text("From ₹85 lakh", "outfit") == "From Rs 85 lakh"

    def test_long_text_shrinks_then_ends_with_an_ellipsis_inside_its_box(self):
        text = "A very long headline that keeps going " * 6
        font, lines = design.fit_text(text, "oswald", weight=700, max_width=500, max_lines=2, start=80, minimum=40)

        assert len(lines) == 2
        assert font.size == 40
        assert lines[-1].endswith("...")
        assert all(font.getlength(line) <= 500 for line in lines)


class TestColour:
    def test_text_colour_is_lifted_until_it_reads(self):
        navy = (8, 29, 74)
        lifted = design.readable((20, 40, 90), navy, minimum=4.5)
        assert design.contrast(lifted, navy) >= 4.5

    def test_a_light_primary_still_gets_a_dark_panel_for_white_type(self):
        look = design.Look(primary=(250, 240, 200), accent=(0, 0, 0), font="outfit", wordmark="X")
        assert design.is_dark(look.panel)

    def test_dominant_colours(self):
        top = design.hex_to_rgb(design.dominant_colours(jpeg_bytes(color=(8, 29, 74)))[0])
        assert all(abs(a - b) <= 4 for a, b in zip(top, (8, 29, 74), strict=True))  # JPEG shifts it a little
        assert design.dominant_colours(b"nope") == []


@pytest.fixture
def published_photo_post(world, photo):
    """A post with a picture that went out without the Studio."""

    def make(when):
        post = Post.objects.create(workspace=world.workspace, author=world.owner, caption="Site visit Saturday")
        PostMedia.objects.create(post=post, media_asset=photo(data=jpeg_bytes(color=(200, 120, 40))), position=0)
        PlatformPost.objects.create(post=post, social_account=world.linkedin, status="published", published_at=when)
        Post.objects.filter(pk=post.pk).update(published_at=when)
        return post

    return make


class TestWhichLookTheNextGraphicFollows:
    def test_with_nothing_posted_it_is_the_brand_profile(self, world, fake_team):
        brief = make_brief(world)
        reference = style.resolve(brief, ensure_profile(world.workspace))

        assert reference.kind == "brand"
        assert reference.defaults["template"] == ensure_profile(world.workspace).default_template

    def test_a_post_made_outside_the_studio_is_matched_by_eye(self, world, fake_team, published_photo_post):
        post = published_photo_post(timezone.now() - timedelta(hours=1))
        brief = make_brief(world)

        reference = style.resolve(brief, ensure_profile(world.workspace))

        assert reference.kind == "post"
        assert reference.post_id == str(post.pk)
        assert reference.image is not None and reference.palette
        assert reference.locked == {}  # nothing to copy exactly: the art director looks at it

    def test_the_most_recent_of_the_two_wins(self, world, fake_team, published_photo_post):
        first = run_all(make_brief(world, idea="First"))
        published_photo_post(timezone.now() + timedelta(minutes=5))
        brief = make_brief(world, idea="Second")

        assert style.resolve(brief, ensure_profile(world.workspace)).kind == "post"

        StudioBrief.objects.filter(pk=first.pk).update(finished_at=timezone.now() + timedelta(hours=1))
        reference = style.resolve(brief, ensure_profile(world.workspace))
        assert reference.kind == "studio"
        assert reference.locked["template"] == "stat"

    def test_the_lock_overrides_only_the_look(self):
        reference = style.StyleReference(kind="studio", label="", locked={"template": "split", "grade": "duotone"})
        spec = style.apply_lock({"template": "stat", "grade": "natural", "headline": "New words"}, reference)

        assert spec == {"template": "split", "grade": "duotone", "headline": "New words"}
        assert style.apply_lock({"template": "stat"}, style.StyleReference(kind="post", label="")) == {
            "template": "stat"
        }

    def test_the_brief_form_previews_what_it_will_follow(self, world, fake_team, published_photo_post):
        assert style.preview(world.workspace)["asset"] is None
        published_photo_post(timezone.now())

        preview = style.preview(world.workspace)

        assert "last post with a picture" in preview["label"]
        assert preview["asset"] is not None


class TestBrandDefaults:
    def test_a_known_brand_starts_from_its_real_details(self, world):
        WorkspaceSetting.objects.create(workspace=world.workspace, key=BRAND_KEY, value="neopolis")

        profile = ensure_profile(world.workspace)

        assert profile.display_font == "oswald"
        assert "8–14%" in profile.facts
        assert ensure_profile(world.workspace).pk == profile.pk  # created once

    def test_any_other_workspace_starts_from_its_own_settings(self, world):
        defaults = defaults_for(world.workspace)

        assert defaults["brand_name"] == "Neopolis"
        assert defaults["wordmark"] == "NEOPOLIS"
        assert defaults["display_font"] in design.FONT_FILES
