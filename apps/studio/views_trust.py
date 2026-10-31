import uuid
from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import BadRequest, PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.common.features import request_features
from apps.media_library.models import MediaAsset

from . import dashboard, guards, settings_links, trust
from .forms_trust import BrandClaimForm
from .models import BrandClaim
from .views import _can_edit_brand, _perms, _workspace


def may_read_facts(request, workspace) -> bool:
    """This page's own check: someone on the agency's team, never a client (a client-facing custom role
    included). Settings → Advanced applies it to its Verified facts section."""
    from . import chat

    viewer = chat.membership_for(request.user, workspace)
    client_role = bool(viewer and viewer.workspace_role == "client" and viewer.custom_role_id is None)
    client_role = client_role or bool(
        viewer and viewer.custom_role and (viewer.custom_role.permissions or {}).get("client_facing")
    )
    return not (viewer is None or client_role)


def can_verify(request, workspace) -> bool:
    """Whether this person may record claims and attest photos: the brand's editors who verify here."""
    return _can_edit_brand(request) and request.user.pk in trust.verification_people(workspace)


def selected_claim(request, workspace) -> BrandClaim | None:
    """The claim ``?claim=`` reopens for review, read the same way here and in Settings → Advanced: one
    of this workspace's claims (another workspace's is 404); a malformed id is 400."""
    value = request.GET.get("claim")
    if not value:
        return None
    try:
        claim_id = uuid.UUID(value)
    except (TypeError, ValueError, AttributeError):
        raise BadRequest("Choose a valid workspace claim.") from None
    return get_object_or_404(BrandClaim, pk=claim_id, workspace=workspace)


def facts_context(request, workspace, *, form, selected, editable, claim_url) -> dict:
    """What the facts body shows (``partials/verified_facts.html``): this page and Settings → Advanced.

    ``claim_url(claim_id)`` is where a claim's "Review or renew" link reopens the including page.
    """
    active_ids = set(trust.current_claims(workspace).values_list("pk", flat=True))
    # Each claim carries two display attributes for the template: whether it is in use, and its link.
    claims: list[Any] = list(BrandClaim.objects.filter(workspace=workspace).select_related("verified_by")[:100])
    for claim in claims:
        claim.current = claim.pk in active_ids
        claim.edit_url = claim_url(claim.pk)
    photos = list(
        MediaAsset.objects.filter(workspace=workspace, organization=workspace.organization, media_type="image")
        .select_related("verified_by")
        .order_by("-created_at")[:40]
    )
    return {
        "workspace": workspace,
        "form": form,
        "claims": claims,
        "photos": [{"asset": a, "provenance": trust.photo_status(a)} for a in photos],
        "can_verify": editable,
        "selected_claim": selected,
    }


@login_required
@require_http_methods(["GET", "POST"])
def verified_facts(request, workspace_id):
    from django.http import HttpResponseBadRequest

    workspace = _workspace(request, workspace_id)
    if not may_read_facts(request, workspace):
        raise PermissionDenied("Source verification belongs to the agency team; client review remains in the portal.")
    # The page lives in Settings → Advanced while the advanced_settings switch shows it there (spec D1,
    # D6); otherwise it keeps rendering here, so the direct links to it keep working.
    if settings_links.is_page_view(request) and request_features(request)["advanced_settings"]:
        return settings_links.moved(request, workspace.pk, "advanced", anchor="verified-facts", cacheable=False)
    editable = can_verify(request, workspace)
    selected = selected_claim(request, workspace) if request.method == "GET" else None
    form = BrandClaimForm(workspace=workspace, instance=selected)
    if request.method == "POST":
        guards.forbid_in_agent_work("verify a commercial claim or property photo")
        if not editable or not request.user.is_active:
            raise PermissionDenied("A current internal approver or workspace manager must verify facts and photos.")
        with transaction.atomic():
            from apps.accounts.models import User
            from apps.members.models import CustomRole, OrgMembership, WorkspaceMembership
            from apps.workspaces.models import Workspace

            current_workspace = (
                Workspace.objects.select_for_update(of=("self",)).select_related("organization").get(pk=workspace.pk)
            )
            if (
                current_workspace.organization_id != workspace.organization_id
                or current_workspace.is_archived
                or current_workspace.organization.deleted_at is not None
            ):
                raise PermissionDenied("The workspace changed or is paused; reload before verifying sources.")
            workspace = current_workspace

            current_user = User.objects.select_for_update().filter(pk=request.user.pk, is_active=True).first()
            membership = (
                WorkspaceMembership.objects.select_for_update(of=("self",))
                .select_related("custom_role")
                .filter(workspace=workspace, user=request.user)
                .first()
            )
            organization_member = (
                OrgMembership.objects.select_for_update()
                .filter(organization=workspace.organization, user=request.user)
                .first()
            )
            if membership and membership.custom_role_id:
                CustomRole.objects.select_for_update().filter(pk=membership.custom_role_id).first()
            if current_user is None or organization_member is None:
                raise PermissionDenied("Your active organization membership changed.")
            if request.user.pk not in trust.verification_people(workspace):
                raise PermissionDenied("Your workspace verification permission changed.")
            if request.POST.get("kind") == "photo":
                try:
                    asset_id = uuid.UUID(request.POST.get("asset_id", ""))
                except (TypeError, ValueError, AttributeError):
                    return HttpResponseBadRequest("Choose a valid workspace photo.")
                asset = get_object_or_404(
                    MediaAsset.objects.select_for_update(),
                    pk=asset_id,
                    workspace=workspace,
                    organization=workspace.organization,
                    media_type="image",
                )
                project = " ".join(request.POST.get("project", "").split())[:200]
                if trust.is_generated(asset) or not project or request.POST.get("photo_confirmed") != "1":
                    messages.error(
                        request,
                        "Choose an authentic uploaded photo, name its project, and confirm the image is accurate. AI pictures remain illustrative.",
                    )
                else:
                    asset.authenticity = "verified"
                    asset.verified_project = project
                    asset.verified_by = request.user
                    asset.verified_at = timezone.now()
                    asset.verified_asset_hash = trust.asset_stamp(asset)
                    asset.save(
                        update_fields=[
                            "authenticity",
                            "verified_project",
                            "verified_by",
                            "verified_at",
                            "verified_asset_hash",
                            "updated_at",
                        ]
                    )
                    messages.success(request, "Your photo attestation is recorded for this file and project.")
                return redirect("studio:trust", workspace_id=workspace.pk)
            existing = None
            if request.POST.get("claim_id"):
                try:
                    claim_id = uuid.UUID(request.POST["claim_id"])
                except (TypeError, ValueError, AttributeError):
                    return HttpResponseBadRequest("Choose a valid workspace claim.")
                existing = get_object_or_404(BrandClaim.objects.select_for_update(), pk=claim_id, workspace=workspace)
            if request.POST.get("kind") == "retire" and existing:
                existing.is_active = False
                existing.save(update_fields=["is_active", "updated_at"])
                messages.success(request, "Claim retired. Drafts that relied on it require fresh review.")
                return redirect("studio:trust", workspace_id=workspace.pk)
            form = BrandClaimForm(request.POST, workspace=workspace, instance=existing)
            if form.is_valid():
                claim = form.save(commit=False)
                claim.workspace = workspace
                claim.verified_by = request.user
                claim.verified_at = timezone.now()
                claim.is_active = True
                claim.save()
                messages.success(request, "Source, verifier and expiry recorded. The team can use this current claim.")
                return redirect("studio:trust", workspace_id=workspace.pk)
    page = reverse("studio:trust", kwargs={"workspace_id": workspace.pk})
    return render(
        request,
        "studio/trust.html",
        {
            "tabs": dashboard.tabs(workspace, "trust", perms=_perms(request)),
            **facts_context(
                request,
                workspace,
                form=form,
                selected=selected,
                editable=editable,
                claim_url=lambda claim_id: f"{page}?claim={claim_id}",
            ),
        },
    )
