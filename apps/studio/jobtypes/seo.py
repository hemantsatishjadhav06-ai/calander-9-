"""The ``seo`` job: the SEO monitor's check-up of a workspace's live articles.

One stage, run by the SEO monitor (a code agent: no model, no cost). For every
published article it takes the SEO score (``apps.blog.seo``) and, when the
website is connected to Google Search Console, the last 28 days against the
28 before (``apps.blog.search_console.page_trend``), and writes one plain
suggestion per article — "stuck on page 2 for 'X' — add a section answering
it", "score 58 — fix: …". The articles that most need a hand come first.

It reads and writes nothing else: no draft is changed, nothing is approved,
scheduled or published. A person decides what to do with the suggestions.
Queued weekly by ``apps.blog.tasks.queue_seo_checkups`` and on demand from
the blog list ("Run a check-up").
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from .. import engine

#: At most this many articles in one check-up's result.
MAX_PAGES = 50


def _needs_attention(page: dict) -> tuple:
    """Sort key: slipping or stuck articles first, then the lowest scores."""
    change = page["position_change"]
    slipping = change is not None and change < 0
    return (not slipping, page["score"], -(page["impressions"] or 0), page["title"])


def check_workspace(workspace, *, today=None) -> list[dict]:
    """One row per published article of ``workspace``: score, rankings and a suggestion."""
    from apps.blog import search_console, seo
    from apps.blog.models import BlogPost, BlogSite

    posts = list(
        BlogPost.objects.filter(workspace=workspace, status=BlogPost.Status.PUBLISHED)
        .select_related("site")
        .order_by("-published_at")[:500]
    )
    reports = seo.score_posts(posts)
    connected = {
        site.pk
        for site in BlogSite.objects.filter(workspace=workspace).select_related("search_console")
        if search_console.is_connected(getattr(site, "search_console", None))
    }
    pages = []
    for post in posts:
        report = reports[post.pk]
        trend = None
        if post.site_id in connected:
            trend = search_console.page_trend(post.site, post.published_url or post.expected_url, today=today)
        pages.append(
            {
                "post_id": str(post.pk),
                "title": post.title,
                "url": post.published_url or post.expected_url,
                "score": report.score,
                "position": trend["position"] if trend and trend["impressions"] else None,
                "position_change": trend["position_change"] if trend else None,
                "clicks": trend["clicks"] if trend else None,
                "impressions": trend["impressions"] if trend else None,
                "suggestion": seo.suggestion(report, trend),
            }
        )
    pages.sort(key=_needs_attention)
    return pages[:MAX_PAGES]


def _summary(pages: list[dict]) -> str:
    if not pages:
        return "No published articles to check yet."
    low = sum(1 for p in pages if p["score"] < 70)
    slipping = sum(1 for p in pages if p["position_change"] is not None and p["position_change"] <= -3)
    lines = [
        f"Checked {len(pages)} published article{'s' if len(pages) != 1 else ''}. "
        f"{low} score{'s' if low != 1 else ''} under 70; {slipping} slipped in Google over the last 28 days."
    ]
    for page in pages[:5]:
        lines.append(f"• {page['title']}: {page['suggestion']}")
    return "\n".join(lines)


def check(job):
    run = engine.begin(job, "seo_monitor")
    pages = check_workspace(job.workspace)
    summary = _summary(pages)
    engine.end(
        run,
        summary=summary.splitlines()[0],
        output={"articles": len(pages), "to_fix": sum(1 for p in pages if p["score"] < 70)},
    )
    engine.finish(
        job,
        result={"pages": pages, "summary": summary, "checked_at": timezone.now().isoformat(timespec="seconds")},
    )
    return None


JOB = engine.JobType(
    kind="seo",
    stages=(engine.Stage("check", "seo_monitor", check),),
    priority=engine.PRIORITY_BACKGROUND,
    stuck_after=timedelta(minutes=30),
)
