"""The AI Studio pages: brief the team, watch it work, approve what it made.

Every URL is under ``/workspace/<workspace_id>/studio/``; the RBAC middleware
has already refused non-members by the time a view runs. Creating and revising
need ``create_posts``; approving needs ``approve_posts`` and, to publish at
once, ``publish_directly`` — the same permissions the composer and the
Approvals page ask for.
"""

from __future__ import annotations

import zoneinfo

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.members.decorators import require_permission

from . import design, images, llm, services, style
from . import team as roster
from .brand_defaults import ensure_profile
from .forms import BrandProfileForm, BriefForm, FeedbackForm, ScheduleForm, studio_accounts
from .models import AgentRun, StudioBrief, StudioConcept

#: The post team, in the order it works, for the progress view: (stage, agent slug).
#: Names and roles come from the roster (``apps.studio.team``).
POST_TEAM = (
    ("strategy", AgentRun.Agent.STRATEGIST),
    ("copy", AgentRun.Agent.COPYWRITER),
    ("art", AgentRun.Agent.ART_DIRECTOR),
    ("picture", AgentRun.Agent.PROMPT_ENGINEER),
    ("picture", AgentRun.Agent.ILLUSTRATOR),
    ("render", AgentRun.Agent.DESIGNER),
    ("review", AgentRun.Agent.REVIEWER),
    ("channel", AgentRun.Agent.CHANNEL_EDITOR),
    ("qa", AgentRun.Agent.QA_INSPECTOR),
    ("schedule", AgentRun.Agent.SCHEDULER),
    ("handoff", AgentRun.Agent.PRODUCER),
)
TEAM = tuple((stage, agent, roster.get(agent).name, roster.get(agent).does) for stage, agent in POST_TEAM)
_STAGE_ORDER = {stage: index for index, stage in enumerate(dict.fromkeys(stage for stage, _agent in POST_TEAM))}


def _workspace(request, workspace_id):
    workspace = request.workspace
    if workspace is None or workspace.id != workspace_id:
        raise PermissionDenied("You do not have access to this workspace.")
    return workspace


def _perms(request) -> dict:
    membership = request.workspace_membership
    return membership.effective_permissions if membership else {}


def _get_brief(request, workspace_id, brief_id):
    workspace = _workspace(request, workspace_id)
    brief = get_object_or_404(
        StudioBrief.objects.select_related("workspace", "author", "chosen_concept", "graphic", "picture", "post"),
        pk=brief_id,
        workspace=workspace,
    )
    return workspace, brief


def _detail_redirect(brief):
    return redirect("studio:detail", workspace_id=brief.workspace_id, brief_id=brief.pk)


def _setup(workspace) -> dict:
    accounts = studio_accounts(workspace)
    return {
        "claude_ready": llm.is_configured(),
        "pictures_ready": images.is_configured(),
        "has_accounts": bool(accounts),
        "has_linkedin": any(a.platform.startswith("linkedin") for a in accounts),
        "model": llm.model_id(),
    }


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


def _index_context(request, workspace, form):
    profile = ensure_profile(workspace)
    briefs = list(
        StudioBrief.objects.filter(workspace=workspace)
        .exclude(status=StudioBrief.Status.DISCARDED)
        .select_related("graphic", "author", "chosen_concept")[:30]
    )
    return {
        "workspace": workspace,
        "profile": profile,
        "form": form,
        "briefs": briefs,
        "setup": _setup(workspace),
        "reference": style.preview(workspace),
        "can_create": _perms(request).get("create_posts", False),
        "can_edit_brand": _can_edit_brand(request),
    }


@login_required
@require_GET
def index(request, workspace_id):
    workspace = _workspace(request, workspace_id)
    return render(request, "studio/index.html", _index_context(request, workspace, BriefForm(workspace=workspace)))


@login_required
@require_permission("create_posts")
@require_POST
def create(request, workspace_id):
    workspace = _workspace(request, workspace_id)
    form = BriefForm(request.POST, workspace=workspace)
    if not llm.is_configured():
        messages.error(request, "The AI Studio isn't set up yet: ANTHROPIC_API_KEY is missing on the server.")
        return redirect("studio:index", workspace_id=workspace.id)
    if not form.is_valid():
        return render(request, "studio/index.html", _index_context(request, workspace, form), status=400)
    brief = services.create_brief(
        workspace,
        request.user,
        idea=form.cleaned_data["idea"],
        notes=form.cleaned_data["notes"],
        goal=form.cleaned_data["goal"],
        accounts=form.cleaned_data["accounts"],
        style_lock=form.cleaned_data["style_lock"],
        source_picture=form.cleaned_data["source_picture"],
    )
    messages.success(request, "The team is on it. This usually takes two to four minutes.")
    return _detail_redirect(brief)


def _team_progress(brief):
    """One row per agent for the current revision: state, summary and timing."""
    runs = {}
    for run in brief.runs.filter(revision=brief.revision).order_by("started_at"):
        runs[run.agent] = run  # the latest run of each agent (a reviewer pass can repeat agents)
    current = _STAGE_ORDER.get(brief.stage, len(_STAGE_ORDER))
    rows = []
    for stage, agent, name, role in TEAM:
        index = _STAGE_ORDER[stage]
        run = runs.get(agent)
        if agent == AgentRun.Agent.PROMPT_ENGINEER and run is None:
            continue  # only works when pictures are painted; not shown otherwise
        if run is not None and run.status == AgentRun.Status.RUNNING:
            state = "working"
        elif run is not None and brief.status == StudioBrief.Status.FAILED and run.status == AgentRun.Status.FAILED:
            state = "failed"
        elif run is not None and index <= current:
            state = {"succeeded": "done", "skipped": "skipped", "failed": "warning"}.get(run.status, "done")
        elif brief.is_active and index == current:
            state = "working" if brief.status == StudioBrief.Status.WORKING else "queued"
        elif brief.status == StudioBrief.Status.FAILED and index == current:
            state = "failed"
        else:
            state = "pending"
        rows.append({"stage": stage, "name": name, "role": role, "run": run, "state": state})
    return rows


def _in_workspace_zone(moment, workspace):
    if moment is None:
        return None
    try:
        zone = zoneinfo.ZoneInfo(workspace.effective_timezone or "UTC")
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        zone = zoneinfo.ZoneInfo("UTC")
    return moment.astimezone(zone)


def _detail_context(request, workspace, brief, *, feedback_form=None, schedule_form=None):
    perms = _perms(request)
    concepts = list(brief.concepts.filter(revision__lte=brief.revision).order_by("-revision", "position"))
    current_concepts = [c for c in concepts if c.revision == max((c.revision for c in concepts), default=0)]
    post = brief.post
    platform_posts = list(post.platform_posts.select_related("social_account")) if post else []
    statuses = {pp.status for pp in platform_posts}
    if schedule_form is None:
        local = _in_workspace_zone(brief.proposed_publish_at, workspace)
        schedule_form = ScheduleForm(
            workspace=workspace,
            initial={"date": local.date(), "time": local.time().replace(second=0)} if local else {},
        )
    runs = list(brief.runs.all().order_by("started_at"))
    review = brief.review_notes or {}
    post_copy = brief.post_copy or {}
    caption = post_copy.get("caption", "")
    first_account = (
        platform_posts[0].social_account if platform_posts else next(iter(brief.social_accounts.all()), None)
    )
    return {
        "workspace": workspace,
        "brief": brief,
        "team": _team_progress(brief),
        "concepts": current_concepts,
        "post": post,
        "platform_posts": platform_posts,
        "post_statuses": statuses,
        "post_copy": post_copy,
        "caption_hook": caption[:210],
        "caption_rest": caption[210:],
        "hashtags": " ".join(post_copy.get("hashtags") or []),
        "spec": brief.design_spec or {},
        "review": review,
        "reference": brief.style_reference or {},
        "preview_account": first_account,
        "runs": runs,
        "cost": llm.estimate_cost(runs),
        "usage": brief.usage_totals,
        "feedback_form": feedback_form or FeedbackForm(),
        "schedule_form": schedule_form,
        "can_create": perms.get("create_posts", False),
        "can_approve": perms.get("approve_posts", False) and brief.status == StudioBrief.Status.READY,
        "can_publish_now": perms.get("publish_directly", False),
        "can_revise": perms.get("create_posts", False) and services.can_revise(brief),
        "can_discard": perms.get("create_posts", False)
        and brief.status not in (StudioBrief.Status.APPROVED, StudioBrief.Status.DISCARDED)
        and not (statuses & {"approved", "scheduled", "publishing", "published", "pending_client", "on_hold"}),
        "setup": _setup(workspace),
    }


@login_required
@require_GET
def detail(request, workspace_id, brief_id):
    workspace, brief = _get_brief(request, workspace_id, brief_id)
    services.sync_status(brief)
    return render(request, "studio/detail.html", _detail_context(request, workspace, brief))


@login_required
@require_GET
def progress(request, workspace_id, brief_id):
    """The team's progress, polled by the detail page while the team works."""
    workspace, brief = _get_brief(request, workspace_id, brief_id)
    if not brief.is_active:
        response = HttpResponse(status=200)
        response["HX-Refresh"] = "true"
        return response
    return render(
        request,
        "studio/partials/progress.html",
        {"workspace": workspace, "brief": brief, "team": _team_progress(brief)},
    )


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def _run(request, brief, action, *args, success=None, **kwargs):
    try:
        result = action(*args, **kwargs)
    except services.StudioActionError as exc:
        messages.error(request, str(exc))
    else:
        message = success or (result if isinstance(result, str) else None)
        if message:
            messages.success(request, message)
    return _detail_redirect(brief)


@login_required
@require_permission("approve_posts")
@require_POST
def approve(request, workspace_id, brief_id):
    workspace, brief = _get_brief(request, workspace_id, brief_id)
    mode = request.POST.get("mode", "approve")
    if mode == "now":
        if not _perms(request).get("publish_directly", False):
            raise PermissionDenied("You do not have permission to publish directly.")
        return _run(request, brief, services.approve, brief, request.user, publish_now=True)
    if mode == "schedule":
        form = ScheduleForm(request.POST, workspace=workspace)
        if not form.is_valid():
            messages.error(request, "Pick a date and a time to schedule it.")
            return _detail_redirect(brief)
        return _run(request, brief, services.approve, brief, request.user, publish_at=form.aware_datetime())
    return _run(request, brief, services.approve, brief, request.user)


@login_required
@require_permission("create_posts")
@require_POST
def request_changes(request, workspace_id, brief_id):
    workspace, brief = _get_brief(request, workspace_id, brief_id)
    form = FeedbackForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Say what should change, so the team knows what to do.")
        return _detail_redirect(brief)
    return _run(
        request,
        brief,
        services.request_changes,
        brief,
        form.cleaned_data["feedback"],
        new_picture=form.cleaned_data["new_picture"],
        success="Sent back to the team with your notes.",
    )


@login_required
@require_permission("create_posts")
@require_POST
def new_angles(request, workspace_id, brief_id):
    workspace, brief = _get_brief(request, workspace_id, brief_id)
    return _run(
        request,
        brief,
        services.new_angles,
        brief,
        request.POST.get("feedback", ""),
        success="The strategist is looking for new angles.",
    )


@login_required
@require_permission("create_posts")
@require_POST
def use_angle(request, workspace_id, brief_id, concept_id):
    workspace, brief = _get_brief(request, workspace_id, brief_id)
    concept = get_object_or_404(StudioConcept, pk=concept_id, brief=brief)
    return _run(request, brief, services.use_concept, brief, concept, success=f"Writing “{concept.title}” instead.")


@login_required
@require_permission("create_posts")
@require_POST
def save_idea(request, workspace_id, brief_id, concept_id):
    workspace, brief = _get_brief(request, workspace_id, brief_id)
    concept = get_object_or_404(StudioConcept, pk=concept_id, brief=brief)
    services.save_concept_as_idea(concept, request.user)
    messages.success(request, f"Saved “{concept.title}” to the idea board.")
    return _detail_redirect(brief)


@login_required
@require_permission("create_posts")
@require_POST
def retry(request, workspace_id, brief_id):
    workspace, brief = _get_brief(request, workspace_id, brief_id)
    if not llm.is_configured():
        messages.error(request, "ANTHROPIC_API_KEY is missing on the server, so the team can't run.")
        return _detail_redirect(brief)
    return _run(request, brief, services.retry, brief, success="Picking up where the team stopped.")


@login_required
@require_permission("create_posts")
@require_POST
def discard(request, workspace_id, brief_id):
    workspace, brief = _get_brief(request, workspace_id, brief_id)
    try:
        services.discard(brief)
    except services.StudioActionError as exc:
        messages.error(request, str(exc))
        return _detail_redirect(brief)
    messages.success(request, "Discarded.")
    return redirect("studio:index", workspace_id=workspace.id)


# ---------------------------------------------------------------------------
# Brand profile
# ---------------------------------------------------------------------------


def _can_edit_brand(request) -> bool:
    perms = _perms(request)
    return bool(perms.get("approve_posts") or perms.get("manage_workspace_settings"))


@login_required
@require_http_methods(["GET", "POST"])
def brand_profile(request, workspace_id):
    workspace = _workspace(request, workspace_id)
    profile = ensure_profile(workspace)
    can_edit = _can_edit_brand(request)
    if request.method == "POST":
        if not can_edit:
            raise PermissionDenied("Only an owner or manager can change the brand profile.")
        form = BrandProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Brand profile saved. The team uses it from the next brief.")
            return redirect("studio:brand", workspace_id=workspace.id)
    else:
        form = BrandProfileForm(instance=profile)
    return render(
        request,
        "studio/brand_profile.html",
        {"workspace": workspace, "profile": profile, "form": form, "can_edit": can_edit, "templates": design.TEMPLATES},
    )


@login_required
@require_GET
def brand_sample(request, workspace_id, template):
    """A sample graphic in the brand's current look, without any AI — for the brand profile page."""
    workspace = _workspace(request, workspace_id)
    if template not in design.TEMPLATES:
        raise PermissionDenied("Unknown layout.")
    profile = ensure_profile(workspace)
    look = design.Look.from_profile(profile, style.read_asset(profile.logo) if profile.logo_id else None)
    spec = {
        "template": template,
        "format": profile.default_format,
        "grade": profile.default_grade,
        "kicker": "Your topic",
        "headline": "A short, concrete headline lives here",
        "subheadline": "The supporting line explains it in a sentence.",
        "stat_value": "42%",
        "stat_label": "what the number means",
        "cta_label": profile.default_cta[:40],
    }
    response = HttpResponse(design.render(spec, look, None), content_type="image/jpeg")
    response["Cache-Control"] = "private, no-store"
    return response
