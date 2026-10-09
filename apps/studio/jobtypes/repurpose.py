"""The ``repurpose`` job: an approved or published article becomes two or three social posts.

1. **ideas** — the repurposer reads the article and suggests 2–3 posts, each
   with a different angle and its own hook;
2. **briefs** — the producer hands each idea to the post team as a
   :class:`~apps.studio.models.StudioBrief` (``origin="repurpose"``) with the
   article's link in the notes. Each brief then goes through the normal post
   pipeline and lands in Approvals; nothing is scheduled or published here.

The briefs go to the workspace's agency accounts (Agency → Autopilot) or,
when none are chosen, to every connected account the post team writes for.
A retry never makes the same brief twice: the briefs already made are kept
in the job's state.
"""

from __future__ import annotations

import logging

from django.db import transaction

from .. import budget, engine
from ..models import AgencyJob, AgencySettings, AgentRun, StudioBrief
from ..roles import seo as seo_roles
from . import blog

logger = logging.getLogger(__name__)

#: The most posts one article is turned into.
MAX_IDEAS = 3


def start(post, *, requested_by, parent: AgencyJob | None = None, conversation=None) -> AgencyJob:
    """Queue the repurposer on ``post``. Callers check permissions, the post's status and the budget."""
    return engine.create(
        post.workspace,
        AgencyJob.Kind.REPURPOSE,
        title=f"Posts from: {post.title}",
        input={"blog_post_id": str(post.pk)},
        requested_by=requested_by,
        blog_post=post,
        parent=parent,
        conversation=conversation,
    )


def social_accounts(workspace) -> list:
    """Where the posts go: the agency's chosen accounts, else the connected accounts the post team writes for."""
    from ..forms import STUDIO_PLATFORMS, studio_accounts

    agency = AgencySettings.objects.filter(workspace=workspace).first()
    chosen = []
    if agency is not None:
        chosen = [
            account
            for account in agency.accounts.filter(workspace=workspace, platform__in=STUDIO_PLATFORMS)
            if account.workspace_id == workspace.id
        ]
    pool = chosen or studio_accounts(workspace)
    return [account for account in pool if not account.needs_reconnect]


def _repurposable(post) -> None:
    from apps.blog.models import BlogPost

    if post.status not in (BlogPost.Status.APPROVED, BlogPost.Status.PUBLISHED):
        raise engine.JobError("Posts are made from an article once it is approved or published.")


def ideas(job: AgencyJob) -> str:
    post = blog.post_for(job)
    _repurposable(post)
    blog.need_budget(job)
    blog.author_for(job)  # fail before paying for anything if nobody may own the posts
    profile = blog.profile_for(job)
    url = post.published_url or post.expected_url
    recent = [
        blog.clip(idea, 160)
        for idea in StudioBrief.objects.filter(workspace_id=job.workspace_id)
        .order_by("-created_at")
        .values_list("idea", flat=True)[:8]
    ]
    run, result = engine.call(
        job,
        "repurposer",
        lambda: seo_roles.repurposer(profile, article=blog.article_of(post), url=url, recent=recent),
        stage="ideas",
        effort=seo_roles.REPURPOSER_EFFORT,
    )
    picked = [
        {"angle": blog.clip(i.angle, 80), "hook": blog.clip(i.hook, 200), "idea": i.idea.strip()[:1500]}
        for i in result.output.ideas
        if i.idea.strip()
    ][:MAX_IDEAS]
    if not picked:
        engine.end(run, summary="No post ideas came back.", result=result, status=AgentRun.Status.FAILED)
        raise engine.JobError("The repurposer didn't suggest any posts. Press Retry.")
    engine.end(
        run,
        summary=f"{len(picked)} post ideas: " + "; ".join(i["angle"] for i in picked),
        output={"ideas": picked, "summary": result.output.summary},
        result=result,
    )
    engine.update_state(job, ideas=picked, url=url)
    return "briefs"


def briefs(job: AgencyJob) -> None:
    from apps.blog import services as blog_services
    from apps.blog.models import BlogPostEvent

    from .. import services as studio_services

    state = job.state or {}
    post = blog.post_for(job)
    _repurposable(post)
    run = engine.begin(job, "producer", stage="briefs")
    try:
        author = blog.author_for(job)
        accounts = social_accounts(job.workspace)
        if not accounts:
            raise engine.JobError(
                "There's no connected social account to make posts for. Connect one under Settings → Social "
                "accounts, then press Retry."
            )
    except engine.JobError as exc:
        engine.end(run, summary=str(exc)[:500], status=AgentRun.Status.FAILED)
        raise
    url = state.get("url") or post.published_url or post.expected_url
    made = [str(pk) for pk in state.get("brief_ids") or []]
    requested_by = job.requested_by if job.requested_by_id and job.requested_by_id != author.pk else None
    for index, idea in enumerate((state.get("ideas") or [])[:MAX_IDEAS]):
        if index < len(made):
            continue  # made on an earlier try
        if not budget.can_spend(job.workspace):
            message = budget.over_budget_message(job.workspace)
            engine.end(run, summary=message[:500], status=AgentRun.Status.FAILED)
            raise engine.JobError(message)
        notes = f"Link: {url}\nHook: {idea.get('hook', '')}\nFrom the blog article “{blog.clip(post.title, 150)}”."
        with transaction.atomic():
            brief = studio_services.create_brief(
                job.workspace,
                author,
                idea=idea.get("idea", "")[:2000],
                notes=notes,
                accounts=accounts,
                origin=StudioBrief.Origin.REPURPOSE,
                job=job,
                requested_by=requested_by,
                start=True,
            )
            made.append(str(brief.pk))
            engine.update_state(job, brief_ids=made)
    names = ", ".join(sorted({a.account_name or a.get_platform_display() for a in accounts}))
    summary = f"Started {len(made)} post(s) for {names}. Each one goes to approval when it's ready."
    try:
        blog_services.record_event(
            post,
            BlogPostEvent.Action.SOCIAL_DRAFTS_CREATED,
            detail=f"The repurposer started {len(made)} social post(s) from this article for {names}.",
            fingerprint_value=blog_services.fingerprint(post),
        )
    except Exception:
        logger.exception("Repurpose job %s: couldn't add the history entry", job.pk)
    engine.end(run, summary=summary, output={"brief_ids": made})
    engine.finish(job, result={"brief_ids": made, "summary": summary, "blog_post_id": str(post.pk)})
    return None


JOB = engine.JobType(
    kind="repurpose",
    stages=(
        engine.Stage("ideas", "repurposer", ideas),
        engine.Stage("briefs", "producer", briefs),
    ),
    priority=engine.PRIORITY_DEFAULT,
    labels={"ideas": "Post ideas", "briefs": "Hand-off to the post team"},
)
