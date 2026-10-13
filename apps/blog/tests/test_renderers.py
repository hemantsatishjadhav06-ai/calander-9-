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
    # The trail the page shows above the title: Home / Blog / the category (the last crumb is the page itself).
    crumbs = blocks["BreadcrumbList"]["itemListElement"]
    assert [i["name"] for i in crumbs] == ["Home", "Blog", "Area Guide"]
    assert "item" not in crumbs[2]


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


# ---------------------------------------------------------------------------
# SEO markup: the title rule, social tags, JSON-LD, related articles, sitemap and feed
# ---------------------------------------------------------------------------

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
PUBLISHED_AT = dt.datetime(2026, 9, 30, 10, 15, tzinfo=IST)
APPROVED_AT = dt.datetime(2026, 10, 2, 9, 0, tzinfo=IST)


def seo_content(**overrides):
    fields = {
        "focus_keyword": "flats in kokapet",
        "keywords": ("kokapet prices", "landlord share"),
        "image_width": 1600,
        "image_height": 900,
        "published_at": PUBLISHED_AT,
        "modified_at": APPROVED_AT,
        "date_published": PUBLISHED_AT.date(),
        "date_modified": APPROVED_AT.date(),
    }
    fields.update(overrides)
    return content(**fields)


@pytest.mark.parametrize("render", [render_neopolis_post, render_morespace_post])
def test_a_long_search_title_drops_the_site_suffix(render):
    long_title = "Land Title Verification in Hyderabad: 5 Checks Before Buying"
    assert len(long_title) == 60
    page = render(seo_content(seo_title=long_title))
    assert f"<title>{long_title}</title>" in page
    short = render(seo_content(seo_title="Kokapet flats"))
    assert re.search(r"<title>Kokapet flats \| (Neopolis Infra|More Space) Blog</title>", short)


@pytest.mark.parametrize("render", [render_neopolis_post, render_morespace_post])
def test_social_tags_carry_the_image_size_dates_section_and_tags(render):
    page = render(seo_content())
    assert '<meta property="og:image:width" content="1600">' in page
    assert '<meta property="og:image:height" content="900">' in page
    assert '<meta property="og:image:alt" content="Kokapet skyline">' in page
    assert '<meta name="twitter:image:alt" content="Kokapet skyline">' in page
    assert '<meta property="article:published_time" content="2026-09-30T10:15:00+05:30">' in page
    assert '<meta property="article:modified_time" content="2026-10-02T09:00:00+05:30">' in page
    assert '<meta property="article:section" content="Area Guide">' in page
    assert page.count('<meta property="article:tag"') == 3
    assert '<meta property="article:tag" content="flats in kokapet">' in page
    assert 'type="application/rss+xml"' in page and "/blog/feed.xml" in page
    # Google ignores meta keywords and Bing treats long ones as spam: not written.
    assert 'name="keywords"' not in page


def test_unknown_image_sizes_are_left_out():
    page = render_neopolis_post(seo_content(image_width=0, image_height=0))
    assert "og:image:width" not in page
    assert 'width="1600" height="900"' in page  # the hero keeps the layout's default box


@pytest.mark.parametrize(
    ("render", "kind"), [(render_neopolis_post, "BlogPosting"), (render_morespace_post, "Article")]
)
def test_article_json_ld_has_image_object_word_count_keywords_and_stable_dates(render, kind):
    article = next(b for b in json_ld(render(seo_content())) if b["@type"] == kind)
    image = article["image"][0] if isinstance(article["image"], list) else article["image"]
    assert image == {
        "@type": "ImageObject",
        "url": image["url"],
        "width": 1600,
        "height": 900,
    }
    assert article["wordCount"] > 0
    assert article["keywords"] == "flats in kokapet, kokapet prices, landlord share"
    assert article["datePublished"] == "2026-09-30T10:15:00+05:30"
    assert article["dateModified"] == "2026-10-02T09:00:00+05:30"
    assert article["publisher"]["logo"]["@type"] == "ImageObject"
    assert article["inLanguage"] == "en-IN" and article["mainEntityOfPage"]["@type"] == "WebPage"


def test_the_page_is_the_same_whatever_day_it_is_rendered():
    """dateModified comes from the approval, not from "today": a later retry writes the same bytes."""
    page = render_neopolis_post(seo_content())
    assert page == render_neopolis_post(seo_content())
    assert '"dateModified":"2026-10-02T09:00:00+05:30"' in page


def test_related_articles_replace_the_legacy_pool_on_neopolis():
    from apps.blog.renderers import RelatedLink

    related = (RelatedLink("kokapet-prices", "Kokapet prices 2026"), RelatedLink("rera-checklist", "RERA checklist"))
    page = render_neopolis_post(seo_content(related=related))
    block = page[page.index('<div class="related">') :]
    block = block[: block.index("</div>")]
    assert '<a href="/blog/kokapet-prices">Kokapet prices 2026</a>' in block
    assert "landlord-share-flats-in-hyderabad-guide" not in block
    # No published articles yet: the site's flagship guides, as before.
    assert "landlord-share-flats-in-hyderabad-guide" in render_neopolis_post(seo_content(related=()))


def test_more_space_gets_a_related_block_only_when_there_are_related_articles():
    from apps.blog.renderers import RelatedLink

    page = render_morespace_post(seo_content(related=(RelatedLink("older", "Older <post>"),)))
    assert '<aside class="blog-related"' in page
    assert '<a href="blog/older.html">Older &lt;post&gt;</a>' in page
    assert '<aside class="blog-related"' not in render_morespace_post(seo_content())


def test_more_space_breadcrumb_matches_the_visible_trail():
    page = render_morespace_post(seo_content())
    crumbs = next(b for b in json_ld(page) if b["@type"] == "BreadcrumbList")["itemListElement"]
    assert [c["name"] for c in crumbs] == ["Home", "Blog", "Area Guide"]


def test_card_data_round_trips_and_reads_old_cards():
    card = seo_content().card()
    assert card.modified == "2026-10-02T09:00:00+05:30"
    assert card.keywords == ("flats in kokapet", "kokapet prices", "landlord share")
    assert CardData.from_dict(json.loads(json.dumps(card.to_dict()))) == card
    old = CardData.from_dict({"slug": "a", "title": "A", "date": "2026-01-02"})
    assert old.modified == "" and old.keywords == () and old.lastmod == "2026-01-02"


def _seo_cards():
    return [
        CardData("older", "Older & wiser", "Earlier.", "Buyer Guide", False, 1, "2026-09-01", 3, "2026-09-03"),
        seo_content().card(),
    ]


def _xml_root(text):
    import xml.etree.ElementTree as ET

    return ET.fromstring(text.split("\n", 2)[2])  # past the declaration and the marker comment


def test_the_sitemap_lists_the_index_and_every_article_with_lastmod():
    from apps.blog.renderers import GENERATED_MARKER, render_sitemap

    origin = "https://www.neopolisinfra.com"
    xml = render_sitemap(_seo_cards(), site_kind="neopolis_static", origin=origin)
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>') and GENERATED_MARKER in xml
    assert "<loc>https://www.neopolisinfra.com/blog/</loc><lastmod>2026-10-02T09:00:00+05:30</lastmod>" in xml
    assert (
        "<loc>https://www.neopolisinfra.com/blog/flats-kokapet-narsingi-2026</loc>"
        "<lastmod>2026-10-02T09:00:00+05:30</lastmod>"
    ) in xml
    assert "<loc>https://www.neopolisinfra.com/blog/older</loc><lastmod>2026-09-03</lastmod>" in xml
    # The same whatever order the cards come in, so an unchanged sitemap is never re-committed.
    assert xml == render_sitemap(list(reversed(_seo_cards())), site_kind="neopolis_static", origin=origin)
    assert len(_xml_root(xml)) == 3
    empty = render_sitemap([], site_kind="morespace_static", origin="https://morespace.netlify.app")
    assert "<loc>https://morespace.netlify.app/blog/</loc>" in empty


def test_the_feed_is_rss_2_newest_first_and_escaped():
    from apps.blog.renderers import render_feed

    root = _xml_root(render_feed(_seo_cards(), site_kind="morespace_static", origin="https://morespace.netlify.app"))
    channel = root.find("channel")
    assert root.tag == "rss" and root.get("version") == "2.0"
    assert channel.findtext("title") == "More Space Blog"
    items = channel.findall("item")
    assert [i.findtext("link") for i in items] == [
        "https://morespace.netlify.app/blog/flats-kokapet-narsingi-2026.html",
        "https://morespace.netlify.app/blog/older.html",
    ]
    assert items[1].findtext("title") == "Older & wiser"
    assert items[0].findtext("pubDate").startswith("Wed, 30 Sep 2026")
    assert channel.findtext("lastBuildDate")
