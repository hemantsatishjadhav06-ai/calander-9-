"""The HTML each site gets: canonical, social tags, JSON-LD, sanitising and the indexes."""

import datetime as dt
import io
import json
import re

import pytest
from PIL import Image

from apps.blog.renderers import (
    CardData,
    IndexStructureError,
    PostContent,
    absolutize_urls,
    hero_jpeg_bytes,
    render_markdown,
    render_morespace_index,
    render_morespace_post,
    render_neopolis_post,
    update_neopolis_index,
)
from apps.blog.tests.conftest import png_bytes

TODAY = dt.date(2026, 10, 2)


def content(**overrides):
    fields = {
        "title": "Flats in Kokapet & Narsingi 2026",
        "slug": "flats-kokapet-narsingi-2026",
        "excerpt": "Where to buy, what it costs, and the landlord-share saving.",
        "body_md": "## Prices\n\nKokapet is **booming**.\n\n| Area | Price |\n|---|---|\n| Kokapet | 9,000 |",
        "seo_title": "Kokapet & Narsingi flats 2026",
        "meta_description": "Prices and projects in Kokapet and Narsingi for 2026.",
        "category": "Area Guide",
        "faq": [{"q": "Is Kokapet good?", "a": "Yes, for most buyers."}],
        "image_alt": "Kokapet skyline",
        "has_image": True,
        "revision": 4,
        "date_published": TODAY,
        "date_modified": TODAY,
    }
    fields.update(overrides)
    return PostContent(**fields)


def json_ld(page):
    return [
        json.loads(block) for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)
    ]


# ---------------------------------------------------------------------------
# Neopolis
# ---------------------------------------------------------------------------


def test_neopolis_post_head_matches_the_site_template():
    page = render_neopolis_post(content())
    canonical = "https://www.neopolisinfra.com/blog/flats-kokapet-narsingi-2026"
    hero = "https://www.neopolisinfra.com/blog/img/flats-kokapet-narsingi-2026-hero.jpg"
    assert page.startswith('<!DOCTYPE html><html lang="en-IN"><head><meta charset="UTF-8">')
    assert f'<link rel="canonical" href="{canonical}">' in page
    assert "<title>Kokapet &amp; Narsingi flats 2026 | Neopolis Infra Blog</title>" in page
    assert f'<meta property="og:url" content="{canonical}">' in page
    assert f'<meta property="og:image" content="{hero}">' in page
    assert f'<meta name="twitter:image" content="{hero}">' in page
    assert '<meta name="twitter:card" content="summary_large_image">' in page
    assert '<link rel="stylesheet" href="blog.css">' in page
    assert "family=Oswald" in page and "Plus+Jakarta+Sans" in page
    # Template blocks from build3.js.
    for marker in (
        '<header class="bhdr">',
        '<div class="bcrumbs">',
        '<span class="acat">Area Guide &middot; 1 min read',
        '<div class="ahero">',
        '<div class="prose">',
        '<div class="projs">',
        '<div class="related">',
        '<div class="acta">',
        '<footer class="bftr">',
    ):
        assert marker in page, marker
    assert "https://wa.me/919533686567" in page
    assert 'src="img/flats-kokapet-narsingi-2026-hero.jpg?v=4"' in page


def test_neopolis_post_json_ld():
    blocks = {b["@type"]: b for b in json_ld(render_neopolis_post(content()))}
    assert set(blocks) == {"BlogPosting", "BreadcrumbList", "FAQPage", "ItemList"}
    posting = blocks["BlogPosting"]
    assert posting["headline"] == "Flats in Kokapet & Narsingi 2026"
    assert posting["mainEntityOfPage"]["@id"] == "https://www.neopolisinfra.com/blog/flats-kokapet-narsingi-2026"
    assert posting["datePublished"] == "2026-10-02" and posting["inLanguage"] == "en-IN"
    assert blocks["FAQPage"]["mainEntity"][0]["acceptedAnswer"]["text"] == "Yes, for most buyers."
    assert [i["name"] for i in blocks["BreadcrumbList"]["itemListElement"]] == ["Home", "Blog", posting["headline"]]


def test_neopolis_post_without_faq_or_image():
    page = render_neopolis_post(content(faq=[], has_image=False))
    assert "FAQPage" not in page
    assert '<div class="ahero">' not in page
    assert 'content="https://www.neopolisinfra.com/assets/img/og-cover.jpg"' in page


def test_json_ld_cannot_close_its_script_tag():
    page = render_neopolis_post(content(faq=[{"q": "</script><script>alert(1)</script>", "a": "x"}]))
    assert "</script><script>alert(1)" not in page
    assert any(b["@type"] == "FAQPage" for b in json_ld(page))


def test_markdown_is_sanitised():
    out = render_markdown(
        "# Title\n\n<script>alert(1)</script><iframe src='https://evil'></iframe>"
        '<a href="javascript:alert(1)" onclick="x()">x</a> <img src=x onerror="alert(1)"> [ok](https://example.com)'
    )
    assert "<script" not in out and "<iframe" not in out
    assert "javascript:" not in out and "onclick" not in out and "onerror" not in out
    assert "<h2>Title</h2>" in out and "<h1>" not in out
    assert '<a href="https://example.com">ok</a>' in out


NEOPOLIS_INDEX = (
    '<!DOCTYPE html><html lang="en-IN"><head><title>Blog</title>'
    '<script type="application/ld+json">{"@context":"https://schema.org","@type":"Blog","name":"Neopolis Infra Blog"}</script>'
    '<script type="application/ld+json">{"@context":"https://schema.org","@type":"ItemList","itemListElement":['
    '{"@type":"ListItem","position":1,"url":"https://www.neopolisinfra.com/blog/stamp-duty.html","name":"Stamp duty"},'
    '{"@type":"ListItem","position":2,"url":"https://www.neopolisinfra.com/blog/flats-kokapet-narsingi-2026.html","name":"Old title"},'
    '{"@type":"ListItem","position":3,"url":"https://www.neopolisinfra.com/blog/nri-guide.html","name":"NRI guide"}]}</script>'
    '</head><body><section class="bhero"></section>'
    '<div class="hscroll">'
    '<a class=\'bcard\' href=\'/blog/stamp-duty\'><div class="bimg"><img src="img/stamp-duty-hero.jpg?v=2" alt="Stamp duty"></div>'
    '<div class="bbody"><span class="cat">Buyer Guide</span><h3>Stamp duty</h3><p>Charges.</p><span class="rt">9 min read</span></div></a>'
    '<a class=\'bcard\' href=\'/blog/flats-kokapet-narsingi-2026\'><div class="bimg"><img src="x.jpg" alt="Old title"></div>'
    '<div class="bbody"><span class="cat">Area Guide</span><h3>Old title</h3><p>Old.</p><span class="rt">5 min read</span></div></a>'
    '<a class=\'bcard\' href=\'/blog/nri-guide\'><div class="bimg"><img src="../assets/img/projects/v.webp" alt="NRI"></div>'
    '<div class="bbody"><span class="cat">NRI Guide</span><h3>NRI guide</h3><p>Remote.</p><span class="rt">8 min read</span></div></a>'
    '</div><p class="hscroll-hint">&larr; swipe</p><footer class="bftr"></footer></body></html>'
)


def _cards(index):
    return re.findall(r"<a class='bcard' href='/blog/([a-z0-9-]+)'>", index)


def test_neopolis_index_keeps_every_other_card_and_puts_this_one_first():
    updated = update_neopolis_index(NEOPOLIS_INDEX, content())
    assert _cards(updated) == ["flats-kokapet-narsingi-2026", "stamp-duty", "nri-guide"]
    # Untouched cards are byte-for-byte the same.
    for slug in ("stamp-duty", "nri-guide"):
        original = re.search(rf"<a class='bcard' href='/blog/{slug}'>.*?</a>", NEOPOLIS_INDEX).group(0)
        assert original in updated
    assert "Old title</h3>" not in updated
    assert "<h3>Flats in Kokapet &amp; Narsingi 2026</h3>" in updated
    item_list = next(b for b in json_ld(updated) if b["@type"] == "ItemList")
    assert [i["position"] for i in item_list["itemListElement"]] == [1, 2, 3]
    assert item_list["itemListElement"][0] == {
        "@type": "ListItem",
        "position": 1,
        "url": "https://www.neopolisinfra.com/blog/flats-kokapet-narsingi-2026",
        "name": "Flats in Kokapet & Narsingi 2026",
    }
    assert updated == update_neopolis_index(updated, content())  # idempotent


def test_neopolis_index_new_post_adds_a_card():
    updated = update_neopolis_index(NEOPOLIS_INDEX, content(slug="brand-new"))
    assert _cards(updated) == ["brand-new", "stamp-duty", "flats-kokapet-narsingi-2026", "nri-guide"]


def test_neopolis_index_with_an_unexpected_structure_is_refused():
    with pytest.raises(IndexStructureError):
        update_neopolis_index("<html><body><div class='grid'></div></body></html>", content())


# ---------------------------------------------------------------------------
# More Space
# ---------------------------------------------------------------------------


def test_morespace_post_uses_the_site_shell():
    page = render_morespace_post(content())
    canonical = "https://morespace.netlify.app/blog/flats-kokapet-narsingi-2026.html"
    assert f'<link rel="canonical" href="{canonical}">' in page
    assert f'<meta property="og:url" content="{canonical}">' in page
    assert (
        '<meta property="og:image" content="https://morespace.netlify.app/blog/img/flats-kokapet-narsingi-2026-hero.jpg">'
        in page
    )
    assert '<base href="../">' in page
    assert '<link rel="stylesheet" href="css/styles.css">' in page
    assert '<script src="js/data.js"></script>\n<script src="js/main.js"></script>' in page
    assert '<body data-page="blog" class="subpage">\n<div id="site-header"></div>' in page
    assert '<div id="site-footer"></div>' in page
    assert "family=Outfit" in page and "DM+Sans" in page
    assert 'src="blog/img/flats-kokapet-narsingi-2026-hero.jpg?v=4"' in page
    blocks = {b["@type"]: b for b in json_ld(page)}
    assert blocks["Article"]["mainEntityOfPage"]["@id"] == canonical
    assert blocks["Article"]["headline"] == "Flats in Kokapet & Narsingi 2026"
    assert "FAQPage" in blocks and "BreadcrumbList" in blocks


def test_morespace_index_lists_cards_and_has_an_empty_state():
    cards = [
        content().card(),
        CardData("older", "Older post", "Earlier.", "", False, 1, "2026-09-01", 3),
    ]
    page = render_morespace_index(cards)
    assert '<link rel="canonical" href="https://morespace.netlify.app/blog/">' in page
    assert page.index('href="blog/flats-kokapet-narsingi-2026.html"') < page.index('href="blog/older.html"')
    item_list = next(b for b in json_ld(page) if b["@type"] == "ItemList")
    assert [i["url"] for i in item_list["itemListElement"]] == [
        "https://morespace.netlify.app/blog/flats-kokapet-narsingi-2026.html",
        "https://morespace.netlify.app/blog/older.html",
    ]
    assert 'class="empty"' in render_morespace_index([])


# ---------------------------------------------------------------------------
# Preview URLs and the hero image
# ---------------------------------------------------------------------------


def test_absolutize_for_neopolis_preview():
    page = absolutize_urls(
        render_neopolis_post(content()), "https://www.neopolisinfra.com/blog/flats-kokapet-narsingi-2026"
    )
    assert 'href="https://www.neopolisinfra.com/blog/blog.css"' in page
    assert 'src="https://www.neopolisinfra.com/assets/img/logo.png"' in page
    assert 'href="https://www.neopolisinfra.com/blog/"' in page  # "./"
    assert 'href="https://www.neopolisinfra.com/blog/landlord-share-flats-in-hyderabad-guide"' in page
    assert 'href="tel:+919533686567"' in page


def test_absolutize_honours_base_for_morespace_preview():
    page = absolutize_urls(
        render_morespace_post(content()), "https://morespace.netlify.app/blog/flats-kokapet-narsingi-2026.html"
    )
    assert '<base href="https://morespace.netlify.app/">' in page
    assert 'href="https://morespace.netlify.app/css/styles.css"' in page
    assert 'src="https://morespace.netlify.app/js/main.js"' in page
    assert 'href="https://morespace.netlify.app/contact.html"' in page


@pytest.mark.django_db
def test_hero_jpeg_is_resized_and_flattened(image_asset):
    asset = image_asset(png_bytes(2400, 1200, "RGBA"))
    data = hero_jpeg_bytes(asset)
    image = Image.open(io.BytesIO(data))
    assert image.format == "JPEG"
    assert image.size == (1600, 800)
    assert image.mode == "RGB"


@pytest.mark.django_db
def test_small_hero_is_not_upscaled(image_asset):
    asset = image_asset(png_bytes(800, 600, "RGB"))
    image = Image.open(io.BytesIO(hero_jpeg_bytes(asset)))
    assert image.size == (800, 600)


@pytest.mark.django_db
def test_hero_rejects_a_non_image(image_asset):
    asset = image_asset(b"not an image", filename="fake.png")
    with pytest.raises(ValueError):
        hero_jpeg_bytes(asset)
