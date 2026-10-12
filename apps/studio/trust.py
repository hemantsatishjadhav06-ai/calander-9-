"""Owner attestations and expiring claim evidence; no external verification is implied."""

from __future__ import annotations

import hashlib
import json
import zoneinfo
from typing import Any

from django.utils import timezone

from .models import BrandClaim


def local_date(workspace, now=None):
    try:
        zone = zoneinfo.ZoneInfo(workspace.effective_timezone or "UTC")
    except (ValueError, zoneinfo.ZoneInfoNotFoundError):
        zone = zoneinfo.ZoneInfo("UTC")
    return (now or timezone.now()).astimezone(zone).date()


def current_claims(workspace, now=None):
    return (
        BrandClaim.objects.filter(
            workspace=workspace,
            is_active=True,
            verified_by_id__in=verification_people(workspace),
            verified_by__is_active=True,
            verified_at__isnull=False,
            verified_at__lte=now or timezone.now(),
            valid_until__gte=local_date(workspace, now),
        )
        .exclude(source_url="", source_note="")
        .order_by("category", "id")
    )


def verification_people(workspace) -> set:
    from apps.members.models import OrgMembership, WorkspaceMembership

    org_members = {
        m.user_id: m.org_role
        for m in OrgMembership.objects.filter(organization=workspace.organization, user__is_active=True)
    }
    permitted: set[Any] = set()
    for member in WorkspaceMembership.objects.filter(workspace=workspace, user__is_active=True).select_related(
        "custom_role"
    ):
        invalid = member.workspace_role == "client" and member.custom_role_id is None
        invalid = invalid or bool(member.custom_role and (member.custom_role.permissions or {}).get("client_facing"))
        invalid = invalid or bool(
            member.custom_role and member.custom_role.organization_id != workspace.organization_id
        )
        if invalid:
            permitted.discard(member.user_id)
            continue
        perms = member.effective_permissions
        if member.user_id in org_members and (perms.get("approve_posts") or perms.get("manage_workspace_settings")):
            permitted.add(member.user_id)
        else:
            permitted.discard(member.user_id)
    return permitted


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def claim_stamp(claim: BrandClaim) -> str:
    return _digest(
        {
            "workspace": str(claim.workspace_id),
            "text": claim.claim,
            "category": claim.category,
            "source": claim.source_url,
            "note": claim.source_note,
            "verifier": str(claim.verified_by_id),
            "verified_at": claim.verified_at,
            "valid_until": claim.valid_until,
            "active": claim.is_active,
        }
    )


def claims_context(profile) -> str:
    workspace = getattr(profile, "workspace", None)
    if workspace is None or not getattr(workspace, "pk", None):
        return "No owner-verified claims are recorded. Ask for a verified source before stating commercial claims."
    claims = list(current_claims(workspace)[:100])
    if not claims:
        return "No current owner-verified claims. Saved background notes are unverified; ask before stating prices, availability, registration, title or launch promises."
    return "\n".join(
        f"[{c.category}; owner attested {c.verified_at.date()}; valid through {c.valid_until}; source: {c.source_url or c.source_note}] {c.claim}"
        for c in claims
    )


def is_generated(asset) -> bool:
    tags = getattr(asset, "tags", []) or []
    tags = [tags] if isinstance(tags, str) else tags if isinstance(tags, list) else []
    return bool(
        asset
        and (
            str(asset.source or "").strip().lower() in {"fal.ai", "ai-studio"}
            or "ai" in {str(t).strip().lower() for t in tags}
        )
    )


def asset_stamp(asset) -> str:
    # Local immutable files also bind their version/stat identity. Remote
    # storage uses the upload UUID and MediaVersion; no HTTP under row locks.
    try:
        import os

        stat = os.stat(asset.file.path)
        local_identity = [stat.st_ino, stat.st_size, stat.st_mtime_ns]
    except (OSError, NotImplementedError, ValueError):
        local_identity = None
    return _digest(
        {
            "id": str(asset.pk),
            "workspace": str(asset.workspace_id),
            "organization": str(asset.organization_id),
            "file": asset.file.name,
            "version": str(asset.current_version_id),
            "source": asset.source,
            "width": asset.width,
            "height": asset.height,
            "local_identity": local_identity,
        }
    )


def photo_status(asset) -> dict[str, Any]:
    if is_generated(asset) or getattr(asset, "authenticity", "unknown") == "illustrative":
        return {
            "status": "illustrative",
            "label": "Illustrative image — not proof of a named property",
            "verified_project": "",
            "source_generated": is_generated(asset),
        }
    verified = bool(
        asset.authenticity == "verified"
        and asset.workspace_id
        and asset.verified_by_id
        and asset.verified_at
        and asset.verified_at <= timezone.now()
        and asset.verified_project
        and asset.verified_asset_hash == asset_stamp(asset)
        and asset.verified_by.is_active
        and asset.verified_by_id in verification_people(asset.workspace)
    )
    return {
        "status": "verified" if verified else "unknown",
        "label": f"Person-verified photo: {asset.verified_project}"
        if verified
        else "Unverified photo — confirm its project before making property claims",
        "verified_project": asset.verified_project if verified else "",
        "source_generated": False,
    }


def capture(brief) -> dict[str, Any]:
    claims = list(current_claims(brief.workspace)[:100])
    picture = brief.source_picture
    return {
        "revision": brief.revision,
        "claims": [{"id": str(c.pk), "stamp": claim_stamp(c)} for c in claims],
        "photo": {"id": str(picture.pk), "stamp": asset_stamp(picture), "provenance": photo_status(picture)}
        if picture
        else None,
    }


def blocker(brief) -> str | None:
    snapshot = brief.trust_snapshot
    if snapshot == {}:
        return "This draft has no current source review. Request a fresh revision or have an internal approver review it again."
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("revision") != brief.revision
        or not isinstance(snapshot.get("claims"), list)
        or "photo" not in snapshot
    ):
        return "The draft's source review is incomplete or belongs to another revision. Request a fresh revision."
    available = {str(c.pk): claim_stamp(c) for c in current_claims(brief.workspace)}
    for item in snapshot["claims"]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("id"), str)
            or not isinstance(item.get("stamp"), str)
            or available.get(item["id"]) != item["stamp"]
        ):
            return "A source claim changed or expired. Have a person verify it under Agency → Verified facts, then request a fresh revision."
    photo = snapshot["photo"]
    if bool(photo) != bool(brief.source_picture_id):
        return "The selected photo is missing from this source review. Select and confirm it in a fresh revision."
    if photo:
        import uuid

        from apps.media_library.models import MediaAsset

        if not isinstance(photo, dict) or str(brief.source_picture_id) != photo.get("id"):
            return "The selected photo does not match this source review. Select it again in a fresh revision."
        try:
            photo_id = uuid.UUID(str(photo.get("id")))
        except (TypeError, ValueError, AttributeError):
            return "The photo reference is invalid. Select it again in a fresh revision."
        asset = MediaAsset.objects.filter(
            pk=photo_id, workspace=brief.workspace, organization=brief.workspace.organization
        ).first()
        if asset is None or asset_stamp(asset) != photo.get("stamp") or photo_status(asset) != photo.get("provenance"):
            return (
                "The selected photo or its provenance changed. Select and review the current photo in a fresh revision."
            )
    return None


def verified_cta(profile) -> str:
    import re

    cta = profile.default_cta or ""
    numbers = re.findall(r"\d+", cta)
    if not numbers:
        return cta
    authority = claims_context(profile)
    if all(number in authority for number in numbers):
        return cta
    return "Invite the reader to contact the brand through its website; do not quote an unverified phone or price."


def post_blocker(post) -> str | None:
    for brief in post.studio_briefs.select_related("workspace", "workspace__organization").filter(
        status__in=["ready", "approved"]
    ):
        reason = blocker(brief)
        if reason:
            return reason
    return None
