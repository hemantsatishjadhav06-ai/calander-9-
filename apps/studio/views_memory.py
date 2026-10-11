"""Creative memory: what the team learns from, and the controls a person has over it.

``/workspace/<id>/studio/memory/``. The page shows the house style the
curator wrote (people who may edit the brand profile can rewrite it), the
best designer's references with a "Learn from this" switch, an upload for
more references, and the best-performing posts with "Use as reference". Every
action is a POST for the agency's staff (``create_posts``, never a client —
see ``views._workspace``), rate-limited, and scoped to this workspace's rows.
"Refresh what we learned" only queues a learn job: the curator's model work
happens in the worker, within the workspace's monthly budget.
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from django_ratelimit.decorators import ratelimit

from apps.members.decorators import require_permission

from . import budget, dashboard, engine, llm
from .brand_defaults import ensure_profile
from .forms_agency import HouseStyleForm, ReferenceUploadForm
from .jobtypes.learn import PERSON_EDIT_HOLD, last_curator_text
from .models import AgencyJob, BrandProfile, CreativeInsight
from .views import _can_edit_brand, _perms, _workspace

#: Cards shown per grid.
GRID_SIZE = 12


def _image_url(asset) -> str:
    if asset is None:
        return ""
    try:
        return asset.thumbnail.url if asset.thumbnail else asset.file.url
    except ValueError:
        return ""


def _network(platform: str) -> str:
    from .reports import network_name

    return network_name(platform)


def _card(insight: CreativeInsight) -> dict:
    hook = (insight.features or {}).get("hook") or ((insight.caption or "").strip().splitlines() or [""])[0]
    top = None
    if insight.score is not None:
        top = max(1, round((1 - insight.score) * 100))
    return {
        "insight": insight,
        "image": _image_url(insight.media_asset),
        "network": _network(insight.platform) if insight.platform else "",
        "top": top,
        "ratio": insight.ratio,
        "hook": hook[:120],
        "look": (insight.description or "").strip(),
    }


def house_style_origin(profile) -> dict:
    """Who wrote the house style and, for a person's text, until when the curator leaves it alone."""
    text = (profile.house_style or "").strip()
    if not text:
        return {"by": "", "until": None}
    if text == (last_curator_text(profile.workspace) or "").strip():
        return {"by": "curator", "until": None}
    edited = profile.house_style_updated_at
    until = edited + PERSON_EDIT_HOLD if edited else None
    return {"by": "person", "until": until if until and until > timezone.now() else None}


def _context(request, workspace, *, house_form=None, upload_form=None) -> dict:
    profile = ensure_profile(workspace)
    perms = _perms(request)
    references = [
        _card(i)
        for i in CreativeInsight.objects.filter(workspace=workspace, media_asset__isnull=False)
        .filter(Q(is_reference=True) | Q(source=CreativeInsight.Source.UPLOAD))
        .select_related("media_asset")
        .order_by("-is_reference", "-created_at")[:GRID_SIZE]
    ]
    best = [
        _card(i)
        for i in CreativeInsight.objects.filter(workspace=workspace, score__isnull=False, media_asset__isnull=False)
        .select_related("media_asset")
        .order_by("-score", "-published_at")[:8]
    ]
    jobs = AgencyJob.objects.filter(workspace=workspace, kind=AgencyJob.Kind.LEARN).order_by("-created_at")
    last_job = jobs.first()
    last_done = jobs.filter(status=AgencyJob.Status.DONE).first()
    return {
        "workspace": workspace,
        "profile": profile,
        "tzname": workspace.effective_timezone or "UTC",
        "tabs": dashboard.tabs(workspace, "memory"),
        "references": references,
        "reference_count": CreativeInsight.objects.filter(workspace=workspace, is_reference=True).count(),
        "best": best,
        "scored_count": CreativeInsight.objects.filter(workspace=workspace, score__isnull=False).count(),
        "origin": house_style_origin(profile),
        "last_job": last_job,
        "last_done": last_done,
        "learning": bool(last_job and last_job.is_active),
        "can_create": perms.get("create_posts", False),
        "can_upload": perms.get("create_posts", False) and perms.get("upload_media", False),
        "can_edit_style": _can_edit_brand(request),
        "house_form": house_form or HouseStyleForm(initial={"house_style": profile.house_style}),
        "upload_form": upload_form or ReferenceUploadForm(),
        "open_upload": bool(upload_form and upload_form.errors),
        "open_style": bool(house_form and house_form.errors),
    }


def _back(workspace):
    return redirect("studio:memory", workspace_id=workspace.id)


@login_required
@require_permission("create_posts")
@require_GET
def memory(request, workspace_id):
    workspace = _workspace(request, workspace_id)
    return render(request, "studio/memory.html", _context(request, workspace))


@login_required
@require_permission("create_posts")
@ratelimit(key="user", rate="10/m", method="POST", block=True)
@require_POST
def house_style(request, workspace_id):
    """A person rewrites the house style. The curator then leaves it alone for 30 days (see jobtypes.learn)."""
    workspace = _workspace(request, workspace_id)
    if not _can_edit_brand(request):
        raise PermissionDenied("Only an owner or manager can change the house style.")
    form = HouseStyleForm(request.POST)
    if not form.is_valid():
        return render(request, "studio/memory.html", _context(request, workspace, house_form=form), status=400)
    profile = ensure_profile(workspace)
    text = " ".join(form.cleaned_data["house_style"].split())
    if text == " ".join((profile.house_style or "").split()):
        messages.info(request, "Nothing changed.")
        return _back(workspace)
    BrandProfile.objects.filter(pk=profile.pk, workspace=workspace).update(
        house_style=text, house_style_updated_at=timezone.now(), updated_at=timezone.now()
    )
    if text:
        messages.success(
            request,
            "Saved. The art director and prompt engineer use it from the next post; the curator won't "
            "rewrite it for 30 days.",
        )
    else:
        messages.success(request, "Cleared. The curator writes a new house style on the next refresh.")
    return _back(workspace)


@login_required
@require_permission("create_posts")
@ratelimit(key="user", rate="10/m", method="POST", block=True)
@require_POST
def toggle_reference(request, workspace_id, insight_id):
    """Turn "Learn from this" on or off for one of this workspace's creatives."""
    workspace = _workspace(request, workspace_id)
    insight = get_object_or_404(CreativeInsight, pk=insight_id, workspace=workspace)
    learn = request.POST.get("learn") == "1"
    CreativeInsight.objects.filter(pk=insight.pk, workspace=workspace).update(is_reference=learn)
    if learn:
        messages.success(request, "The team will learn from this one. Refresh what we learned to update the style.")
    else:
        messages.success(request, "The team won't learn from this one any more.")
    return _back(workspace)


@login_required
@require_permission("create_posts")
@ratelimit(key="user", rate="10/m", method="POST", block=True)
@require_POST
def upload_references(request, workspace_id):
    """Pictures by the best designer, stored in the media library and marked "Learn from this"."""
    from apps.media_library.quotas import StorageQuotaExceededError
    from apps.media_library.services import create_asset, upload_rejection_message
    from apps.media_library.tasks import process_media_asset

    workspace = _workspace(request, workspace_id)
    if not _perms(request).get("upload_media", False):
        raise PermissionDenied("You don't have permission to upload media.")
    form = ReferenceUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        return render(request, "studio/memory.html", _context(request, workspace, upload_form=form), status=400)
    note = " ".join(form.cleaned_data["note"].split())
    added, problems = 0, []
    for uploaded in form.cleaned_data["images"]:
        try:
            asset = create_asset(
                workspace.organization,
                workspace,
                uploaded,
                request.user,
                title=f"Reference: {uploaded.name}"[:255],
                tags=["studio-reference"],
                source="studio-reference",
            )
        except (StorageQuotaExceededError, ValidationError) as exc:
            problems.append(f"{uploaded.name}: {upload_rejection_message(exc)}")
            continue
        if asset.media_type != asset.MediaType.IMAGE:
            asset.file.delete(save=False)
            asset.delete()
            problems.append(f"{uploaded.name}: only still pictures (JPEG, PNG or WebP) can be references.")
            continue
        process_media_asset(str(asset.id))
        CreativeInsight.objects.create(
            workspace=workspace,
            media_asset=asset,
            source=CreativeInsight.Source.UPLOAD,
            is_reference=True,
            reference_note=note[:300],
        )
        added += 1
    if added:
        messages.success(
            request,
            f"Added {added} reference{'s' if added != 1 else ''}. Press “Refresh what we learned” to have the "
            "curator study them.",
        )
    for problem in problems:
        messages.error(request, problem)
    return _back(workspace)


@login_required
@require_permission("create_posts")
@ratelimit(key="user", rate="10/m", method="POST", block=True)
@require_POST
def refresh(request, workspace_id):
    """Queue a learn job (the ranking is code; the curator's look runs in the worker, within budget)."""
    workspace = _workspace(request, workspace_id)
    active = AgencyJob.objects.filter(
        workspace=workspace, kind=AgencyJob.Kind.LEARN, status__in=AgencyJob.ACTIVE_STATUSES
    ).first()
    if active is not None:
        messages.info(request, "The curator is already studying your work.")
        return redirect("studio:job", workspace_id=workspace.id, job_id=active.pk)
    if not llm.is_configured():
        messages.error(request, "ANTHROPIC_API_KEY is missing on the server, so the curator can't look at pictures.")
        return _back(workspace)
    if not budget.can_spend(workspace):
        messages.error(request, budget.over_budget_message(workspace))
        return _back(workspace)
    recent = AgencyJob.objects.filter(
        workspace=workspace, kind=AgencyJob.Kind.LEARN, created_at__gte=timezone.now() - timedelta(minutes=2)
    ).exists()
    if recent:
        messages.info(request, "The curator has only just finished. Give it a couple of minutes.")
        return _back(workspace)
    job = engine.create(workspace, AgencyJob.Kind.LEARN, title="Refresh what we learned", requested_by=request.user)
    messages.success(request, "The performance analyst and the curator are on it. This takes a minute or two.")
    return redirect("studio:job", workspace_id=workspace.id, job_id=job.pk)
