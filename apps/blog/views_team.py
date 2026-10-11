"""Writing with the agency's SEO team, from the blog pages.

* **Write with the team** (``blog:write``): a topic, the website, an optional
  focus keyword and notes; the SEO team researches, outlines, writes, checks
  and hands back a draft that waits for approval.
* **The team's progress** (``blog:team_job``): who is doing what, live while
  the job runs, then a link to the draft.
* **Ask the SEO team** on an article (``blog:team_panel``, loaded into the
  article page): ask for a change, "Improve SEO", or — once the article is
  approved or published — "Make social posts".

These pages are for the agency's staff: they need ``create_posts`` to start
work and are closed to plain clients (who would otherwise pass permission
checks with their sign-off rights). Every POST that starts paid work is rate
limited and checks the workspace's monthly AI budget. The work itself runs in
the worker (``apps.studio.jobtypes.blog`` / ``repurpose``), never here, and
it only ever makes drafts and submits them for approval.
"""

from __future__ import annotations

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django_ratelimit.decorators import ratelimit

from apps.members.decorators import require_permission
from apps.studio import budget, engine, images, llm, team
from apps.studio.jobtypes import blog as blog_job
from apps.studio.jobtypes import repurpose as repurpose_job
from apps.studio.models import AgencyJob, AgentRun, StudioBrief
from apps.studio.views import is_plain_client

from . import services
from .models import BlogPost, BlogSite

Status = BlogPost.Status

#: Articles the SEO team writes at once in one workspace (a database cap next to the per-user rate limit).
MAX_ACTIVE_ARTICLES = 3
#: Articles the team may revise: not yet approved, and not being published.
REVISABLE = (Status.DRAFT, Status.CHANGES_REQUESTED, Status.PENDING_REVIEW)
#: Articles the team may turn into social posts.
REPURPOSABLE = (Status.APPROVED, Status.PUBLISHED)
TEAM_KINDS = (AgencyJob.Kind.BLOG, AgencyJob.Kind.REPURPOSE)
#: Who works on an article, in order, for the write page.
ARTICLE_TEAM = (
    "seo_strategist",
    "outline_editor",
    "blog_writer",
    "fact_checker",
    "seo_editor",
    "editor_in_chief",
    "prompt_engineer",
    "illustrator",
    "producer",
)
_RUN_STATE: dict[str, str] = {
    AgentRun.Status.RUNNING: "working",
    AgentRun.Status.SUCCEEDED: "done",
    AgentRun.Status.FAILED: "failed",
    AgentRun.Status.SKIPPED: "skipped",
}


class WriteForm(forms.Form):
    topic = forms.CharField(label="What should the article be about?", max_length=300)
    site = forms.ModelChoiceField(label="Website", queryset=BlogSite.objects.none(), empty_label=None)
    focus_keyword = forms.CharField(label="Focus keyword", max_length=80, required=False)
    notes = forms.CharField(label="Notes for the team", max_length=2000, required=False, widget=forms.Textarea)

    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["site"].queryset = BlogSite.objects.filter(workspace=workspace, is_enabled=True).order_by("name")


def _workspace(request, workspace_id):
    """The URL's workspace, for its staff. Clients sign off in the client portal instead."""
    workspace = request.workspace
    if workspace is None or workspace.id != workspace_id:
        raise PermissionDenied("You do not have access to this workspace.")
    if is_plain_client(request.workspace_membership):
        raise PermissionDenied("This part of SM Bean is for your agency team. Your approvals are in the client portal.")
    return workspace


def _perms(request) -> dict:
    membership = request.workspace_membership
    return membership.effective_permissions if membership else {}


def _not_ready(workspace) -> str:
    """Why paid work can't start right now, or an empty string."""
    if not llm.is_configured():
        return "The SEO team isn't set up yet: the server has no Claude API key. Ask your admin to add one."
    if not budget.can_spend(workspace):
        return budget.over_budget_message(workspace)
    return ""


def _team_busy(workspace) -> str:
    """Why the SEO team can't take on another article here right now, or an empty string."""
    active = AgencyJob.objects.filter(
        workspace=workspace, kind=AgencyJob.Kind.BLOG, status__in=AgencyJob.ACTIVE_STATUSES
    ).count()
    if active >= MAX_ACTIVE_ARTICLES:
        return (
            f"The SEO team is already working on {MAX_ACTIVE_ARTICLES} articles here. "
            "Ask again when one of them is ready."
        )
    return ""


def _recent_jobs(workspace, limit=6):
    return list(
        AgencyJob.objects.filter(workspace=workspace, kind__in=TEAM_KINDS)
        .select_related("requested_by")
        .order_by("-created_at")[:limit]
    )


# ---------------------------------------------------------------------------
# Write with the team
# ---------------------------------------------------------------------------


@login_required
@require_permission("create_posts")
@ratelimit(key="user", rate="10/m", method="POST", block=True)
@require_http_methods(["GET", "POST"])
def write(request, workspace_id):
    workspace = _workspace(request, workspace_id)
    if not BlogSite.objects.filter(workspace=workspace, is_enabled=True).exists():
        return render(request, "blog/no_sites.html", {"workspace": workspace})
    form = WriteForm(request.POST or None, workspace=workspace)
    error = ""
    status = 200
    if request.method == "POST":
        if not form.is_valid():
            status = 400
        elif (error := _not_ready(workspace)) or (error := _team_busy(workspace)):
            status = 409
        else:
            data = form.cleaned_data
            job = blog_job.start_article(
                workspace,
                topic=data["topic"],
                site=data["site"],
                requested_by=request.user,
                focus_keyword=data["focus_keyword"],
                notes=data["notes"],
            )
            messages.success(request, "The SEO team is on it. An article usually takes five to ten minutes.")
            return redirect("blog:team_job", workspace_id=workspace.id, job_id=job.pk)
    return render(
        request,
        "blog/write.html",
        {
            "workspace": workspace,
            "form": form,
            "error": error,
            "claude_ready": llm.is_configured(),
            "pictures_ready": images.is_configured(),
            "article_team": [team.get(slug) for slug in ARTICLE_TEAM],
            "recent_jobs": _recent_jobs(workspace),
        },
        status=status,
    )


# ---------------------------------------------------------------------------
# The team's progress on one job
# ---------------------------------------------------------------------------


def _get_job(request, workspace_id, job_id):
    workspace = _workspace(request, workspace_id)
    job = get_object_or_404(
        AgencyJob.objects.select_related("requested_by"), pk=job_id, workspace=workspace, kind__in=TEAM_KINDS
    )
    return workspace, job


def _timeline(job: AgencyJob) -> list[dict]:
    """Every agent turn so far (all tries, oldest first), then the steps still to come."""
    rows = [
        {"agent": team.get(run.agent), "run": run, "state": _RUN_STATE.get(run.status, "idle")}
        for run in job.runs.order_by("started_at")
    ]
    if not job.is_active:
        return rows
    try:
        stages = engine.job_type(job.kind).stages
    except KeyError:
        return rows
    names = [stage.name for stage in stages]
    current = names.index(job.stage) if job.stage in names else len(names)
    running = any(row["state"] == "working" for row in rows)
    for index, stage in enumerate(stages[current:], start=current):
        if index == current and running:
            continue
        state = "pending"
        if index == current:
            state = "working" if job.status == AgencyJob.Status.WORKING else "queued"
        rows.append({"agent": team.get(stage.agent), "run": None, "state": state})
    return rows


def _job_context(request, workspace, job) -> dict:
    post = None
    post_id = (job.result or {}).get("blog_post_id") or job.blog_post_id
    if post_id:
        post = BlogPost.objects.filter(pk=post_id, workspace=workspace).select_related("site").first()
    report = None
    if post is not None and job.kind == AgencyJob.Kind.BLOG and job.status == AgencyJob.Status.DONE:
        from .seo import score_post

        report = score_post(post)
    briefs = []
    if job.kind == AgencyJob.Kind.REPURPOSE:
        briefs = list(StudioBrief.objects.filter(workspace=workspace, job=job).order_by("created_at"))
    return {
        "workspace": workspace,
        "job": job,
        "timeline": _timeline(job),
        "post": post,
        "report": report,
        "briefs": briefs,
        "can_act": bool(_perms(request).get("create_posts")),
    }


@login_required
@require_GET
def team_job(request, workspace_id, job_id):
    workspace, job = _get_job(request, workspace_id, job_id)
    context = _job_context(request, workspace, job)
    if request.htmx:
        return render(request, "blog/partials/team_progress.html", context)
    return render(request, "blog/team_job.html", context)


@login_required
@require_permission("create_posts")
@ratelimit(key="user", rate="10/m", method="POST", block=True)
@require_POST
def team_retry(request, workspace_id, job_id):
    workspace, job = _get_job(request, workspace_id, job_id)
    if job.status != AgencyJob.Status.FAILED:
        messages.error(request, "Only work that stopped with a problem can be retried.")
    elif error := _not_ready(workspace):
        messages.error(request, error)
    else:
        engine.restart(job)
        messages.success(request, "The team is trying again from where it stopped.")
    return redirect("blog:team_job", workspace_id=workspace.id, job_id=job.pk)


# ---------------------------------------------------------------------------
# Ask the SEO team, on one article
# ---------------------------------------------------------------------------


def _get_post(request, workspace_id, post_id):
    workspace = _workspace(request, workspace_id)
    post = get_object_or_404(BlogPost.objects.select_related("site", "workspace"), pk=post_id, workspace=workspace)
    return workspace, post


def _may_revise(request, post) -> bool:
    return (
        bool(_perms(request).get("create_posts")) and services.can_edit(request.user, post) and post.status in REVISABLE
    )


def _may_repurpose(request, post) -> bool:
    return bool(_perms(request).get("create_posts")) and post.status in REPURPOSABLE


@login_required
@require_GET
def team_panel(request, workspace_id, post_id):
    """The "Ask the SEO team" banner for the article page (loaded with HTMX; empty for people who can't use it)."""
    workspace = request.workspace
    if workspace is None or workspace.id != workspace_id or is_plain_client(request.workspace_membership):
        return HttpResponse("")
    post = get_object_or_404(BlogPost.objects.select_related("site"), pk=post_id, workspace=workspace)
    active = blog_job.active_job(post)
    latest = (
        AgencyJob.objects.filter(workspace=workspace, blog_post=post, kind__in=TEAM_KINDS)
        .exclude(status__in=AgencyJob.ACTIVE_STATUSES)
        .order_by("-created_at")
        .first()
    )
    can_revise, can_repurpose = _may_revise(request, post), _may_repurpose(request, post)
    if not (can_revise or can_repurpose or active or latest):
        return HttpResponse("")
    return render(
        request,
        "blog/partials/team_panel.html",
        {
            "workspace": workspace,
            "post": post,
            "active_job": active,
            "latest_job": latest,
            "can_revise": can_revise,
            "can_repurpose": can_repurpose,
            "has_accounts": bool(repurpose_job.social_accounts(workspace)) if can_repurpose else False,
        },
    )


def _back(post):
    return redirect("blog:detail", workspace_id=post.workspace_id, post_id=post.pk)


@login_required
@require_permission("create_posts")
@ratelimit(key="user", rate="10/m", method="POST", block=True)
@require_POST
def team_revise(request, workspace_id, post_id):
    """Ask the SEO team for a change ("feedback"), or to fix what the SEO score flags (``mode=seo``)."""
    workspace, post = _get_post(request, workspace_id, post_id)
    if not services.can_edit(request.user, post):
        raise PermissionDenied("You don't have permission to edit this blog post.")
    improve = request.POST.get("mode") == "seo"
    feedback = blog_job.IMPROVE_SEO_FEEDBACK if improve else (request.POST.get("feedback") or "").strip()[:4000]
    if post.status not in REVISABLE:
        messages.error(
            request, "The team changes articles before they're approved. Edit an approved or live article yourself."
        )
    elif not feedback:
        messages.error(request, "Say what should change, so the team knows what to do.")
    elif error := _not_ready(workspace):
        messages.error(request, error)
    elif blog_job.active_job(post) is not None:
        messages.info(request, "The team is already working on this article. Wait for it to finish, then ask again.")
    elif error := _team_busy(workspace):
        messages.error(request, error)
    else:
        job = blog_job.start_revision(post, feedback=feedback, requested_by=request.user)
        messages.success(
            request,
            "The SEO team is fixing what the score flags." if improve else "The SEO team is working on your change.",
        )
        return redirect("blog:team_job", workspace_id=workspace.id, job_id=job.pk)
    return _back(post)


@login_required
@require_permission("create_posts")
@ratelimit(key="user", rate="10/m", method="POST", block=True)
@require_POST
def team_repurpose(request, workspace_id, post_id):
    """Turn an approved or published article into 2–3 social posts (each goes to approval)."""
    workspace, post = _get_post(request, workspace_id, post_id)
    if post.status not in REPURPOSABLE:
        messages.error(request, "Social posts are made from an article once it is approved or published.")
    elif not repurpose_job.social_accounts(workspace):
        messages.error(request, "Connect a social account first, so the team knows where the posts go.")
    elif error := _not_ready(workspace):
        messages.error(request, error)
    elif blog_job.active_job(post, kinds=(AgencyJob.Kind.REPURPOSE,)) is not None:
        messages.info(request, "The team is already making posts from this article.")
    else:
        job = repurpose_job.start(post, requested_by=request.user)
        messages.success(
            request, "The team is turning this article into social posts. Each one comes to you to approve."
        )
        return redirect("blog:team_job", workspace_id=workspace.id, job_id=job.pk)
    return _back(post)
