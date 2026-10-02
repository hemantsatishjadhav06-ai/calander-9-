"""Turn a blog post into the exact files its website serves.

One renderer per ``BlogSite.Kind``. Each produces complete, standalone HTML
strings — the same strings the dashboard preview shows (with its asset URLs
made absolute) and the publisher commits. Rendering is pure: it reads a
:class:`PostContent` snapshot, never the database, so what was approved is
what is rendered.

``neopolis_static`` reproduces the pages ``agents/content-build/build3.js`` in
the neopolis-site-deploy repository generates (``blog.css`` classes, header,
WhatsApp CTA, footer and the BlogPosting / BreadcrumbList / FAQPage / ItemList
JSON-LD), and inserts the post's card into the existing ``blog/index.html``
without touching the other cards.

``morespace_static`` builds pages that use the More Space site's own
``css/styles.css`` and the ``js/main.js`` header/footer injection. main.js
writes root-relative links (``index.html``, ``contact.html``) into the header,
so blog pages carry ``<base href="../">``: every relative URL on the page —
including the injected nav — resolves from the site root, on Netlify and on a
GitHub Pages project URL alike.
"""

from __future__ import annotations

import datetime as dt
import html
import io
import json
import math
import re
from dataclasses import asdict, dataclass, field
from urllib.parse import quote, urljoin, urlsplit

import markdown as markdown_lib  # type: ignore[import-untyped]
import nh3

# ---------------------------------------------------------------------------
# Snapshot of a post's published content
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PostContent:
    title: str
    slug: str
    excerpt: str
    body_md: str
    seo_title: str = ""
    meta_description: str = ""
    category: str = ""
    faq: list = field(default_factory=list)
    image_alt: str = ""
    has_image: bool = False
    revision: int = 1
    date_published: dt.date | None = None
    date_modified: dt.date | None = None

    @classmethod
    def from_post(cls, post, *, today: dt.date | None = None, published_on: dt.date | None = None) -> PostContent:
        """Snapshot ``post``. ``published_on`` is the first publish date (today when never published)."""
        today = today or dt.date.today()
        published = published_on or today
        return cls(
            title=post.title.strip(),
            slug=post.slug,
            excerpt=(post.excerpt or "").strip(),
            body_md=post.body or "",
            seo_title=(post.seo_title or "").strip(),
            meta_description=(post.meta_description or "").strip(),
            category=(post.category or "").strip(),
            faq=[{"q": str(i["q"]).strip(), "a": str(i["a"]).strip()} for i in (post.faq or [])],
            image_alt=(post.featured_image_alt or "").strip(),
            has_image=bool(post.featured_image_id),
            revision=post.revision,
            date_published=published,
            date_modified=today,
        )

    @property
    def page_title(self) -> str:
        return self.seo_title or self.title

    @property
    def description(self) -> str:
        if self.meta_description:
            return self.meta_description
        if self.excerpt:
            return _truncate(self.excerpt, 160)
        return _truncate(plain_text(self.body_md), 160)

    @property
    def card_text(self) -> str:
        return self.excerpt or self.meta_description or _truncate(plain_text(self.body_md), 200)

    @property
    def read_minutes(self) -> int:
        words = len(plain_text(self.body_md).split())
        words += sum(len(f"{i['q']} {i['a']}".split()) for i in self.faq)
        return max(1, round(words / 200))

    def card(self) -> CardData:
        return CardData(
            slug=self.slug,
            title=self.title,
            text=self.card_text,
            category=self.category,
            has_image=self.has_image,
            revision=self.revision,
            date=(self.date_published or dt.date.today()).isoformat(),
            read_minutes=self.read_minutes,
        )


@dataclass(frozen=True)
class CardData:
    """What a blog index shows for one post. Stored as ``BlogPost.published_card``."""

    slug: str
    title: str
    text: str
    category: str
    has_image: bool
    revision: int
    date: str
    read_minutes: int

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> CardData:
        return cls(
            slug=str(data["slug"]),
            title=str(data["title"]),
            text=str(data.get("text", "")),
            category=str(data.get("category", "")),
            has_image=bool(data.get("has_image")),
            revision=int(data.get("revision", 1)),
            date=str(data.get("date", "")),
            read_minutes=int(data.get("read_minutes", 1)),
        )


# ---------------------------------------------------------------------------
# Markdown -> sanitised HTML
# ---------------------------------------------------------------------------

_ALLOWED_TAGS = {
    "p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6",
    "strong", "b", "em", "i", "u", "s", "del", "sup", "sub",
    "code", "pre", "blockquote", "ul", "ol", "li", "a",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td",
    "img", "figure", "figcaption",
}  # fmt: skip
_ALLOWED_ATTRIBUTES = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title", "width", "height", "loading"},
    "th": {"colspan", "rowspan", "scope"},
    "td": {"colspan", "rowspan"},
    "ol": {"start"},
}
_URL_SCHEMES = {"http", "https", "mailto", "tel"}


def render_markdown(source: str) -> str:
    """Markdown to HTML with no scripts, iframes, styles or event handlers.

    Raw HTML in the source is allowed through Markdown and then cleaned with
    an allowlist, so ``<script>``/``<iframe>``/``onclick=``/``javascript:``
    never reach the page. A ``# Heading`` becomes ``<h2>``: the page's own
    ``<h1>`` is the post title.
    """
    rendered = markdown_lib.markdown(source or "", extensions=["tables", "fenced_code", "sane_lists"])
    cleaned = nh3.clean(
        rendered,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        url_schemes=_URL_SCHEMES,
        link_rel=None,
        strip_comments=True,
    )
    return re.sub(r"<(/?)h1>", r"<\1h2>", cleaned)


def plain_text(source: str) -> str:
    """The words of a Markdown body, for read time and fallback descriptions."""
    text = nh3.clean(render_markdown(source), tags=set())
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _truncate(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(",.;:-—–")
    return cut + "…"


def _esc(value) -> str:
    return html.escape(str(value), quote=False)


def _attr(value) -> str:
    return html.escape(str(value), quote=True)


def _json_ld(obj) -> str:
    # Compact like JSON.stringify, and unable to close its <script> element.
    payload = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    return f'<script type="application/ld+json">{payload}</script>'


def _faq_ld(faq) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": item["q"], "acceptedAnswer": {"@type": "Answer", "text": item["a"]}}
            for item in faq
        ],
    }


def _faq_html(faq) -> str:
    items = "\n".join(f"<h3>{_esc(i['q'])}</h3>\n<p>{_esc(i['a'])}</p>" for i in faq)
    return "<h2>Frequently asked questions</h2>\n" + items


def _human_date(value: dt.date) -> str:
    return f"{value.day} {value.strftime('%B %Y')}"


# ---------------------------------------------------------------------------
# Neopolis (www.neopolisinfra.com) — mirrors agents/content-build/build3.js
# ---------------------------------------------------------------------------

NEOPOLIS_ORIGIN = "https://www.neopolisinfra.com"
NEOPOLIS_WA = "https://wa.me/919533686567?text=I%27m%20interested%20in%20a%20landlord%20share%20with%20Neopolis%20Infra"
NEOPOLIS_DEFAULT_CATEGORY = "Guide"
# The card list on blog/index.html. Cards are inserted straight after it.
NEOPOLIS_INDEX_MARKER = '<div class="hscroll">'

_NEOPOLIS_HEAD_COMMON = (
    '<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">{extra}'
    '<meta name="robots" content="index,follow,max-image-preview:large"><meta name="theme-color" content="#081d4a">'
    '<meta property="og:site_name" content="Neopolis Infra"><meta name="twitter:card" content="summary_large_image">'
    '<link rel="icon" href="../assets/img/logo.png"><link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Oswald:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">'
    '<link rel="stylesheet" href="blog.css">'
)
_NEOPOLIS_HEADER = (
    '<header class="bhdr"><div class="wrapwide bnav"><a class="bbrand" href="../">'
    '<img src="../assets/img/logo.png" alt="Neopolis Infra logo">Neopolis Infra</a>'
    '<nav class="bnav-links"><a href="../">Home</a><a href="./">Blog</a>'
    f'<a class="wa" href="{NEOPOLIS_WA}" target="_blank" rel="noopener">WhatsApp</a></nav></div></header>'
)
_NEOPOLIS_FOOTER = (
    '<footer class="bftr"><div class="wrap">&copy; {year} Neopolis Infra Developers &middot; West Hyderabad '
    'landlord-share desk &middot; <a href="tel:+919533686567">+91 95336 86567</a> &middot; '
    '<a href="https://instagram.com/neopolis_infra" target="_blank" rel="noopener">@neopolis_infra</a><br>'
    '<a href="../">Back to neopolisinfra.com</a></div></footer>'
)
# build3.js's supplemental prose styling (tables, related/projects boxes).
_NEOPOLIS_PROSE_EXTRA = (
    "<style>.prose table{border-collapse:collapse;width:100%;margin:1.1rem 0;font-size:.96em}"
    ".prose th,.prose td{border:1px solid #d9dee8;padding:9px 11px;text-align:left;vertical-align:top}"
    ".prose thead th,.prose table tr:first-child th{background:#081d4a;color:#fff}"
    ".prose table tr:nth-child(even) td{background:#f5f7fb}.prose figure.viz{margin:26px 0}"
    ".prose figure.viz img{width:100%;border-radius:14px;border:1px solid #e3e8f1;display:block}"
    ".prose figure.viz figcaption{font-size:.86rem;color:#54668c;margin-top:8px;text-align:center}"
    ".projs,.related{margin:26px 0;padding:16px 20px;border:1px solid #e3e8f1;border-radius:14px;background:#f7f9fc}"
    ".projs h2,.related h2{margin:0 0 8px;font-size:1.1rem;border:0;padding:0}.projs p{margin:0;line-height:1.6}"
    ".related ul{margin:6px 0 0;padding-left:18px}.related li{margin:5px 0}"
    ".projs a,.related a{color:#081d4a;font-weight:600;text-decoration:underline}</style>"
)
# build3.js FLAGSHIP projects (the list a post without a corridor gets).
_NEOPOLIS_FLAGSHIP_PROJECTS = (
    ("Rajapushpa Pristinia", "rajapushpa-pristinia-kokapet"),
    ("MoonGlade", "moonglade-kokapet"),
    ("Vasavi Atlantis", "vasavi-atlantis-narsingi"),
    ("Aparna Zenon", "aparna-zenon-nanakramguda"),
    ("Rajapushpa Greendale", "rajapushpa-greendale-tellapur"),
    ("Rajapushpa Infina", "rajapushpa-infina-manchirevula"),
)
# build3.js relatedBlock() pool, in its order, with the live titles.
_NEOPOLIS_RELATED_POOL = (
    ("landlord-share-flats-in-hyderabad-guide", "Landlord Share Flats in Hyderabad: The Complete 2026 Buyer's Guide"),
    (
        "best-areas-to-buy-flat-in-hyderabad-2026",
        "Best Areas to Buy a Flat in Hyderabad 2026: Prices, ROI & Where to Buy",
    ),
    (
        "buying-a-flat-in-hyderabad-complete-guide-2026",
        "Buying a Flat in Hyderabad 2026: The Complete Step-by-Step Guide",
    ),
    (
        "ready-to-move-vs-under-construction-flats-hyderabad",
        "Ready-to-Move vs Under-Construction Flats in Hyderabad 2026: Which to Buy?",
    ),
    (
        "kokapet-vs-financial-district-vs-gachibowli",
        "Kokapet vs Financial District vs Gachibowli: Where to Buy in 2026",
    ),
    (
        "is-west-hyderabad-good-real-estate-investment-2026",
        "Is West Hyderabad a Good Real Estate Investment in 2026? Data, ROI & Risks",
    ),
    (
        "west-hyderabad-2026-corridor-price-guide",
        "West Hyderabad 2026 Price Guide: Kokapet, Narsingi, Tellapur, Kollur and More",
    ),
    (
        "are-landlord-share-flats-safe-legal-checklist",
        "Are Landlord Share Flats Safe? The 2026 Legal & Title-Verification Checklist",
    ),
    (
        "home-loan-landlord-share-flats-hyderabad",
        "Home Loan on Landlord Share Flats in Hyderabad: Eligibility, Process & Documents (2026)",
    ),
    (
        "landlord-share-vs-resale-vs-builder-price-hyderabad",
        "Landlord Share vs Resale vs Builder Price in Hyderabad: The 8-14% Saving Explained",
    ),
    (
        "nri-guide-buying-flat-hyderabad-remote-process",
        "NRI Guide to Buying a Flat in Hyderabad 2026: Remote Process, POA, Loans and Title",
    ),
)


def neopolis_post_url(slug: str, origin: str = NEOPOLIS_ORIGIN) -> str:
    return f"{origin}/blog/{slug}"


def _neopolis_hero_url(content: PostContent, origin: str) -> str:
    if content.has_image:
        return f"{origin}/blog/img/{content.slug}-hero.jpg"
    return f"{origin}/assets/img/og-cover.jpg"


def render_neopolis_post(content: PostContent, *, origin: str = NEOPOLIS_ORIGIN, hero_src: str | None = None) -> str:
    """The post page, in build3.js's template."""
    origin = origin.rstrip("/")
    category = content.category or NEOPOLIS_DEFAULT_CATEGORY
    canonical = neopolis_post_url(content.slug, origin)
    hero_jpg = _neopolis_hero_url(content, origin)
    date_published = (content.date_published or dt.date.today()).isoformat()
    date_modified = (content.date_modified or dt.date.today()).isoformat()
    page_title = content.page_title
    desc = content.description

    blog_posting = {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": content.title,
        "description": desc,
        "image": hero_jpg,
        "datePublished": date_published,
        "dateModified": date_modified,
        "articleSection": category,
        "inLanguage": "en-IN",
        "author": {"@type": "Organization", "name": "Neopolis Infra Developers", "url": origin},
        "publisher": {
            "@type": "Organization",
            "name": "Neopolis Infra Developers",
            "logo": {"@type": "ImageObject", "url": f"{origin}/assets/img/logo.png"},
        },
        "mainEntityOfPage": {"@type": "WebPage", "@id": canonical},
    }
    breadcrumb = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": origin + "/"},
            {"@type": "ListItem", "position": 2, "name": "Blog", "item": origin + "/blog/"},
            {"@type": "ListItem", "position": 3, "name": content.title, "item": canonical},
        ],
    }
    projects_ld = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": "Projects covered by Neopolis Infra",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": name, "url": f"{origin}/projects/{slug}.html"}
            for i, (name, slug) in enumerate(_NEOPOLIS_FLAGSHIP_PROJECTS)
        ],
    }
    blocks = [blog_posting, breadcrumb]
    if content.faq:
        blocks.append(_faq_ld(content.faq))
    blocks.append(projects_ld)
    json_ld = "".join(_json_ld(b) for b in blocks)

    head_meta = (
        f"<title>{_esc(page_title)} | Neopolis Infra Blog</title>"
        f'<meta name="description" content="{_attr(desc)}">'
        f'<link rel="canonical" href="{canonical}">'
        '<meta property="og:type" content="article">'
        f'<meta property="og:title" content="{_attr(page_title)}">'
        f'<meta property="og:description" content="{_attr(desc)}">'
        f'<meta property="og:url" content="{canonical}">'
        f'<meta property="og:image" content="{hero_jpg}">'
        '<meta property="og:locale" content="en_IN">'
        f'<meta name="twitter:title" content="{_attr(page_title)}">'
        f'<meta name="twitter:description" content="{_attr(desc)}">'
        f'<meta name="twitter:image" content="{hero_jpg}">'
    )

    prose = render_markdown(content.body_md)
    if content.faq:
        prose += "\n" + _faq_html(content.faq)

    hero = ""
    if content.has_image:
        src = hero_src or f"img/{content.slug}-hero.jpg?v={content.revision}"
        hero = (
            f'<div class="ahero"><img src="{_attr(src)}" alt="{_attr(content.image_alt or content.title)}" '
            'width="1600" height="900" style="width:100%;height:auto;display:block" loading="eager" '
            'fetchpriority="high"></div>'
        )

    project_links = " &middot; ".join(
        f'<a href="{origin}/projects/{slug}.html">{_esc(name)}</a>' for name, slug in _NEOPOLIS_FLAGSHIP_PROJECTS
    )
    projects = (
        '<div class="projs"><h2>Featured landlord-share projects we cover</h2><p>Neopolis Infra represents '
        "landlord-share (landowner-share) units across leading West Hyderabad developments &mdash; the same flats, "
        f"direct-priced 8&ndash;14% below builder rates. Projects include {project_links}. "
        f'<a href="{origin}/#projects">See all projects &rarr;</a></p></div>'
    )
    related_items = "".join(
        f'<li><a href="/blog/{slug}">{_esc(title)}</a></li>'
        for slug, title in [p for p in _NEOPOLIS_RELATED_POOL if p[0] != content.slug][:6]
    )
    related = f'<div class="related"><h2>Related guides</h2><ul>{related_items}</ul></div>'
    cta = (
        '<div class="acta"><strong>See verified, direct-priced landlord shares in your budget.</strong><br>'
        "Tell us your corridor and budget &mdash; we reply on WhatsApp, usually within the hour.<br>"
        f'<a href="{NEOPOLIS_WA}" target="_blank" rel="noopener">Chat on WhatsApp &rarr;</a></div>'
    )
    footer = _NEOPOLIS_FOOTER.format(year=(content.date_modified or dt.date.today()).year)

    return (
        '<!DOCTYPE html><html lang="en-IN"><head>'
        + _NEOPOLIS_HEAD_COMMON.format(extra=head_meta)
        + json_ld
        + _NEOPOLIS_PROSE_EXTRA
        + "</head><body>"
        + _NEOPOLIS_HEADER
        + '<main class="wrap"><div class="bcrumbs"><a href="../">Home</a> / <a href="./">Blog</a> / '
        + _esc(category)
        + "</div>"
        + f'<span class="acat">{_esc(category)} &middot; {content.read_minutes} min read</span>'
        + f"<article><h1>{_esc(content.title)}</h1>"
        + f'<div class="ameta">By Neopolis Infra Developers &middot; {date_published}</div>'
        + hero
        + f'<div class="prose">{prose}</div>'
        + projects
        + related
        + cta
        + '<a class="back" href="./">&larr; All articles</a></article></main>'
        + footer
        + "</body></html>"
    )


def neopolis_card(card: CardData) -> str:
    """One ``.bcard`` for the Neopolis blog index (build3.js ``card()``)."""
    src = f"img/{card.slug}-hero.jpg?v={card.revision}" if card.has_image else "../assets/img/og-cover.jpg"
    category = card.category or NEOPOLIS_DEFAULT_CATEGORY
    return (
        f'<a class=\'bcard\' href=\'/blog/{card.slug}\'><div class="bimg"><img loading="lazy" decoding="async" '
        f'src="{_attr(src)}" alt="{_attr(card.title)}" width="400" height="250"></div><div class="bbody">'
        f'<span class="cat">{_esc(category)}</span><h3>{_esc(card.title)}</h3><p>{_esc(card.text)}</p>'
        f'<span class="rt">{card.read_minutes} min read</span></div></a>'
    )


class IndexStructureError(Exception):
    """The live blog index is not shaped the way the renderer expects."""


_CARD_RE_TEMPLATE = r"<a\s+class=(['\"])bcard\1\s+href=(['\"])/blog/{slug}(?:\.html)?\2\s*>.*?</a>"
_ANY_CARD_RE = re.compile(r"<a\s+class=(['\"])bcard\1\s", re.IGNORECASE)
_LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL)


def update_neopolis_index(index_html: str, content: PostContent, *, origin: str = NEOPOLIS_ORIGIN) -> str:
    """Put this post's card first in the existing ``blog/index.html``.

    Any card already linking to this slug is replaced; every other card is
    kept byte for byte. The index's ItemList JSON-LD gets the same treatment.
    Raises :class:`IndexStructureError` rather than guess when the card list
    cannot be found, so a changed template can never cost the site its cards.
    """
    origin = origin.rstrip("/")
    if index_html.count(NEOPOLIS_INDEX_MARKER) != 1:
        raise IndexStructureError(
            f"blog/index.html does not contain exactly one {NEOPOLIS_INDEX_MARKER!r} card list, so the new card "
            "cannot be placed safely. Nothing was published."
        )
    before = len(_ANY_CARD_RE.findall(index_html))
    own_card = re.compile(_CARD_RE_TEMPLATE.format(slug=re.escape(content.slug)), re.DOTALL | re.IGNORECASE)
    stripped, replaced = own_card.subn("", index_html)
    card_html = neopolis_card(content.card())
    updated = stripped.replace(NEOPOLIS_INDEX_MARKER, NEOPOLIS_INDEX_MARKER + card_html, 1)
    after = len(_ANY_CARD_RE.findall(updated))
    if after != before - replaced + 1:
        raise IndexStructureError(
            f"Updating blog/index.html would change the card count from {before} to {after}; refusing to publish."
        )
    return _update_index_item_list(updated, content, origin)


def _update_index_item_list(index_html: str, content: PostContent, origin: str) -> str:
    canonical = neopolis_post_url(content.slug, origin)
    own_urls = {canonical, canonical + ".html"}

    def replace(match):
        try:
            data = json.loads(match.group(1))
        except ValueError:
            return match.group(0)
        if not isinstance(data, dict) or data.get("@type") != "ItemList" or "name" in data:
            return match.group(0)
        items = [i for i in data.get("itemListElement", []) if i.get("url") not in own_urls]
        items.insert(0, {"@type": "ListItem", "position": 1, "url": canonical, "name": content.title})
        for position, item in enumerate(items, start=1):
            item["position"] = position
        data["itemListElement"] = items
        return _json_ld(data)

    return _LD_RE.sub(replace, index_html)


# ---------------------------------------------------------------------------
# More Space (morespace.netlify.app) — the site's styles.css + main.js
# ---------------------------------------------------------------------------

MORESPACE_ORIGIN = "https://morespace.netlify.app"
MORESPACE_DEFAULT_CATEGORY = "Insights"
MORESPACE_WHATSAPP = "917075168306"
_MORESPACE_LOGO = (
    "https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=120,fit=crop,q=95/AMq19Z68OEtq90DG/"
    "untitled-design-A85V2Gln5jFKZkow.png"
)
_MORESPACE_ICON = (
    "https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=64,fit=crop/AMq19Z68OEtq90DG/"
    "untitled-design-A85V2Gln5jFKZkow.png"
)
_MORESPACE_OG_FALLBACK = (
    "https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1200,h=630,fit=crop/AMq19Z68OEtq90DG/"
    "screenshot-2025-06-26-140123-YanJ6aqErrS1kv3K.png"
)
_MORESPACE_FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
    '<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800&family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700&display=swap" rel="stylesheet">\n'
)
# Blog-only additions on top of css/styles.css, written against its tokens.
# styles.css resets list bullets and has no article layout of its own.
_MORESPACE_BLOG_CSS = """<style>
.blog-article{max-width:780px}
.blog-hero{margin:0 0 1.6rem}
.blog-hero img{width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:var(--r-lg);box-shadow:var(--shadow-md)}
.blog-meta{color:var(--ink-soft);font-size:.92rem;font-family:var(--font-display);margin-bottom:1.4rem}
.blog-article .prose ul{list-style:disc;padding-left:1.4rem}
.blog-article .prose ol{list-style:decimal;padding-left:1.4rem}
.blog-article .prose li+li{margin-top:.4rem}
.blog-article .prose a{text-decoration:underline}
.blog-article .prose blockquote{border-left:4px solid var(--blue);padding:.4rem 0 .4rem 1rem;color:var(--ink-soft)}
.blog-article .prose table{width:100%;border-collapse:collapse;border:1px solid var(--line)}
.blog-article .prose th,.blog-article .prose td{padding:.7rem .9rem;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
.blog-article .prose th{background:var(--paper);font-family:var(--font-display);color:var(--indigo)}
.blog-article .prose img{border-radius:var(--r)}
.blog-article .prose pre{overflow-x:auto;background:var(--paper);padding:1rem;border-radius:var(--r-sm)}
.blog-faq{margin-top:2.6rem;padding-top:1.6rem;border-top:1px solid var(--line)}
.blog-back{margin-top:2.4rem}
.blog-card-media{display:block}
.blog-card h3 a{color:var(--ink)}
.blog-card h3 a:hover{color:var(--blue)}
.blog-card-text{margin-top:.55rem;color:var(--ink-soft);font-size:.95rem}
</style>
"""


def morespace_post_url(slug: str, origin: str = MORESPACE_ORIGIN) -> str:
    return f"{origin}/blog/{slug}.html"


def _morespace_wa(message: str) -> str:
    return f"https://wa.me/{MORESPACE_WHATSAPP}?text={quote(message)}"


def _morespace_head(*, title, description, canonical, og_type, og_image, json_ld) -> str:
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n'
        '<meta charset="UTF-8">\n'
        # main.js injects header/footer links relative to the site root.
        '<base href="../">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f"<title>{_esc(title)}</title>\n"
        f'<meta name="description" content="{_attr(description)}">\n'
        f'<link rel="canonical" href="{canonical}">\n'
        '<meta name="robots" content="index,follow,max-image-preview:large">\n'
        f'<meta property="og:type" content="{og_type}">\n'
        '<meta property="og:site_name" content="More Space">\n'
        f'<meta property="og:title" content="{_attr(title)}">\n'
        f'<meta property="og:description" content="{_attr(description)}">\n'
        f'<meta property="og:url" content="{canonical}">\n'
        f'<meta property="og:image" content="{_attr(og_image)}">\n'
        '<meta property="og:locale" content="en_IN">\n'
        '<meta name="twitter:card" content="summary_large_image">\n'
        f'<meta name="twitter:title" content="{_attr(title)}">\n'
        f'<meta name="twitter:description" content="{_attr(description)}">\n'
        f'<meta name="twitter:image" content="{_attr(og_image)}">\n'
        + _MORESPACE_FONTS
        + '<link rel="stylesheet" href="css/styles.css">\n'
        + f'<link rel="icon" href="{_MORESPACE_ICON}">\n'
        + "".join(_json_ld(block) + "\n" for block in json_ld)
        + _MORESPACE_BLOG_CSS
        + "</head>\n"
    )


_MORESPACE_TAIL = '<div id="site-footer"></div>\n<script src="js/data.js"></script>\n<script src="js/main.js"></script>\n</body>\n</html>\n'


def render_morespace_post(content: PostContent, *, origin: str = MORESPACE_ORIGIN, hero_src: str | None = None) -> str:
    origin = origin.rstrip("/")
    category = content.category or MORESPACE_DEFAULT_CATEGORY
    canonical = morespace_post_url(content.slug, origin)
    hero_abs = f"{origin}/blog/img/{content.slug}-hero.jpg" if content.has_image else _MORESPACE_OG_FALLBACK
    published = content.date_published or dt.date.today()
    modified = content.date_modified or dt.date.today()
    page_title = f"{content.page_title} | More Space Blog"
    desc = content.description

    article = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": content.title,
        "description": desc,
        "image": [hero_abs],
        "datePublished": published.isoformat(),
        "dateModified": modified.isoformat(),
        "articleSection": category,
        "inLanguage": "en-IN",
        "author": {"@type": "Organization", "name": "More Space", "url": origin + "/"},
        "publisher": {
            "@type": "Organization",
            "name": "More Space",
            "logo": {"@type": "ImageObject", "url": _MORESPACE_LOGO},
        },
        "mainEntityOfPage": {"@type": "WebPage", "@id": canonical},
    }
    breadcrumb = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": origin + "/"},
            {"@type": "ListItem", "position": 2, "name": "Blog", "item": origin + "/blog/"},
            {"@type": "ListItem", "position": 3, "name": content.title, "item": canonical},
        ],
    }
    blocks = [article, breadcrumb]
    if content.faq:
        blocks.append(_faq_ld(content.faq))

    hero = ""
    if content.has_image:
        src = hero_src or f"blog/img/{content.slug}-hero.jpg?v={content.revision}"
        hero = (
            f'<figure class="blog-hero"><img src="{_attr(src)}" alt="{_attr(content.image_alt or content.title)}" '
            'width="1600" height="900" fetchpriority="high"></figure>\n'
        )
    faq = ""
    if content.faq:
        faq = f'<section class="blog-faq prose" aria-label="Frequently asked questions">\n{_faq_html(content.faq)}\n</section>\n'
    excerpt = f"    <p>{_esc(content.excerpt)}</p>\n" if content.excerpt else ""
    wa = _morespace_wa(f"Hi More Space, I read your article “{content.title}” and would like to know more.")

    return (
        _morespace_head(
            title=page_title,
            description=desc,
            canonical=canonical,
            og_type="article",
            og_image=hero_abs,
            json_ld=blocks,
        )
        + '<body data-page="blog" class="subpage">\n<div id="site-header"></div>\n\n'
        + '<section class="page-hero">\n  <div class="container">\n'
        + '    <nav class="breadcrumb" aria-label="Breadcrumb"><a href="index.html">Home</a><span class="sep">/</span>'
        + f'<a href="blog/">Blog</a><span class="sep">/</span><span>{_esc(category)}</span></nav>\n'
        + f'    <span class="eyebrow" style="color:#cfc9ff">{_esc(category)} &middot; {content.read_minutes} min read</span>\n'
        + f"    <h1>{_esc(content.title)}</h1>\n"
        + excerpt
        + "  </div>\n</section>\n\n"
        + '<section class="section">\n  <div class="container blog-article">\n    <article>\n'
        + hero
        + f'<p class="blog-meta">By More Space &middot; <time datetime="{published.isoformat()}">{_human_date(published)}</time></p>\n'
        + f'<div class="prose">\n{render_markdown(content.body_md)}\n</div>\n'
        + faq
        + "    </article>\n"
        + '    <p class="blog-back"><a class="btn btn-ghost btn-sm" href="blog/">&larr; All articles</a></p>\n'
        + "  </div>\n</section>\n\n"
        + '<section class="section section--paper">\n  <div class="container">\n    <div class="cta-banner">\n'
        + "      <h2>Let's find your space</h2>\n"
        + "      <p>Tell us what you're looking for — we'll shortlist verified options with transparency and care.</p>\n"
        + '      <div class="actions">\n'
        + f'        <a class="btn btn-light" href="{_attr(wa)}" target="_blank" rel="noopener">Chat on WhatsApp</a>\n'
        + '        <a class="btn btn-dark" href="contact.html">Contact us</a>\n'
        + "      </div>\n    </div>\n  </div>\n</section>\n\n"
        + _MORESPACE_TAIL
    )


def _morespace_card(card: CardData) -> str:
    href = f"blog/{card.slug}.html"
    try:
        date = dt.date.fromisoformat(card.date)
        when = f'<time datetime="{card.date}">{_human_date(date)}</time> &middot; '
    except ValueError:
        when = ""
    media = ""
    if card.has_image:
        media = (
            f'<a class="pcard__media blog-card-media" href="{href}" tabindex="-1" aria-hidden="true">'
            f'<img loading="lazy" src="blog/img/{card.slug}-hero.jpg?v={card.revision}" alt="" width="760" height="428">'
            f'<span class="pcard__tag">{_esc(card.category or MORESPACE_DEFAULT_CATEGORY)}</span></a>'
        )
    return (
        f'<article class="pcard blog-card">{media}<div class="pcard__body">'
        f'<span class="pcard__loc">{when}{card.read_minutes} min read</span>'
        f'<h3><a href="{href}">{_esc(card.title)}</a></h3>'
        f'<p class="blog-card-text">{_esc(card.text)}</p></div></article>'
    )


def render_morespace_index(cards: list[CardData], *, origin: str = MORESPACE_ORIGIN) -> str:
    """The whole ``blog/index.html``, newest first."""
    origin = origin.rstrip("/")
    canonical = f"{origin}/blog/"
    title = "Blog | Hyderabad Real Estate Insights | More Space"
    desc = "Guides, market notes and buyer how-tos for Hyderabad real estate from the More Space team."
    blog_ld = {
        "@context": "https://schema.org",
        "@type": "Blog",
        "name": "More Space Blog",
        "description": desc,
        "url": canonical,
        "inLanguage": "en-IN",
        "publisher": {
            "@type": "Organization",
            "name": "More Space",
            "logo": {"@type": "ImageObject", "url": _MORESPACE_LOGO},
        },
    }
    item_ld = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "url": morespace_post_url(c.slug, origin), "name": c.title}
            for i, c in enumerate(cards)
        ],
    }
    grid = "\n".join(_morespace_card(c) for c in cards) or '<p class="empty">New articles are on their way.</p>'
    return (
        _morespace_head(
            title=title,
            description=desc,
            canonical=canonical,
            og_type="website",
            og_image=_MORESPACE_OG_FALLBACK,
            json_ld=[blog_ld, item_ld],
        )
        + '<body data-page="blog" class="subpage">\n<div id="site-header"></div>\n\n'
        + '<section class="page-hero">\n  <div class="container">\n'
        + '    <nav class="breadcrumb" aria-label="Breadcrumb"><a href="index.html">Home</a><span class="sep">/</span><span>Blog</span></nav>\n'
        + '    <span class="eyebrow" style="color:#cfc9ff">Blog</span>\n'
        + "    <h1>Insights for smarter property decisions</h1>\n"
        + f"    <p>{_esc(desc)}</p>\n"
        + "  </div>\n</section>\n\n"
        + f'<section class="section">\n  <div class="container">\n    <div class="project-grid">\n{grid}\n    </div>\n  </div>\n</section>\n\n'
        + _MORESPACE_TAIL
    )


# ---------------------------------------------------------------------------
# Dispatch, preview and the hero image
# ---------------------------------------------------------------------------


def render_post_page(site, content: PostContent, *, hero_src: str | None = None) -> str:
    from apps.blog.models import BlogSite

    if site.kind == BlogSite.Kind.NEOPOLIS_STATIC:
        return render_neopolis_post(content, origin=site.origin, hero_src=hero_src)
    if site.kind == BlogSite.Kind.MORESPACE_STATIC:
        return render_morespace_post(content, origin=site.origin, hero_src=hero_src)
    raise ValueError(f"No renderer for site kind {site.kind!r}")


_TAG_RE = re.compile(r"<[a-zA-Z][^<>]*>")
_TAG_URL_ATTR_RE = re.compile(r"(\s(?:src|href)=)([\"'])(.*?)\2", re.IGNORECASE | re.DOTALL)
_BASE_TAG_RE = re.compile(r"<base\s+href=([\"'])(.*?)\1\s*/?>", re.IGNORECASE)
_KEEP_PREFIXES = ("#", "data:", "mailto:", "tel:", "javascript:", "//")


def absolutize_urls(page_html: str, page_url: str) -> str:
    """Rewrite every relative ``src``/``href`` in tags to an absolute URL.

    Used for the dashboard preview: the page is served from the app, so the
    site's own CSS, scripts, logo and links have to point at the live site.
    A ``<base href>`` is honoured (and itself made absolute).
    """
    base_url = page_url
    match = _BASE_TAG_RE.search(page_html)
    if match:
        base_url = urljoin(page_url, html.unescape(match.group(2)))
        page_html = page_html[: match.start()] + f'<base href="{_attr(base_url)}">' + page_html[match.end() :]

    def fix_attr(attr_match):
        prefix, quote_char, value = attr_match.groups()
        raw = html.unescape(value).strip()
        if not raw or raw.startswith(_KEEP_PREFIXES) or urlsplit(raw).scheme:
            return attr_match.group(0)
        return f"{prefix}{quote_char}{_attr(urljoin(base_url, raw))}{quote_char}"

    def fix_tag(tag_match):
        return _TAG_URL_ATTR_RE.sub(fix_attr, tag_match.group(0))

    return _TAG_RE.sub(fix_tag, page_html)


HERO_MAX_WIDTH = 1600
HERO_JPEG_QUALITY = 85


def hero_jpeg_bytes(asset) -> bytes:
    """The featured image as a JPEG, at most 1600px wide, quality 85.

    Orientation from EXIF is applied, transparency is flattened onto white
    and metadata is dropped. Raises ``ValueError`` for anything that is not a
    still image Pillow can read.
    """
    from django.conf import settings
    from PIL import Image, ImageOps

    max_pixels = getattr(settings, "MEDIA_LIBRARY_MAX_IMAGE_PIXELS", 30_000_000)
    with asset.file.open("rb") as handle:
        data = handle.read()
    try:
        opened = Image.open(io.BytesIO(data))
        opened.draft("RGB", (HERO_MAX_WIDTH, 1))
        image: Image.Image = opened  # JPEG: decode at the smallest scale still >= 1600 wide
        if image.width * image.height > max_pixels:
            raise ValueError(
                f"The featured image is {image.width}x{image.height}, larger than this server will process."
            )
        image = ImageOps.exif_transpose(image)
        if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
            image = image.convert("RGBA")
            flattened = Image.new("RGB", image.size, (255, 255, 255))
            flattened.paste(image, mask=image.getchannel("A"))
            image = flattened
        elif image.mode != "RGB":
            image = image.convert("RGB")
        if image.width > HERO_MAX_WIDTH:
            height = max(1, math.floor(image.height * HERO_MAX_WIDTH / image.width))
            image = image.resize((HERO_MAX_WIDTH, height), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=HERO_JPEG_QUALITY, optimize=True, progressive=True)
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError(f"The featured image could not be read as an image ({exc}).") from exc
    return out.getvalue()
