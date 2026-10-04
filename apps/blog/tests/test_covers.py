"""The designed cover: what the publisher writes as the hero and what the dashboard shows."""

import io

import pytest
from django.urls import reverse
from PIL import Image

from apps.blog import services
from apps.blog.covers import (
    CANVAS,
    TITLE_MAX_LINES,
    TITLE_MIN_SIZE,
    brand_for,
    compose_cover,
    cover_for_post,
    fit_title,
    hero_image_bytes,
)
from apps.blog.models import BlogPost
from apps.blog.renderers import PostContent, render_post_page
from apps.blog.tests.conftest import make_post, png_bytes


def _open(data):
    return Image.open(io.BytesIO(data))


def _close(a, b, tolerance=6):
    """JPEG compression nudges single channels by a unit or two."""
    return all(abs(x - y) <= tolerance for x, y in zip(a, b, strict=True))


def _photo(width=2000, height=1200):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (120, 160, 200)).save(buf, format="JPEG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# compose_cover
# ---------------------------------------------------------------------------


def test_cover_is_a_1600x900_jpeg_over_the_picture():
    data = compose_cover(title="Flats in Kokapet 2026", category="Area Guide", picture=_photo())
    image = _open(data)
    assert image.format == "JPEG" and image.size == CANVAS and image.mode == "RGB"
    # The picture shows through on the right; the scrim darkens the left where the type sits.
    right = image.getpixel((1500, 120))
    left = image.getpixel((60, 450))
    assert sum(right) > sum(left)
    # The brand strip runs along the foot in the accent colour.
    assert _close(image.getpixel((800, 896)), brand_for("neopolis_static").accent)


def test_cover_without_a_picture_uses_the_brand_background():
    data = compose_cover(title="Are landlord share flats safe?", picture=None, slug="safe")
    image = _open(data)
    assert image.size == CANVAS
    r, g, b = image.getpixel((300, 300))
    assert b > r and b > g  # navy, not white


def test_same_inputs_give_the_same_bytes():
    kwargs = {"title": "Same title", "category": "Guide", "picture": _photo(), "slug": "same"}
    assert compose_cover(**kwargs) == compose_cover(**kwargs)
    assert compose_cover(**kwargs) != compose_cover(**{**kwargs, "title": "Other title"})


def test_every_site_kind_has_a_brand_and_renders():
    for kind in ("neopolis_static", "morespace_static"):
        data = compose_cover(title="Kokapet vs Financial District", site_kind=kind, picture=None)
        image = _open(data)
        assert _close(image.getpixel((800, 896)), brand_for(kind).accent)
    assert brand_for("unknown") is brand_for("neopolis_static")


def test_a_png_with_transparency_and_a_portrait_picture_are_cover_cropped():
    assert _open(compose_cover(title="PNG", picture=png_bytes(800, 1600, "RGBA"))).size == CANVAS
    assert _open(compose_cover(title="Tiny", picture=png_bytes(200, 100, "RGB"))).size == CANVAS


def test_a_non_image_is_refused():
    with pytest.raises(ValueError, match="could not be read as an image"):
        compose_cover(title="Bad", picture=b"not an image")


# ---------------------------------------------------------------------------
# Title fitting
# ---------------------------------------------------------------------------


def test_short_titles_use_the_largest_size_and_long_ones_shrink_to_fit():
    big_font, big_lines = fit_title("Flats in Kokapet", "Oswald-Variable.ttf")
    long_font, long_lines = fit_title(
        "Home Loan on Landlord Share Flats in Hyderabad: Eligibility, Process & Documents (2026)",
        "Oswald-Variable.ttf",
    )
    assert big_lines == ["Flats in Kokapet"]
    assert len(long_lines) <= TITLE_MAX_LINES and long_font.size < big_font.size
    assert long_font.size >= TITLE_MIN_SIZE


def test_an_absurdly_long_title_is_cut_with_an_ellipsis_instead_of_overflowing():
    title = " ".join(["Verylongword"] * 60)
    font, lines = fit_title(title, "Oswald-Variable.ttf")
    assert len(lines) == TITLE_MAX_LINES and lines[-1].endswith("…")
    assert font.size == TITLE_MIN_SIZE
    assert all(font.getlength(line) <= 1180 for line in lines)
    _open(compose_cover(title=title))  # and it still renders


def test_an_empty_title_renders_as_untitled():
    assert fit_title("   ", "Oswald-Variable.ttf")[1] == ["Untitled"]


# ---------------------------------------------------------------------------
# Posts: what the publisher gets
# ---------------------------------------------------------------------------


def test_designed_posts_always_have_a_hero_and_plain_ones_only_with_a_picture(world, image_asset):
    designed = make_post(world, cover_style="designed")
    plain = make_post(world, slug="plain", cover_style="plain")
    with_picture = make_post(
        world, slug="picture", cover_style="plain", featured_image=image_asset(), featured_image_alt="Towers"
    )

    designed_content = services.post_content(designed)
    assert designed_content.cover_style == "designed" and designed_content.has_image
    assert designed_content.card().has_image
    assert not services.post_content(plain).has_image
    assert services.post_content(with_picture).has_image

    hero = _open(hero_image_bytes(designed, designed_content))
    assert hero.size == CANVAS
    assert hero_image_bytes(plain, services.post_content(plain)) is None
    plain_hero = _open(hero_image_bytes(with_picture, services.post_content(with_picture)))
    assert plain_hero.width == 1600 and plain_hero.height == 800  # the picture as uploaded, resized


def test_designed_cover_puts_the_picture_behind_the_title(world, image_asset):
    post = make_post(world, cover_style="designed", featured_image=image_asset(_photo()), featured_image_alt="Sky")
    data = cover_for_post(post)
    assert _open(data).size == CANVAS
    # Rendering is from the content snapshot: the same snapshot gives the same cover.
    assert cover_for_post(post, PostContent.from_post(post)) == data


def test_cover_style_is_part_of_the_fingerprint_and_defaults_to_designed(world):
    post = make_post(world)  # the fixture pins "plain"
    before = services.fingerprint(post)
    post = services.update_content(post, world.editor, cover_style="designed")
    assert post.revision == 2 and services.fingerprint(post) != before
    assert BlogPost._meta.get_field("cover_style").default == BlogPost.CoverStyle.DESIGNED
    fresh = services.create_post(
        workspace=world.workspace, site=world.neopolis, author=world.editor, title="New", slug="new", body="b"
    )
    assert fresh.cover_style == "designed"


def test_the_page_markup_uses_the_cover_as_hero_and_og_image(world):
    post = make_post(world, cover_style="designed")
    page = render_post_page(post.site, services.post_content(post))
    assert '<div class="ahero"><img src="img/flats-in-kokapet-2026-hero.jpg?v=1"' in page
    assert 'og:image" content="https://www.neopolisinfra.com/blog/img/flats-in-kokapet-2026-hero.jpg"' in page


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def _url(name, world, post):
    return reverse(f"blog:{name}", kwargs={"workspace_id": world.workspace.id, "post_id": post.id})


def test_cover_endpoint_serves_the_designed_jpeg_privately(client, world):
    post = make_post(world, cover_style="designed")
    client.force_login(world.viewer)
    response = client.get(_url("cover", world, post))
    assert response.status_code == 200
    assert response["Content-Type"] == "image/jpeg"
    assert response["Cache-Control"] == "private, no-store"
    assert _open(response.content).size == CANVAS


def test_cover_endpoint_needs_membership(client, world):
    post = make_post(world)
    assert client.get(_url("cover", world, post)).status_code == 302
    client.force_login(world.outsider)
    assert client.get(_url("cover", world, post)).status_code in (403, 404)


def test_preview_and_detail_show_the_designed_cover(client, world):
    post = make_post(world, cover_style="designed")
    client.force_login(world.owner)
    cover_url = _url("cover", world, post)
    preview = client.get(_url("preview", world, post)).content.decode()
    assert f'src="http://testserver{cover_url}?v=1"' in preview
    detail = client.get(_url("detail", world, post)).content.decode()
    assert f"{cover_url}?v=1" in detail and "Designed (title over the picture)" in detail


def test_editor_offers_the_cover_choice_and_shows_the_preview(client, world):
    post = make_post(world, cover_style="designed")
    client.force_login(world.editor)
    html = client.get(_url("edit", world, post)).content.decode()
    assert 'name="cover_style" value="designed" checked' in html
    assert 'name="cover_style" value="plain" ' in html
    assert _url("cover", world, post) in html
    # Saving with the plain style switches the hero off again.
    response = client.post(
        _url("edit", world, post),
        {
            "site": str(world.neopolis.id),
            "title": post.title,
            "slug": post.slug,
            "excerpt": post.excerpt,
            "body": post.body,
            "featured_image": "",
            "featured_image_alt": "",
            "cover_style": "plain",
            "seo_title": "",
            "meta_description": "",
            "category": post.category,
            "faq_text": "",
        },
    )
    assert response.status_code == 302
    assert BlogPost.objects.get(pk=post.pk).cover_style == "plain"


def test_a_form_without_a_cover_choice_keeps_the_designed_default(client, world):
    client.force_login(world.editor)
    response = client.post(
        reverse("blog:create", kwargs={"workspace_id": world.workspace.id}),
        {
            "site": str(world.neopolis.id),
            "title": "Posted by a script",
            "slug": "posted-by-a-script",
            "excerpt": "",
            "body": "Body.",
            "featured_image": "",
            "featured_image_alt": "",
            "seo_title": "",
            "meta_description": "",
            "category": "",
            "faq_text": "",
        },
    )
    assert response.status_code == 302
    assert BlogPost.objects.get(slug="posted-by-a-script").cover_style == "designed"
