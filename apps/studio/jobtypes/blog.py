"""The ``blog`` job: the SEO team writes an article, or revises one, and hands it to a person.

A new article goes through every stage:

1. **research** — the SEO strategist picks the focus keyword, the searcher's
   intent, related terms, reader questions and links to the site's own live
   articles (after a web search for what ranks, when web search is on);
2. **outline** — the outline editor plans the headings, the answer-first
   intro and the FAQ;
3. **write** — the blog writer writes the Markdown article (a long, streamed
   answer);
4. **fact_check** — the fact checker reads every claim against the brand
   facts; unsupported claims go back to the writer once, and anything left is
   flagged to the approver;
5. **seo** — the SEO editor writes the title tag, description, address and
   alt text and fixes what ``apps.blog.seo.score`` flags, with a second pass
   when the score is still under 70;
6. **edit** — the editor-in-chief's final read, with at most one send-back;
7. **cover** — when pictures are switched on, the prompt engineer writes the
   cover prompt from the creative memory and the illustrator paints it (a
   failure is fine: the designed cover falls back to the brand background);
8. **produce** — the producer saves the draft through ``apps.blog.services``
   and submits it for approval.

A revision (``blog_post`` set, input ``{"revision_of", "feedback"}``) skips
research and the outline and starts at the writer with the current article.

Every link in the article is checked in code: links to the site's own
articles must be ones the strategist was given, and outside links must be
URLs from the brand facts, the brief or the web research. Anything else is
turned back into plain text. Nothing here approves or publishes: the draft
waits for an approver on the dashboard like any other.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q

from .. import budget, engine, llm
from ..models import AgencyJob, AgencySettings, AgentRun
from ..roles import creative, quality
from ..roles import seo as seo_roles

logger = logging.getLogger(__name__)

#: Passes back to the writer the fact checker and the editor-in-chief may ask for.
AUTO_FACT_PASSES = 1
AUTO_EDITOR_PASSES = 1
#: Under this SEO score after the first SEO edit, the SEO editor gets one more pass.
SEO_TARGET = 70
MAX_SEO_PASSES = 2
MAX_SEO_EDITS = 12
MAX_LINK_TARGETS = 40
MAX_SOURCES = 12
MAX_FAQ = 6
#: What "Improve SEO" asks for.
IMPROVE_SEO_FEEDBACK = "Fix everything the SEO score flags"
COVER_SIZE = {"width": 1600, "height": 896}
#: Checked against the storage quota before fal.ai is paid for a picture.
COVER_ESTIMATED_BYTES = 2_000_000
#: An article shorter than this came back broken, not short.
MIN_ARTICLE_WORDS = 150
#: Fields that may not yet be part of ``apps.blog.services.CONTENT_FIELDS``.
KEYWORD_FIELDS = ("focus_keyword", "secondary_keywords")

_URL = re.compile(r"https?://[^\s<>()\[\]\"'`]+")
_MD_LINK = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_H1 = re.compile(r"^#\s+")
_WORD = re.compile(r"\w+", re.UNICODE)


# ---------------------------------------------------------------------------
# Starting a job (callers check permissions and the budget first)
# ---------------------------------------------------------------------------


def start_article(
    workspace,
    *,
    topic: str,
    site,
    requested_by,
    focus_keyword: str = "",
    notes: str = "",
    category: str = "",
    parent: AgencyJob | None = None,
    conversation=None,
) -> AgencyJob:
    """Queue the SEO team on a new article for ``site``."""
    topic = " ".join((topic or "").split())[:300]
    return engine.create(
        workspace,
        AgencyJob.Kind.BLOG,
        title=f"Article: {topic}",
        input={
            "topic": topic,
            "site_id": str(site.pk),
            "focus_keyword": " ".join((focus_keyword or "").split())[:80],
            "notes": (notes or "").strip()[:2000],
            "category": " ".join((category or "").split())[:60],
        },
        requested_by=requested_by,
        parent=parent,
        conversation=conversation,
    )


def start_revision(
    post, *, feedback: str, requested_by, parent: AgencyJob | None = None, conversation=None
) -> AgencyJob:
    """Queue the SEO team on a change to ``post``."""
    return engine.create(
        post.workspace,
        AgencyJob.Kind.BLOG,
        title=f"Revise: {post.title}",
        input={"revision_of": str(post.pk), "feedback": (feedback or "").strip()[:4000] or IMPROVE_SEO_FEEDBACK},
        requested_by=requested_by,
        blog_post=post,
        parent=parent,
        conversation=conversation,
    )


def active_job(post, kinds: Iterable[str] = (AgencyJob.Kind.BLOG, AgencyJob.Kind.REPURPOSE)) -> AgencyJob | None:
    """The team's unfinished job on ``post``, if any."""
    return (
        AgencyJob.objects.filter(
            workspace_id=post.workspace_id, blog_post=post, kind__in=list(kinds), status__in=AgencyJob.ACTIVE_STATUSES
        )
        .order_by("-created_at")
        .first()
    )


# ---------------------------------------------------------------------------
# Helpers shared with the repurpose job
# ---------------------------------------------------------------------------


def need_budget(job: AgencyJob) -> None:
    """Stop before new model work once the workspace's monthly budget is used."""
    if not budget.can_spend(job.workspace):
        raise engine.JobError(budget.over_budget_message(job.workspace))


def profile_for(job: AgencyJob):
    from ..brand_defaults import ensure_profile

    return ensure_profile(job.workspace)


def post_for(job: AgencyJob):
    """The job's blog post — re-checked to belong to the job's workspace."""
    from apps.blog.models import BlogPost

    post = (
        BlogPost.objects.select_related("site", "workspace", "featured_image", "author")
        .filter(pk=job.blog_post_id, workspace_id=job.workspace_id)
        .first()
        if job.blog_post_id
        else None
    )
    if post is None:
        raise engine.JobError("The article this was for has been deleted, so there is nothing to work on.")
    return post


def site_for(job: AgencyJob, site_id: Any = None):
    """The job's website — re-checked to belong to the job's workspace."""
    from apps.blog.models import BlogSite

    raw = site_id or (job.state or {}).get("site_id")
    site = None
    if raw:
        try:
            site = BlogSite.objects.filter(pk=str(raw), workspace_id=job.workspace_id).first()
        except (ValueError, ValidationError):
            site = None
    if site is None:
        raise engine.JobError("The website for this article isn't connected to this workspace any more.")
    return site


def may_write(user, workspace) -> bool:
    """A member of the agency's staff (not a plain client) who may create posts here."""
    from apps.members.models import WorkspaceMembership

    from ..views import is_plain_client

    if user is None or not getattr(user, "is_active", False):
        return False
    membership = (
        WorkspaceMembership.objects.filter(user=user, workspace=workspace).select_related("custom_role").first()
    )
    if membership is None or is_plain_client(membership):
        return False
    return bool(membership.effective_permissions.get("create_posts"))


def author_for(job: AgencyJob, *, post=None):
    """Whose name the draft carries: the person who asked, else the workspace's agency lead.

    Re-checked when the draft is made, so someone who lost their rights while
    the team worked can't end up as its author. For a revision the person must
    also be allowed to edit that article.
    """
    from apps.blog import services as blog_services

    candidates = [job.requested_by]
    agency = AgencySettings.objects.filter(workspace_id=job.workspace_id).select_related("lead").first()
    if agency is not None and agency.lead is not None:
        candidates.append(agency.lead)
    for user in candidates:
        if may_write(user, job.workspace) and (post is None or blog_services.can_edit(user, post)):
            return user
    raise engine.JobError(
        "Nobody who may write here asked for this, so the team can't save it under anyone's name. Ask again, or "
        "choose a team lead under Agency → Autopilot."
    )


def article_of(post) -> dict[str, Any]:
    """A saved post as the team's draft."""
    return {
        "title": post.title,
        "body": post.body,
        "excerpt": post.excerpt,
        "faq": [{"q": str(i.get("q", "")), "a": str(i.get("a", ""))} for i in post.faq or [] if isinstance(i, dict)],
        "seo_title": post.seo_title,
        "meta_description": post.meta_description,
        "slug": post.slug,
        "featured_image_alt": post.featured_image_alt,
        "category": post.category,
        "focus_keyword": getattr(post, "focus_keyword", "") or "",
        "secondary_keywords": list(getattr(post, "secondary_keywords", []) or []),
        "has_image": bool(post.featured_image_id) or post.cover_style == "designed",
    }


def clip(text: Any, limit: int) -> str:
    """One line, at most ``limit`` characters, cut at a word where possible."""
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    cut = text[: limit + 1].rsplit(" ", 1)[0].rstrip(",.;:-–— ")
    return (cut or text)[:limit]


# ---------------------------------------------------------------------------
# Links, slugs and scoring (plain code, no model)
# ---------------------------------------------------------------------------


def link_targets(site, *, exclude=None) -> list[dict[str, str]]:
    """The site's live articles a new one may link to: ``[{"title", "url"}]``."""
    from apps.blog.models import BlogPost

    rows = (
        BlogPost.objects.filter(site=site, workspace_id=site.workspace_id)
        .filter(Q(status=BlogPost.Status.PUBLISHED) | ~Q(published_url=""))
        .select_related("site")
        .order_by("-published_at", "-updated_at")
    )
    if exclude is not None:
        rows = rows.exclude(pk=exclude)
    targets = []
    for post in rows[:MAX_LINK_TARGETS]:
        title = (post.published_card or {}).get("title") or post.title
        targets.append({"title": str(title)[:200], "url": post.published_url or post.expected_url})
    return targets


def urls_in(*texts: str) -> list[str]:
    found: list[str] = []
    for text in texts:
        for match in _URL.findall(text or ""):
            url = match.rstrip(".,;:!?")
            if url not in found:
                found.append(url)
    return found


def _norm(url: str) -> str:
    return url.strip().rstrip("/").lower()


def clean_links(body: str, allowed: Iterable[str], facts: str = "") -> tuple[str, list[str]]:
    """Keep only links the team was given; others become plain text. Images are dropped.

    ``allowed`` are absolute URLs (the site's articles, sources from the facts,
    the brief or the web research) and links already in an article being
    revised. A relative link is kept when its path is one of theirs; ``tel:``
    and ``mailto:`` links only when the number or address is in the facts.
    """
    allowed = [u for u in allowed if u]
    exact = {_norm(u) for u in allowed}
    paths = {_norm(urlsplit(u).path) for u in allowed if u.startswith("http") and urlsplit(u).path not in ("", "/")}
    digits = re.sub(r"\D", "", facts or "")
    removed: list[str] = []

    def keep(match: re.Match) -> str:
        text, url = match.group(1), match.group(2).strip()
        norm = _norm(url)
        if norm in exact or url.startswith("#"):
            return match.group(0)
        if url.startswith("/") and not url.startswith("//") and norm in paths:
            return match.group(0)
        if url.startswith("tel:") and len(re.sub(r"\D", "", url)) >= 6 and re.sub(r"\D", "", url) in digits:
            return match.group(0)
        if url.startswith("mailto:") and url[7:].lower() and url[7:].lower() in (facts or "").lower():
            return match.group(0)
        removed.append(url)
        return text

    body = _MD_IMAGE.sub("", body or "")
    return _MD_LINK.sub(keep, body), removed


def tidy_body(body: str) -> str:
    """The article without a leading H1 (the title is set separately) and with tidy line endings."""
    lines = (body or "").replace("\r\n", "\n").strip().split("\n")
    while lines and (not lines[0].strip() or _H1.match(lines[0])):
        lines.pop(0)
    return "\n".join(lines).strip()


def word_count(body: str) -> int:
    from apps.blog.renderers import plain_text

    return len(_WORD.findall(plain_text(body or "")))


def unique_slug(site, wanted: str, *, title: str, exclude=None) -> str:
    """A short, valid address that no other article on ``site`` uses."""
    from apps.blog.models import RESERVED_SLUGS, BlogPost
    from apps.blog.services import suggest_slug

    base = suggest_slug(wanted) or suggest_slug(title) or "article"
    words = base.split("-")[:8]
    base = "-".join(words)
    while len(base) > 60 and "-" in base:
        base = base.rsplit("-", 1)[0]
    base = base[:60].strip("-") or "article"
    if base in RESERVED_SLUGS:
        base = f"{base}-guide"
    taken_rows = BlogPost.objects.filter(site=site)
    if exclude is not None:
        taken_rows = taken_rows.exclude(pk=exclude)
    taken = set(taken_rows.values_list("slug", flat=True))
    slug, number = base, 2
    while slug in taken or slug in RESERVED_SLUGS:
        slug = f"{base}-{number}"
        number += 1
    return slug


def score_draft(draft: dict[str, Any], site, *, exclude=None):
    """``apps.blog.seo.score`` for a draft that isn't saved yet, against the site's other articles."""
    from apps.blog import seo as blog_seo
    from apps.blog.models import BlogPost

    others = BlogPost.objects.filter(site=site)
    if exclude is not None:
        others = others.exclude(pk=exclude)
    return blog_seo.score(
        title=draft.get("title", ""),
        slug=draft.get("slug", "") or "",
        body=draft.get("body", ""),
        seo_title=draft.get("seo_title", ""),
        meta_description=draft.get("meta_description", ""),
        excerpt=draft.get("excerpt", ""),
        focus_keyword=draft.get("focus_keyword", ""),
        secondary_keywords=draft.get("secondary_keywords") or [],
        faq=draft.get("faq") or [],
        image_alt=draft.get("featured_image_alt", ""),
        has_image=draft.get("has_image", True),
        site_kind=site.kind,
        site_origin=site.origin,
        other_titles=list(others.values_list("title", flat=True)[:500]),
    )


def _faq(items, *, existing: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    out = list(existing or [])
    seen = {" ".join(i["q"].lower().split()) for i in out}
    for item in items or []:
        q = clip(getattr(item, "q", "") or (item.get("q") if isinstance(item, dict) else ""), 300)
        a = (getattr(item, "a", "") or (item.get("a") if isinstance(item, dict) else "") or "").strip()[:1500]
        key = " ".join(q.lower().split())
        if q and a and key not in seen:
            out.append({"q": q, "a": a})
            seen.add(key)
    return out[:MAX_FAQ]


def _allowed_links(state: dict[str, Any]) -> list[str]:
    return [t["url"] for t in state.get("link_targets") or []] + list(state.get("sources") or [])


def _facts_text(profile) -> str:
    return f"{profile.facts or ''}\n{profile.compliance or ''}\n{getattr(profile, 'website', '') or ''}"


def unchanged_since_start(job: AgencyJob, state: dict[str, Any]):
    """For a revision: the article, as long as nobody changed it while the team worked. Else stop.

    A person's own edit (a new revision) or an approval given meanwhile wins:
    the team never overwrites either, and says so.
    """
    from apps.blog.models import BlogPost

    post = post_for(job)
    if post.status == BlogPost.Status.PUBLISHING:
        raise engine.JobError("This article is being published right now. Ask again once publishing finishes.")
    if state.get("base_revision") is not None and post.revision != state["base_revision"]:
        raise engine.JobError(
            "Someone edited this article while the team was working on it, so the team didn't overwrite their "
            "changes. Ask again to work from the latest version."
        )
    settled = (BlogPost.Status.APPROVED, BlogPost.Status.PUBLISHED, BlogPost.Status.FAILED)
    if state.get("base_status") and post.status != state["base_status"] and post.status in settled:
        raise engine.JobError(
            "This article was approved while the team was working on it, so the team didn't change it. Ask again "
            "if you still want the change."
        )
    return post


def _skip(job: AgencyJob, agent: str, stage: str, summary: str) -> None:
    run = engine.begin(job, agent, stage=stage)
    engine.end(run, summary=summary, status=AgentRun.Status.SKIPPED)


def _reject(run: AgentRun, result: llm.AgentResult, message: str) -> None:
    """Close the turn as failed (recording what it cost) and stop the job with ``message``."""
    engine.end(run, summary=message, result=result, status=AgentRun.Status.FAILED)
    raise engine.JobError(message)


def _topic(job: AgencyJob) -> str:
    data = job.input or {}
    return clip(data.get("topic") or (job.state or {}).get("topic") or job.title, 300)


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------


def research(job: AgencyJob) -> str:
    if job.blog_post_id or (job.input or {}).get("revision_of"):
        return _prepare_revision(job)
    from apps.blog.models import BlogPost

    data = job.input or {}
    topic = _topic(job)
    if not topic:
        raise engine.JobError("Say what the article should be about, then ask again.")
    site = site_for(job, data.get("site_id"))
    need_budget(job)
    author_for(job)  # fail before paying for anything if nobody may own the draft
    profile = profile_for(job)
    targets = link_targets(site)
    given = clip(data.get("focus_keyword"), 80).lower()
    notes = (data.get("notes") or "").strip()
    web = _web_research(job, profile, topic, given) if llm.web_search_enabled() else ""
    categories = list(
        BlogPost.objects.filter(site=site).exclude(category="").values_list("category", flat=True).distinct()[:20]
    )
    run, result = engine.call(
        job,
        "seo_strategist",
        lambda: seo_roles.seo_strategist(
            profile,
            topic=topic,
            notes=notes,
            focus_keyword=given,
            category=data.get("category", ""),
            link_targets=targets,
            existing_categories=categories,
            web_research=web,
        ),
        stage="research",
        effort=seo_roles.SEO_STRATEGIST_EFFORT,
    )
    answer = result.output
    allowed = {_norm(t["url"]): t["url"] for t in targets}
    picks = [
        {"url": allowed[_norm(p.url)], "anchor_text": clip(p.anchor_text, 80), "why": clip(p.why, 200)}
        for p in answer.internal_links
        if _norm(p.url) in allowed
    ][:4]
    plan = answer.model_dump()
    plan.update(
        focus_keyword=given or clip(answer.focus_keyword, 80).lower(),
        related_terms=[clip(t, 80) for t in answer.related_terms if t.strip()][:6],
        internal_links=picks,
        category=clip(data.get("category") or answer.category, 60),
    )
    sources = urls_in(_facts_text(profile), topic, notes, web)[:MAX_SOURCES]
    dropped = len(answer.internal_links) - len(picks)
    engine.end(
        run,
        summary=(
            f"Focus keyword “{plan['focus_keyword']}” ({answer.search_intent}); "
            f"{len(answer.reader_questions)} reader questions; {len(picks)} link(s) to your other articles."
        ),
        output={"plan": plan, "links_dropped": dropped},
        result=result,
    )
    engine.update_state(
        job, mode="new", topic=topic, site_id=str(site.pk), research=plan, link_targets=targets, sources=sources
    )
    return "outline"


def _web_research(job: AgencyJob, profile, topic: str, keyword: str) -> str:
    """What currently ranks and what people ask, from a web search (free text, optional)."""
    run = engine.begin(job, "seo_strategist", stage="research", effort="low")
    try:
        found = llm.research(
            agent="seo_strategist",
            system=seo_roles.research_system(profile),
            question=seo_roles.research_question(topic, keyword),
            effort="low",
        )
    except engine.JobError as exc:
        engine.fail_run(run, exc)
        AgentRun.objects.filter(pk=run.pk).update(
            status=AgentRun.Status.SKIPPED, summary="Web search wasn't available; planned from your brand facts."
        )
        return ""
    run.model = found.model
    run.input_tokens, run.output_tokens, run.cache_read_tokens = (
        found.input_tokens,
        found.output_tokens,
        found.cache_read_tokens,
    )
    run.save(update_fields=["model", "input_tokens", "output_tokens", "cache_read_tokens"])
    engine.end(
        run,
        summary=f"Searched the web ({found.web_searches} search(es)) for what ranks and what people ask.",
        output={"web_searches": found.web_searches, "notes": found.text[:6000]},
    )
    return found.text


def _prepare_revision(job: AgencyJob) -> str:
    """A change to an existing article: start at the writer with the article as it is now."""
    from apps.blog.models import BlogPost, BlogPostEvent

    post = post_for(job)
    if post.status == BlogPost.Status.PUBLISHING:
        raise engine.JobError("This article is being published right now. Ask again once publishing finishes.")
    need_budget(job)
    author_for(job, post=post)  # fail before paying for anything if nobody may own the change
    profile = profile_for(job)
    current = article_of(post)
    feedback = ((job.input or {}).get("feedback") or "").strip() or IMPROVE_SEO_FEEDBACK
    if post.status == BlogPost.Status.CHANGES_REQUESTED:
        asked = (
            BlogPostEvent.objects.filter(post=post, action=BlogPostEvent.Action.CHANGES_REQUESTED)
            .order_by("-created_at")
            .values_list("detail", flat=True)
            .first()
        )
        if asked and asked.strip() not in feedback:
            feedback = f"{feedback}\n\nThe approver asked for: {asked.strip()}"
    earlier = (
        AgencyJob.objects.filter(
            workspace_id=job.workspace_id, kind=AgencyJob.Kind.BLOG, blog_post=post, status=AgencyJob.Status.DONE
        )
        .exclude(pk=job.pk)
        .order_by("-finished_at")
        .first()
    )
    plan = dict((earlier.state or {}).get("research") or {}) if earlier else {}
    plan["focus_keyword"] = current["focus_keyword"] or plan.get("focus_keyword", "")
    plan["related_terms"] = current["secondary_keywords"] or plan.get("related_terms", [])
    targets = link_targets(post.site, exclude=post.pk)
    # Links a person already put in the article stay allowed; the writer may keep them.
    existing_links = [url for _text, url in _MD_LINK.findall(post.body or "")]
    sources = list(dict.fromkeys(urls_in(_facts_text(profile))[:MAX_SOURCES] + existing_links))
    for agent, stage in (("seo_strategist", "research"), ("outline_editor", "outline")):
        _skip(job, agent, stage, "Not needed: this is a change to an existing article.")
    engine.update_state(
        job,
        mode="revision",
        topic=post.title,
        site_id=str(post.site_id),
        base_revision=post.revision,
        base_status=post.status,
        feedback=feedback,
        current=current,
        draft=current,
        research=plan,
        link_targets=targets,
        sources=sources,
    )
    return "write"


def outline(job: AgencyJob) -> str:
    state = job.state or {}
    if state.get("mode") == "revision":
        return "write"
    need_budget(job)
    profile = profile_for(job)
    run, result = engine.call(
        job,
        "outline_editor",
        lambda: seo_roles.outline_editor(
            profile,
            topic=_topic(job),
            notes=(job.input or {}).get("notes", ""),
            research=state.get("research") or {},
            link_targets=state.get("link_targets") or [],
        ),
        stage="outline",
        effort=seo_roles.OUTLINE_EDITOR_EFFORT,
    )
    plan = result.output.model_dump()
    plan["target_words"] = max(600, min(2000, int(plan.get("target_words") or 1200)))
    h2 = sum(1 for s in plan["sections"] if s.get("level") == "h2")
    if h2 == 0:
        _reject(run, result, "The outline came back without any sections. Press Retry.")
    engine.end(
        run,
        summary=(
            f"“{clip(plan['title'], 90)}”: {h2} sections, {len(plan['faq_questions'])} FAQ questions, "
            f"about {plan['target_words']:,} words."
        ),
        output={"outline": plan},
        result=result,
    )
    engine.update_state(job, outline=plan)
    return "write"


def write(job: AgencyJob) -> str:
    state = job.state or {}
    if state.get("mode") == "revision":
        unchanged_since_start(job, state)  # stop before paying for more work on an article that moved on
    need_budget(job)
    profile = profile_for(job)
    site = site_for(job)
    revision = state.get("mode") == "revision"
    fixes = list(state.get("fixes") or [])
    previous = state.get("draft") if (revision or fixes) else None
    seo_checks = None
    if revision:
        report = score_draft(previous or {}, site, exclude=job.blog_post_id)
        seo_checks = [f"{c.label}: {c.detail}" for c in report.to_fix]
    run, result = engine.call(
        job,
        "blog_writer",
        lambda: seo_roles.blog_writer(
            profile,
            topic=_topic(job),
            notes=(job.input or {}).get("notes", ""),
            research=state.get("research") or {},
            outline=state.get("outline"),
            link_targets=state.get("link_targets") or [],
            sources=list(state.get("sources") or []),
            current=previous,
            change_request=state.get("feedback", "") if revision else "",
            fixes=fixes,
            fixes_from=state.get("fixes_from", ""),
            seo_checks=seo_checks,
        ),
        stage="write",
        effort=seo_roles.BLOG_WRITER_EFFORT,
    )
    answer = result.output
    body, removed = clean_links(tidy_body(answer.body), _allowed_links(state), _facts_text(profile))
    words = word_count(body)
    if words < MIN_ARTICLE_WORDS:
        _reject(run, result, "The writer's article came back too short to use. Press Retry.")
    research_plan = state.get("research") or {}
    draft = dict(previous or {})
    draft.update(
        title=clip(answer.title, 200) or draft.get("title", ""),
        body=body,
        excerpt=clip(answer.excerpt, 400) or draft.get("excerpt", ""),
        faq=_faq(answer.faq) or draft.get("faq", []),
        focus_keyword=research_plan.get("focus_keyword", "") or draft.get("focus_keyword", ""),
        secondary_keywords=list(research_plan.get("related_terms") or draft.get("secondary_keywords") or []),
    )
    if not revision:
        draft.setdefault("category", research_plan.get("category", ""))
        draft["has_image"] = True  # new articles get the designed cover
    passes = int(state.get("write_passes", 0)) + 1
    who = {"fact_checker": "the fact checker's", "editor_in_chief": "the editor-in-chief's"}.get(
        state.get("fixes_from", ""), ""
    )
    if fixes and who:
        summary = f"Rewrote it with {who} fixes: {words:,} words."
    elif revision:
        summary = f"Revised the article as asked: {words:,} words."
    else:
        summary = f"Wrote “{clip(draft['title'], 90)}”: {words:,} words."
    if removed:
        summary += f" Removed {len(removed)} link(s) that weren't from your site or your facts."
    engine.end(
        run, summary=summary, output={"words": words, "notes": answer.notes, "links_removed": removed}, result=result
    )
    engine.update_state(job, draft=draft, fixes=[], fixes_from="", write_passes=passes)
    return "fact_check"


def fact_check(job: AgencyJob) -> str:
    state = job.state or {}
    if state.get("mode") == "revision":
        unchanged_since_start(job, state)  # stop before paying for more work on an article that moved on
    need_budget(job)
    profile = profile_for(job)
    draft = state.get("draft") or {}
    run, result = engine.call(
        job,
        "fact_checker",
        lambda: quality.fact_checker(
            profile, article=draft, topic=_topic(job), notes=(job.input or {}).get("notes", "")
        ),
        stage="fact_check",
        effort=quality.FACT_CHECKER_EFFORT,
    )
    answer = result.output
    claims = [claim for claim in answer.unsupported if claim.claim.strip()]
    passes = int(state.get("fact_passes", 0))
    if claims and passes < AUTO_FACT_PASSES:
        engine.end(
            run,
            summary=f"Found {len(claims)} claim(s) your brand facts don't support; sent them back to the writer.",
            output=answer.model_dump(),
            result=result,
        )
        engine.update_state(
            job,
            fixes=[f"“{clip(c.claim, 300)}” — {clip(c.fix, 300)}" for c in claims][:12],
            fixes_from="fact_checker",
            fact_passes=passes + 1,
        )
        return "write"
    flags = [f"“{clip(c.claim, 200)}” ({clip(c.why, 120)})" for c in claims][:10]
    summary = (
        f"Checked {answer.claims_checked} claim(s): all supported by your brand facts."
        if not flags
        else f"{len(flags)} claim(s) still need a person's check; they're flagged for the approver."
    )
    engine.end(run, summary=summary, output=answer.model_dump(), result=result)
    engine.update_state(job, fact_flags=flags)
    return "seo"


def seo(job: AgencyJob) -> str:
    from apps.blog.models import BlogPost

    state = job.state or {}
    if state.get("mode") == "revision":
        unchanged_since_start(job, state)
    need_budget(job)
    profile = profile_for(job)
    site = site_for(job)
    revision = state.get("mode") == "revision"
    exclude = job.blog_post_id
    draft = dict(state.get("draft") or {})
    taken_rows = BlogPost.objects.filter(site=site)
    if exclude is not None:
        taken_rows = taken_rows.exclude(pk=exclude)
    taken = list(taken_rows.values_list("slug", flat=True)[:300])
    before = report = score_draft(draft, site, exclude=exclude)
    notes, passes = "", 0
    while passes < MAX_SEO_PASSES:
        if passes and report.score >= SEO_TARGET:
            break
        if passes:
            need_budget(job)
        draft, report, notes = _seo_pass(
            job, profile, site, draft, report, taken=taken, keep_slug=revision, previous_notes=notes
        )
        passes += 1
    engine.update_state(
        job,
        draft=draft,
        seo={
            "before": before.score,
            "after": report.score,
            "passes": passes,
            "to_fix": [c.label for c in report.to_fix],
        },
    )
    return "edit"


def _seo_pass(job, profile, site, draft, report, *, taken, keep_slug, previous_notes):
    state = job.state or {}
    checks = [{"key": c.key, "label": c.label, "level": c.level, "detail": c.detail} for c in report.to_fix]
    run, result = engine.call(
        job,
        "seo_editor",
        lambda: seo_roles.seo_editor(
            profile,
            article=draft,
            related_terms=draft.get("secondary_keywords") or [],
            checks=checks,
            link_targets=state.get("link_targets") or [],
            taken_slugs=taken,
            site_name=site.name,
            previous_notes=previous_notes,
        ),
        stage="seo",
        effort=seo_roles.SEO_EDITOR_EFFORT,
    )
    answer = result.output
    draft = dict(draft)
    if answer.seo_title.strip():
        draft["seo_title"] = clip(answer.seo_title, 60)
    if answer.meta_description.strip():
        draft["meta_description"] = clip(answer.meta_description, 160)
    if not keep_slug or not draft.get("slug"):
        draft["slug"] = unique_slug(
            site, answer.slug or draft.get("title", ""), title=draft.get("title", ""), exclude=job.blog_post_id
        )
    if answer.featured_image_alt.strip():
        draft["featured_image_alt"] = clip(answer.featured_image_alt, 300)
    if answer.category.strip() and not (job.input or {}).get("category") and not (keep_slug and draft.get("category")):
        draft["category"] = clip(answer.category, 60)
    if answer.excerpt.strip():
        draft["excerpt"] = clip(answer.excerpt, 400)
    body, applied, skipped = draft.get("body", ""), 0, 0
    for edit in answer.body_edits[:MAX_SEO_EDITS]:
        if edit.find and edit.replace.strip() and body.count(edit.find) == 1:
            body = body.replace(edit.find, edit.replace.strip(), 1)
            applied += 1
        else:
            skipped += 1
    body, removed = clean_links(tidy_body(body), _allowed_links(state), _facts_text(profile))
    if word_count(body) >= MIN_ARTICLE_WORDS:
        draft["body"] = body
    if answer.faq_additions:
        draft["faq"] = _faq(answer.faq_additions, existing=draft.get("faq") or [])
    after = score_draft(draft, site, exclude=job.blog_post_id)
    summary = f"SEO score {report.score} → {after.score}. {answer.notes}".strip()
    engine.end(
        run,
        summary=summary[:500],
        output={
            "before": report.score,
            "after": after.score,
            "report": after.as_dict(),
            "edits_applied": applied,
            "edits_skipped": skipped,
            "links_removed": removed,
            "notes": answer.notes,
        },
        result=result,
    )
    return draft, after, answer.notes


def edit(job: AgencyJob) -> str:
    state = job.state or {}
    if state.get("mode") == "revision":
        unchanged_since_start(job, state)  # stop before paying for more work on an article that moved on
    need_budget(job)
    profile = profile_for(job)
    run, result = engine.call(
        job,
        "editor_in_chief",
        lambda: quality.editor_in_chief(
            profile,
            article=state.get("draft") or {},
            topic=_topic(job),
            plan=state.get("research") or {},
            seo_score=(state.get("seo") or {}).get("after"),
            open_flags=state.get("fact_flags") or [],
        ),
        stage="edit",
        effort=quality.EDITOR_IN_CHIEF_EFFORT,
    )
    answer = result.output
    fixes = [clip(fix, 400) for fix in answer.fixes if fix.strip()]
    passes = int(state.get("editor_passes", 0))
    if answer.verdict == "revise" and fixes and passes < AUTO_EDITOR_PASSES:
        engine.end(
            run, summary=f"Sent it back to the writer: {answer.summary}", output=answer.model_dump(), result=result
        )
        engine.update_state(job, fixes=fixes[:10], fixes_from="editor_in_chief", editor_passes=passes + 1)
        return "write"
    notes = [clip(n, 300) for n in answer.notes_for_approver if n.strip()]
    if answer.verdict == "revise":
        notes += fixes
    engine.end(run, summary=answer.summary, output=answer.model_dump(), result=result)
    engine.update_state(job, editor_notes=notes[:10])
    return "cover"


def cover(job: AgencyJob) -> str:
    from .. import images, memory

    state = job.state or {}
    draft = state.get("draft") or {}
    if state.get("mode") == "revision" and post_for(job).featured_image_id:
        _skip(job, "illustrator", "cover", "Kept the article's picture.")
        return "produce"
    if not images.is_configured():
        _skip(
            job, "illustrator", "cover", "Pictures aren't switched on, so the designed cover uses your brand colours."
        )
        return "produce"
    if not budget.can_spend(job.workspace):
        _skip(job, "illustrator", "cover", "This month's AI budget is used up, so the cover uses your brand colours.")
        return "produce"
    profile = profile_for(job)
    title = draft.get("title", "")
    spec = {
        "template": "editorial",
        "format": "landscape",
        "grade": profile.default_grade,
        "picture_prompt": (state.get("research") or {}).get("cover_idea")
        or f"A photograph that represents the article “{title}”",
        "picture_style": profile.photo_style,
    }
    try:
        remembered = memory.prompt_memory(job.workspace)
        references = memory.reference_images(job.workspace, 2)
    except Exception:
        logger.exception("Blog job %s: couldn't read the creative memory", job.pk)
        remembered, references = {}, []
    try:
        run, result = engine.call(
            job,
            "prompt_engineer",
            lambda: creative.prompt_engineer(profile, spec, remembered, reference_images=references),
            stage="cover",
            effort=creative.PROMPT_ENGINEER_EFFORT,
        )
    except engine.JobError:
        _skip(job, "illustrator", "cover", "No cover prompt, so the designed cover uses your brand colours.")
        return "produce"
    answer = result.output
    engine.end(
        run,
        summary=f"Wrote the cover prompt. {answer.references_used}"[:500],
        output=answer.model_dump(),
        result=result,
    )
    asset = _paint(job, answer.prompt, answer.picture_style, title)
    if asset is not None:
        engine.update_state(job, cover_asset_id=str(asset.pk))
    return "produce"


def _paint(job: AgencyJob, prompt: str, style: str, title: str):
    """The cover picture from fal.ai, saved to the media library. None when it couldn't be made."""
    from django.core.files.base import ContentFile

    from apps.blog import ai_images
    from apps.media_library.models import MediaAsset
    from apps.media_library.quotas import StorageQuotaExceededError, enforce_storage_quota
    from apps.media_library.tasks import process_media_asset

    from .. import images

    run = engine.begin(job, "illustrator", stage="cover")
    workspace = job.workspace
    try:
        enforce_storage_quota(workspace.organization, COVER_ESTIMATED_BYTES)
        generated = ai_images.generate_from_prompt(images.build_prompt(prompt, style), image_size=COVER_SIZE)
        width, height = ai_images.validate_image(generated.content)
        enforce_storage_quota(workspace.organization, len(generated.content))
    except StorageQuotaExceededError:
        engine.end(
            run,
            summary="Out of storage, so the designed cover uses your brand colours.",
            status=AgentRun.Status.SKIPPED,
        )
        return None
    except ai_images.ImageGenerationError as exc:
        engine.end(
            run,
            summary=f"No picture ({exc}); the designed cover uses your brand colours."[:500],
            status=AgentRun.Status.SKIPPED,
        )
        return None
    filename = f"blog-cover-{str(job.pk)[:8]}-r{job.revision}.{generated.extension}"
    asset = MediaAsset.objects.create(
        organization=workspace.organization,
        workspace=workspace,
        uploaded_by=job.requested_by,
        file=ContentFile(generated.content, name=filename),
        filename=filename,
        title=f"AI cover: {title}"[:255],
        media_type=MediaAsset.MediaType.IMAGE,
        mime_type=generated.content_type,
        file_size=len(generated.content),
        width=width,
        height=height,
        source="fal.ai",
        attribution=f"Generated with {generated.model} on fal.ai",
        alt_text=title[:500],
        tags=["ai", "blog-cover"],
    )
    process_media_asset(str(asset.id))
    engine.end(run, summary="Painted the cover picture.", output={"asset_id": str(asset.pk), "model": generated.model})
    return asset


def produce(job: AgencyJob) -> None:
    from apps.blog import seo as blog_seo

    state = job.state or {}
    run = engine.begin(job, "producer", stage="produce")
    try:
        if state.get("mode") == "revision":
            post = _save_revision(job, state)
            summary = f"Saved the revised “{clip(post.title, 80)}” and sent it for approval."
        else:
            post = _save_new(job, state)
            summary = f"Saved “{clip(post.title, 80)}” as a draft and sent it for approval."
    except engine.JobError as exc:
        engine.end(run, summary=str(exc)[:500], status=AgentRun.Status.FAILED)
        raise
    report = blog_seo.score_post(post)
    summary += f" SEO score {report.score}."
    engine.end(run, summary=summary, output={"blog_post_id": str(post.pk), "score": report.score})
    engine.finish(job, result={"blog_post_id": str(post.pk), "score": report.score, "summary": summary})
    _notify(job, post, revised=state.get("mode") == "revision")
    return None


def _split_keywords(changes: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Content the blog's services take, and the keyword fields they don't take (yet).

    When ``apps.blog.services.CONTENT_FIELDS`` covers the keywords (they are
    rendered on the page, so they belong in the fingerprint), they go through
    the service with everything else. Until then they are written next to it:
    they aren't part of what is published, so that can't change an approved
    article behind its approval.
    """
    from apps.blog import services as blog_services

    extra = {k: changes.pop(k) for k in KEYWORD_FIELDS if k in changes and k not in blog_services.CONTENT_FIELDS}
    return changes, extra


def _check_before_approving(state: dict[str, Any]) -> str:
    notes = list(state.get("fact_flags") or []) + list(state.get("editor_notes") or [])
    return ("\nCheck before approving: " + "; ".join(notes)) if notes else ""


def _label_event(post, action: str, detail: str) -> None:
    """Say on the audit trail that the SEO team made this revision (the row was written moments ago)."""
    from apps.blog.models import BlogPostEvent

    event = (
        BlogPostEvent.objects.filter(post=post, action=action, revision=post.revision).order_by("-created_at").first()
    )
    if event is not None and not event.detail:
        BlogPostEvent.objects.filter(pk=event.pk).update(detail=detail[:4000])


def _content(draft: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": clip(draft.get("title"), 200),
        "excerpt": clip(draft.get("excerpt"), 400),
        "body": draft.get("body", ""),
        "seo_title": clip(draft.get("seo_title"), 60),
        "meta_description": clip(draft.get("meta_description"), 160),
        "category": clip(draft.get("category"), 60),
        "faq": _faq(draft.get("faq") or []),
        "featured_image_alt": clip(draft.get("featured_image_alt") or draft.get("title"), 300),
        "focus_keyword": clip(draft.get("focus_keyword"), 80),
        "secondary_keywords": [clip(t, 80) for t in draft.get("secondary_keywords") or [] if str(t).strip()][:6],
    }


def _cover_asset(job: AgencyJob, state: dict[str, Any]):
    from apps.media_library.models import MediaAsset

    asset_id = state.get("cover_asset_id")
    if not asset_id:
        return None
    return MediaAsset.objects.filter(pk=str(asset_id), workspace_id=job.workspace_id).first()


def _readable(exc: ValidationError) -> str:
    if hasattr(exc, "error_dict"):
        return "; ".join(f"{field}: {' '.join(errors)}" for field, errors in exc.message_dict.items())
    return " ".join(exc.messages)


def _save_new(job: AgencyJob, state: dict[str, Any]):
    from apps.blog import services as blog_services
    from apps.blog.models import BlogPost, BlogPostEvent

    site = site_for(job)
    author = author_for(job)
    draft = state.get("draft") or {}
    post = None
    if state.get("blog_post_id"):  # made on an earlier try that stopped before the hand-off
        post = BlogPost.objects.filter(pk=str(state["blog_post_id"]), workspace_id=job.workspace_id).first()
    if post is None:
        changes, extra = _split_keywords(_content(draft))
        changes["slug"] = (
            draft.get("slug")
            if draft.get("slug") and not BlogPost.objects.filter(site=site, slug=draft["slug"]).exists()
            else unique_slug(site, draft.get("slug") or "", title=changes["title"])
        )
        changes["cover_style"] = BlogPost.CoverStyle.DESIGNED
        asset = _cover_asset(job, state)
        if asset is not None:
            changes["featured_image"] = asset
        detail = f"Written by the SEO team from the topic “{clip(_topic(job), 200)}”." + _check_before_approving(state)
        try:
            with transaction.atomic():
                post = blog_services.create_post(workspace=job.workspace, site=site, author=author, **changes)
                if extra:
                    BlogPost.objects.filter(pk=post.pk).update(**extra)
                _label_event(post, BlogPostEvent.Action.CREATED, detail)
                engine.save(job, blog_post=post, state={**(job.state or {}), "blog_post_id": str(post.pk)})
        except ValidationError as exc:
            raise engine.JobError(f"The article couldn't be saved: {_readable(exc)}") from exc
        except PermissionDenied as exc:
            raise engine.JobError(str(exc)) from exc
    return _submit(post, author)


def _submit(post, author):
    from apps.blog import services as blog_services
    from apps.blog.models import BlogPost

    post.refresh_from_db()
    if post.status in (BlogPost.Status.DRAFT, BlogPost.Status.CHANGES_REQUESTED):
        try:
            post = blog_services.submit_for_review(post, author)
        except (blog_services.BlogWorkflowError, PermissionDenied) as exc:
            raise engine.JobError(f"The draft was saved but couldn't be sent for approval: {exc}") from exc
    return post


def _save_revision(job: AgencyJob, state: dict[str, Any]):
    from apps.blog import services as blog_services
    from apps.blog.models import BlogPost, BlogPostEvent

    post = unchanged_since_start(job, state)
    author = author_for(job, post=post)
    wanted = _content(state.get("draft") or {})
    asset = _cover_asset(job, state)
    if asset is not None and not post.featured_image_id:
        wanted["featured_image"] = asset
    changes = {name: value for name, value in wanted.items() if getattr(post, name, None) != value}
    changes, extra = _split_keywords(changes)
    feedback = clip(state.get("feedback", ""), 300)
    detail = f"Revised by the SEO team: {feedback}" + _check_before_approving(state)
    try:
        with transaction.atomic():
            updated = blog_services.update_content(post, author, **changes) if changes else post
            if extra:
                BlogPost.objects.filter(pk=post.pk).update(**extra)
            if updated.revision != state.get("base_revision"):
                _label_event(updated, BlogPostEvent.Action.EDITED, detail)
    except ValidationError as exc:
        raise engine.JobError(f"The revision couldn't be saved: {_readable(exc)}") from exc
    except blog_services.BlogWorkflowError as exc:
        raise engine.JobError(str(exc)) from exc
    except PermissionDenied as exc:
        raise engine.JobError(str(exc)) from exc
    return _submit(updated, author)


def _notify(job: AgencyJob, post, *, revised: bool) -> None:
    """Tell the person who asked (staff only: clients hear back in their own thread)."""
    from django.conf import settings
    from django.urls import reverse

    from apps.notifications.engine import notify
    from apps.notifications.models import EventType

    user = job.requested_by
    if user is None or not may_write(user, job.workspace):
        return
    path = reverse("blog:detail", kwargs={"workspace_id": post.workspace_id, "post_id": post.pk})
    title = "The SEO team revised your article" if revised else "The SEO team wrote your article"
    try:
        notify(
            user=user,
            event_type=EventType.POST_SUBMITTED,
            title=title,
            body=f"“{clip(post.title, 120)}” is waiting for approval.",
            data={
                "blog_post_id": str(post.pk),
                "workspace_id": str(post.workspace_id),
                "agency_job_id": str(job.pk),
                "action_url": f"{settings.APP_URL.rstrip('/')}{path}",
            },
        )
    except Exception:
        logger.exception("Blog job %s: couldn't notify %s", job.pk, user.pk)


JOB = engine.JobType(
    kind="blog",
    stages=(
        engine.Stage("research", "seo_strategist", research),
        engine.Stage("outline", "outline_editor", outline),
        engine.Stage("write", "blog_writer", write),
        engine.Stage("fact_check", "fact_checker", fact_check),
        engine.Stage("seo", "seo_editor", seo),
        engine.Stage("edit", "editor_in_chief", edit),
        engine.Stage("cover", "illustrator", cover),
        engine.Stage("produce", "producer", produce),
    ),
    priority=engine.PRIORITY_DEFAULT,
    # A long article streams for a few minutes; leave room before the sweep calls it stuck.
    stuck_after=timedelta(minutes=45),
    labels={
        "research": "Research",
        "outline": "Outline",
        "write": "Writing",
        "fact_check": "Fact check",
        "seo": "SEO",
        "edit": "Final read",
        "cover": "Cover",
        "produce": "Hand-off",
    },
)
