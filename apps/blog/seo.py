"""The SEO score: plain checks that make an article easier to find and better to read.

Deterministic and free — no model, no network — so the editor can re-score
on every keystroke, the SEO editor agent can aim at it, and the approver sees
the same number. Each check is pass / warn / fail with a sentence that says
how to fix it, and a weight; the score is the weighted share of passes (a
warning counts half).

What it does not do: guess search volumes or rankings. Those come from Google
Search Console when it is connected (``apps.blog.search_console``).

Google's own guidance (2026) still rewards the basics measured here — a clear
title and description, a sensible heading structure, descriptive links and
alt text, helpful depth — and FAQ rich results are gone, so the FAQ check is
about answering readers' questions on the page, not about a snippet.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field

# The renderer owns the <title> rule; the score measures exactly what it writes.
from .renderers import TITLE_MAX, TITLE_SUFFIX, plain_text, title_tag

__all__ = [
    "TITLE_MAX",
    "TITLE_SUFFIX",
    "Check",
    "Report",
    "score",
    "score_post",
    "score_posts",
    "suggestion",
    "title_tag",
]

TITLE_MIN = 30
META_MIN = 120
META_MAX = 160
MIN_WORDS = 800
MIN_H2 = 3
MAX_PARAGRAPH_WORDS = 120
MAX_SENTENCE_WORDS = 25
MIN_INTERNAL_LINKS = 2

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.MULTILINE)
_LINK = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)")
_SENTENCE = re.compile(r"[^.!?]+[.!?]")
_WORD = re.compile(r"[\w'’-]+", re.UNICODE)


@dataclass
class Check:
    key: str
    label: str
    level: str  # "pass" | "warn" | "fail"
    detail: str
    weight: int = 1

    @property
    def passed(self) -> bool:
        return self.level == "pass"


@dataclass
class Report:
    score: int
    grade: str
    checks: list[Check] = field(default_factory=list)
    words: int = 0
    title_tag: str = ""

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def to_fix(self) -> list[Check]:
        """Failures first, then warnings — the order a person should fix them in."""
        return [c for c in self.checks if c.level == "fail"] + [c for c in self.checks if c.level == "warn"]

    @property
    def passing(self) -> list[Check]:
        return [c for c in self.checks if c.passed]

    @property
    def title_fits(self) -> bool:
        """Whether the <title> is within the ~60 characters Google shows."""
        return len(self.title_tag) <= TITLE_MAX

    @property
    def tone(self) -> str:
        """``good`` / ``fair`` / ``poor``: the colour the score is shown in."""
        return "good" if self.score >= 80 else "fair" if self.score >= 60 else "poor"

    def as_dict(self) -> dict:
        data = asdict(self)
        data["passed"] = self.passed
        return data


def _norm(text: str) -> str:
    return " ".join(_WORD.findall((text or "").lower()))


def _contains(haystack: str, keyword: str) -> bool:
    keyword = _norm(keyword)
    return bool(keyword) and f" {keyword} " in f" {_norm(haystack)} "


def _slug_words(slug: str) -> str:
    return (slug or "").replace("-", " ")


def _paragraphs(body: str) -> list[str]:
    blocks = re.split(r"\n\s*\n", body or "")
    out = []
    for block in blocks:
        text = block.strip()
        if not text or text.startswith(("#", "|", "-", "*", ">", "1.", "```")):
            continue
        out.append(text)
    return out


def _is_internal(url: str, site_origin: str) -> bool:
    url = url.strip()
    if url.startswith(("/", "#")) and not url.startswith("//"):
        return True
    origin = (site_origin or "").rstrip("/")
    bare = origin.replace("https://", "").replace("http://", "").replace("www.", "")
    return bool(bare) and bare in url.replace("www.", "")


def score(
    *,
    title: str,
    slug: str,
    body: str,
    seo_title: str = "",
    meta_description: str = "",
    excerpt: str = "",
    focus_keyword: str = "",
    secondary_keywords: list[str] | None = None,
    faq: list | None = None,
    image_alt: str = "",
    has_image: bool = False,
    site_kind: str = "",
    site_origin: str = "",
    other_titles: list[str] | None = None,
) -> Report:
    """Score one article. Every argument is plain data (see :func:`score_post`)."""
    checks: list[Check] = []
    add = checks.append
    keyword = (focus_keyword or "").strip()
    text = plain_text(body or "")
    words = len(_WORD.findall(text))
    tag = title_tag(seo_title, title, site_kind)
    description = (meta_description or "").strip() or (excerpt or "").strip()
    headings = [(len(m.group(1)), m.group(2).strip()) for m in _HEADING.finditer(body or "")]
    h2s = [h for level, h in headings if level <= 2]  # the renderer turns '#' into h2
    links = _LINK.findall(body or "")
    internal = [u for _t, u in links if _is_internal(u, site_origin)]
    external = [u for _t, u in links if u.startswith("http") and not _is_internal(u, site_origin)]
    first_part = " ".join(text.split()[:100])

    # Title tag
    base_len = len((seo_title or title or "").strip())
    if base_len == 0:
        add(Check("title", "Search title", "fail", "Add a title.", 3))
    elif base_len > TITLE_MAX:
        add(
            Check(
                "title", "Search title", "fail", f"{base_len} characters — Google cuts it at about 60. Shorten it.", 3
            )
        )
    elif base_len < TITLE_MIN:
        add(
            Check(
                "title",
                "Search title",
                "warn",
                f"{base_len} characters — a little short; say more of what it covers.",
                3,
            )
        )
    else:
        add(Check("title", "Search title", "pass", f"{base_len} of {TITLE_MAX} characters.", 3))

    # Description
    dlen = len(description)
    if not description:
        add(Check("meta", "Search description", "fail", "Add a description of about 150 characters.", 3))
    elif dlen > META_MAX:
        add(Check("meta", "Search description", "warn", f"{dlen} characters — it will be cut at about 160.", 3))
    elif dlen < META_MIN:
        add(Check("meta", "Search description", "warn", f"{dlen} characters — aim for 120 to 160.", 3))
    else:
        add(Check("meta", "Search description", "pass", f"{dlen} of {META_MAX} characters.", 3))

    # Keyword placement
    if not keyword:
        add(Check("keyword", "Focus keyword", "warn", "Set the phrase a reader would search for.", 2))
    else:
        add(
            Check(
                "kw_title",
                "Keyword in the search title",
                "pass" if _contains(tag, keyword) or _contains(title, keyword) else "fail",
                f"“{keyword}” {'appears' if _contains(tag, keyword) or _contains(title, keyword) else 'is missing'}.",
                3,
            )
        )
        add(
            Check(
                "kw_intro",
                "Keyword early in the article",
                "pass" if _contains(first_part, keyword) else "warn",
                "In the first 100 words." if _contains(first_part, keyword) else "Use it in the first paragraph.",
                2,
            )
        )
        in_h2 = any(_contains(h, keyword) for h in h2s) or any(
            _contains(h, kw) for h in h2s for kw in (secondary_keywords or [])
        )
        add(
            Check(
                "kw_heading",
                "Keyword or a related term in a heading",
                "pass" if in_h2 else "warn",
                "Found in a section heading." if in_h2 else "Use it (or a related term) in one H2.",
                1,
            )
        )
        slug_ok = _contains(_slug_words(slug), keyword) or all(
            w in _slug_words(slug).split() for w in _norm(keyword).split()[:3]
        )
        add(
            Check(
                "kw_slug",
                "Keyword in the address",
                "pass" if slug_ok else "warn",
                "The address carries it." if slug_ok else "Put the main words in the address.",
                1,
            )
        )
        add(
            Check(
                "kw_meta",
                "Keyword in the description",
                "pass" if _contains(description, keyword) else "warn",
                "Present." if _contains(description, keyword) else "Use it once in the description.",
                1,
            )
        )
        count = f" {_norm(text)} ".count(f" {_norm(keyword)} ")
        density = (count * max(1, len(_norm(keyword).split())) / words * 100) if words else 0
        if density > 3:
            add(
                Check(
                    "kw_density",
                    "Natural keyword use",
                    "warn",
                    f"It is {density:.1f}% of the words — reads as stuffing.",
                    1,
                )
            )
        else:
            add(Check("kw_density", "Natural keyword use", "pass", f"Used {count} times.", 1))

    # Address
    if len(slug or "") > 60 or len((slug or "").split("-")) > 8:
        add(Check("slug", "Short address", "warn", "Keep the address under about 60 characters.", 1))
    else:
        add(Check("slug", "Short address", "pass", f"{len(slug or '')} characters.", 1))

    # Depth
    if words >= MIN_WORDS:
        add(Check("length", "Depth", "pass", f"{words:,} words.", 2))
    elif words >= MIN_WORDS // 2:
        add(Check("length", "Depth", "warn", f"{words:,} words — guides that rank usually go past {MIN_WORDS}.", 2))
    else:
        add(Check("length", "Depth", "fail", f"{words:,} words — too thin to rank; answer the question fully.", 2))

    # Structure
    if len(h2s) >= MIN_H2:
        add(Check("headings", "Sections", "pass", f"{len(h2s)} section headings.", 2))
    else:
        add(
            Check("headings", "Sections", "warn", f"{len(h2s)} headings — break it into at least {MIN_H2} sections.", 2)
        )
    levels = [max(level, 2) for level, _h in headings]
    skipped = any(b - a > 1 for a, b in zip(levels, levels[1:], strict=False))
    add(
        Check(
            "heading_order",
            "Heading order",
            "warn" if skipped else "pass",
            "A heading level is skipped (e.g. H2 → H4)." if skipped else "No skipped levels.",
            1,
        )
    )
    long_paras = [p for p in _paragraphs(body) if len(_WORD.findall(p)) > MAX_PARAGRAPH_WORDS]
    add(
        Check(
            "paragraphs",
            "Short paragraphs",
            "warn" if long_paras else "pass",
            f"{len(long_paras)} paragraph(s) over {MAX_PARAGRAPH_WORDS} words — split them."
            if long_paras
            else "Easy to scan.",
            1,
        )
    )
    sentences = _SENTENCE.findall(text)
    avg = (sum(len(_WORD.findall(s)) for s in sentences) / len(sentences)) if sentences else 0
    add(
        Check(
            "sentences",
            "Readable sentences",
            "warn" if avg > MAX_SENTENCE_WORDS else "pass",
            f"Sentences average {avg:.0f} words" + (" — shorten some." if avg > MAX_SENTENCE_WORDS else "."),
            1,
        )
    )

    # Links
    if len(internal) >= MIN_INTERNAL_LINKS:
        add(Check("internal_links", "Links to your other articles", "pass", f"{len(internal)} internal links.", 2))
    else:
        add(
            Check(
                "internal_links",
                "Links to your other articles",
                "warn",
                f"{len(internal)} internal link(s) — link {MIN_INTERNAL_LINKS} or more related pages.",
                2,
            )
        )
    add(
        Check(
            "external_links",
            "A source for facts",
            "pass" if external else "warn",
            f"{len(external)} outside source(s)." if external else "Link one authoritative source.",
            1,
        )
    )
    vague = [t for t, _u in links if _norm(t) in {"here", "click here", "this", "link", "read more"}]
    add(
        Check(
            "link_text",
            "Descriptive link text",
            "warn" if vague else "pass",
            "Replace “click here” style link text." if vague else "Links say where they go.",
            1,
        )
    )

    # Images
    body_images = _IMAGE.findall(body or "")
    missing_alt = [u for alt, u in body_images if not alt.strip()]
    if has_image and not (image_alt or "").strip():
        add(Check("cover_alt", "Cover alt text", "fail", "Describe the cover image for screen readers and search.", 2))
    elif has_image:
        add(Check("cover_alt", "Cover alt text", "pass", "The cover is described.", 2))
    else:
        add(Check("cover_alt", "Cover image", "warn", "Add a cover: shared links and search look better with one.", 1))
    if missing_alt:
        add(
            Check(
                "image_alt", "Image alt text", "fail", f"{len(missing_alt)} image(s) in the text have no alt text.", 1
            )
        )

    # Questions and summary
    add(
        Check(
            "faq",
            "Answers readers' questions",
            "pass" if faq else "warn",
            f"{len(faq)} question(s) answered." if faq else "Add 2–4 questions people ask, with short answers.",
            1,
        )
    )
    add(
        Check(
            "excerpt",
            "Summary for the blog index",
            "pass" if (excerpt or "").strip() else "warn",
            "Present." if (excerpt or "").strip() else "Write one or two sentences for the card on the blog page.",
            1,
        )
    )

    # Duplicates on the site
    if other_titles:
        dup = _norm(title) in {_norm(t) for t in other_titles if t}
        add(
            Check(
                "duplicate",
                "Unique title on the site",
                "fail" if dup else "pass",
                "Another article has this title — choose another." if dup else "No other article uses it.",
                2,
            )
        )

    total = sum(c.weight for c in checks)
    earned = sum(c.weight * (1.0 if c.level == "pass" else 0.5 if c.level == "warn" else 0.0) for c in checks)
    value = round(100 * earned / total) if total else 0
    grade = "Good — ready to rank" if value >= 80 else "Getting there" if value >= 60 else "Needs work"
    return Report(score=value, grade=grade, checks=checks, words=words, title_tag=tag)


def _score_saved(post, other_titles: list[str]) -> Report:
    return score(
        title=post.title,
        slug=post.slug,
        body=post.body,
        seo_title=post.seo_title,
        meta_description=post.meta_description,
        excerpt=post.excerpt,
        focus_keyword=getattr(post, "focus_keyword", ""),
        secondary_keywords=getattr(post, "secondary_keywords", []) or [],
        faq=post.faq or [],
        image_alt=post.featured_image_alt,
        has_image=bool(post.featured_image_id) or post.cover_style == "designed",
        site_kind=post.site.kind if post.site_id else "",
        site_origin=post.site.origin if post.site_id else "",
        other_titles=other_titles,
    )


def score_post(post, *, exclude_self: bool = True) -> Report:
    """Score a saved ``BlogPost`` against its site's other articles."""
    from .models import BlogPost

    others = BlogPost.objects.filter(site_id=post.site_id)
    if exclude_self and post.pk:
        others = others.exclude(pk=post.pk)
    return _score_saved(post, list(others.values_list("title", flat=True)[:500]))


def score_posts(posts) -> dict:
    """Score several saved posts with one query for their sites' titles: ``{post.pk: Report}``.

    For the blog list and the SEO monitor, where :func:`score_post` per row
    would query the titles once per article.
    """
    from .models import BlogPost

    posts = list(posts)
    titles: dict = defaultdict(list)
    site_ids = {p.site_id for p in posts if p.site_id}
    for site_id, pk, title in BlogPost.objects.filter(site_id__in=site_ids).values_list("site_id", "pk", "title"):
        titles[site_id].append((pk, title))
    return {post.pk: _score_saved(post, [t for pk, t in titles[post.site_id] if pk != post.pk][:500]) for post in posts}


# ---------------------------------------------------------------------------
# What the SEO monitor suggests for a published article
# ---------------------------------------------------------------------------

#: Below this many impressions in 28 days, a query is too thin to act on.
MIN_QUERY_IMPRESSIONS = 20
#: A drop of this many places in average position is worth a refresh.
SLIPPED_PLACES = 3.0


def suggestion(report: Report | None, perf: dict | None) -> str:
    """One plain sentence: the most useful next step for a published article.

    ``perf`` is :func:`apps.blog.search_console.page_trend` (or None when
    Search Console isn't connected): position, the change, clicks,
    impressions, CTR and the top queries. Rankings come first — they are the
    point — then the score.
    """
    if perf and perf.get("impressions"):
        queries = [q for q in perf.get("queries", []) if q["impressions"] >= MIN_QUERY_IMPRESSIONS]
        page_two = next((q for q in queries if 10.5 < q["position"] <= 20.5), None)
        if page_two:
            return (
                f"Stuck on page 2 for “{page_two['query']}” (position {page_two['position']:.0f}) — "
                "add a section that answers it."
            )
        change = perf.get("position_change")
        if change is not None and change <= -SLIPPED_PLACES:
            return (
                f"Slipped {abs(change):.0f} places in Google over 28 days — refresh the facts and the year, "
                "and add what's new."
            )
        edge = next((q for q in queries if 7.5 < q["position"] <= 10.5), None)
        if edge:
            return f"“{edge['query']}” sits at the bottom of page 1 — a short section on it could lift it."
        if perf["impressions"] >= 200 and perf.get("ctr", 0) < 0.01 and perf.get("position", 99) <= 10:
            return (
                f"Seen {perf['impressions']:,} times but rarely clicked — rewrite the search title and "
                "description so they promise the answer."
            )
    elif perf is not None:
        return "No Google impressions yet — link to it from two of your other articles so Google finds it."
    if report is not None and report.score < 80 and report.to_fix:
        first = report.to_fix[0]
        return f"Score {report.score} — fix: {first.label.lower()}: {first.detail}"
    return "Doing well — nothing to change this week."
