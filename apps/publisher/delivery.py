"""Bound late delivery and reconcile uncertain writes through a human audit trail."""

from __future__ import annotations

import contextvars
import hashlib
import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.approvals import gate
from apps.approvals.actor import DASHBOARD, current_actor
from apps.approvals.models import ApprovalAction
from apps.composer.models import PlatformPost, Post

STATE_KEY = "_delivery_state"
LATENESS_KEY = "publishing.max_lateness_seconds"
DEFAULT_MAX_LATENESS_SECONDS = 86400
MIN_MAX_LATENESS_SECONDS = 60
MAX_MAX_LATENESS_SECONDS = 7 * 86400
UNRESOLVED = {"unknown", "expired"}
_DELIVERY_WRITES: contextvars.ContextVar[bool] = contextvars.ContextVar("trusted_delivery_write", default=False)


def trusted_delivery_write() -> bool:
    return _DELIVERY_WRITES.get()


@contextmanager
def delivery_write():
    """Reserved for publisher bookkeeping and already-authorized human reconciliation."""
    token = _DELIVERY_WRITES.set(True)
    try:
        yield
    finally:
        _DELIVERY_WRITES.reset(token)


class DeliveryActionError(ValueError):
    """A delivery record needs a fresh, scoped human decision."""


def state(pp) -> dict:
    extra = pp.platform_extra if isinstance(pp.platform_extra, dict) else {}
    value = extra.get(STATE_KEY)
    local = value if isinstance(value, dict) else {}
    if isinstance(pp, PlatformPost):
        registry = Post.objects.filter(pk=pp.post_id).values_list("delivery_holds", flat=True).first()
        held = registry.get(_registry_key(pp)) if isinstance(registry, dict) else None
        if isinstance(held, dict) and held.get("kind") in UNRESOLVED:
            return held
    return local


def _registry_key(pp) -> str:
    identity = destination(pp)
    identity.pop("account_id")
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def has_unresolved_holds(post) -> bool:
    registry = Post.objects.filter(pk=post.pk).values_list("delivery_holds", flat=True).first()
    return isinstance(registry, dict) and any(
        isinstance(item, dict) and item.get("kind") in UNRESOLVED for item in registry.values()
    )


def _record_hold(pp, evidence: dict) -> None:
    parent = Post.objects.select_for_update().get(pk=pp.post_id)
    registry = parent.delivery_holds if isinstance(parent.delivery_holds, dict) else {}
    registry = {**registry, _registry_key(pp): evidence}
    Post.objects.filter(pk=parent.pk).update(delivery_holds=registry)
    pp.post.delivery_holds = registry


def max_lateness_seconds(workspace) -> int:
    from apps.settings_manager.models import WorkspaceSetting

    raw = WorkspaceSetting.objects.filter(workspace=workspace, key=LATENESS_KEY).values_list("value", flat=True).first()
    if raw is None:
        raw = getattr(settings, "PUBLISHER_MAX_LATENESS_SECONDS", DEFAULT_MAX_LATENESS_SECONDS)
    try:
        if isinstance(raw, bool):
            raise ValueError
        value = int(raw) if raw is not None else DEFAULT_MAX_LATENESS_SECONDS
    except (TypeError, ValueError, OverflowError):
        value = DEFAULT_MAX_LATENESS_SECONDS
    return min(MAX_MAX_LATENESS_SECONDS, max(MIN_MAX_LATENESS_SECONDS, value))


def hold_reason(pp, *, now=None) -> str:
    kind = state(pp).get("kind")
    if kind == "unknown":
        return "Delivery outcome unknown. Check the account and record what happened before preparing another attempt."
    if kind == "expired":
        return "This approved time expired. Return the post for review, choose a future time and approve it again."
    effective = pp.scheduled_at or pp.post.scheduled_at
    if isinstance(effective, datetime) and effective + timedelta(seconds=max_lateness_seconds(pp.post.workspace)) < (
        now or timezone.now()
    ):
        return "This approved time expired. Return the post for review, choose a future time and approve it again."
    return ""


def destination(pp) -> dict:
    account = pp.social_account
    return {
        "workspace_id": str(pp.post.workspace_id),
        "account_workspace_id": str(account.workspace_id),
        "account_id": str(account.pk),
        "platform": account.platform,
        "native_id": account.account_platform_id,
        "instance_url": account.instance_url or "",
    }


def snapshot(pp, *, kind: str, reason: str = "") -> dict:
    return {
        "kind": kind,
        "platform_post_id": str(pp.pk),
        "attempt_id": str(uuid.uuid4()),
        "at": timezone.now().isoformat(),
        "reason": reason[:300],
        "content_fingerprint": gate.fingerprint(pp),
        "approved_fingerprint": pp.approved_fingerprint or "",
        "publish_at": gate.effective_publish_at(pp).isoformat() if gate.effective_publish_at(pp) else None,
        "revision": gate._current_revision(pp.post),
        "destination": destination(pp),
    }


def mark(pp, *, kind: str, reason: str, from_status="publishing") -> bool:
    """Settle only the claimed row, retaining its original content/destination snapshot."""
    with transaction.atomic(), delivery_write():
        fresh = (
            PlatformPost.objects.select_for_update(of=("self",))
            .select_related("post__workspace", "social_account")
            .filter(pk=pp.pk, status=from_status)
            .first()
        )
        if fresh is None:
            return False
        previous = state(fresh)
        evidence = (
            previous if previous.get("kind") in {"submitting", "unknown", "expired"} else snapshot(fresh, kind=kind)
        )
        evidence = {**evidence, "kind": kind, "reason": reason[:300]}
        _record_hold(fresh, evidence)
        extra = {**(fresh.platform_extra or {}), STATE_KEY: evidence}
        PlatformPost.objects.filter(pk=fresh.pk).update(
            status=PlatformPost.Status.FAILED,
            platform_extra=extra,
            publish_error=reason[:2000],
            next_retry_at=None,
            updated_at=timezone.now(),
        )
        ApprovalAction.objects.create(
            post=fresh.post,
            platform_post=fresh,
            action=ApprovalAction.ActionType.BLOCKED,
            comment=reason[:2000],
            fingerprint=evidence.get("content_fingerprint", ""),
            revision=evidence.get("revision"),
            publish_at=fresh.approved_publish_at,
            channel="system",
        )
        pp.status, pp.platform_extra, pp.publish_error, pp.next_retry_at = (
            PlatformPost.Status.FAILED,
            extra,
            reason,
            None,
        )
    return True


def _authorize(workspace, user, *, locked: bool = False) -> None:
    from apps.accounts.models import User
    from apps.members.models import CustomRole, OrgMembership, WorkspaceMembership
    from apps.studio.guards import forbid_in_agent_work

    forbid_in_agent_work("reconcile a publishing outcome")
    actor = current_actor()
    if (
        actor.channel != DASHBOARD
        or not actor.is_dashboard
        or actor.user is None
        or actor.user.pk != getattr(user, "pk", None)
    ):
        raise PermissionDenied("An internal approver signed in to the dashboard must reconcile delivery.")
    users = User.objects.filter(pk=user.pk, is_active=True)
    memberships = WorkspaceMembership.objects.select_related("custom_role").filter(workspace=workspace, user=user)
    org_memberships = OrgMembership.objects.filter(user=user, organization_id=workspace.organization_id)
    if locked:
        users = users.select_for_update()
        memberships = memberships.select_for_update(of=("self",))
        org_memberships = org_memberships.select_for_update()
    if users.first() is None:
        raise PermissionDenied("This account cannot reconcile delivery.")
    member = memberships.first()
    if locked and member and member.custom_role_id:
        member.custom_role = CustomRole.objects.select_for_update().get(pk=member.custom_role_id)
    if (
        member is None
        or member.workspace_role == WorkspaceMembership.WorkspaceRole.CLIENT
        or not all(member.effective_permissions.get(p) for p in ("approve_posts", "create_posts"))
    ):
        raise PermissionDenied("This action requires an internal approver with permission to create posts.")
    if org_memberships.first() is None:
        raise PermissionDenied("You are not a member of this organization.")


def _locked(pp_id, workspace, *, expected_attempt_id: str, expected_fingerprint: str):
    pp = (
        PlatformPost.objects.select_for_update(of=("self",))
        .select_related("post__workspace", "social_account")
        .filter(pk=pp_id, post__workspace=workspace, social_account__workspace=workspace)
        .first()
    )
    if pp is None:
        raise DeliveryActionError("This delivery record is unavailable in this workspace.")
    evidence = state(pp)
    if evidence.get("kind") not in UNRESOLVED or pp.status != PlatformPost.Status.FAILED:
        raise DeliveryActionError("This delivery record was already resolved. Refresh the draft.")
    if evidence.get("attempt_id") != expected_attempt_id or evidence.get("content_fingerprint") != expected_fingerprint:
        raise DeliveryActionError("This delivery record changed. Refresh the draft before confirming.")
    if (
        destination(pp) != evidence.get("destination")
        or gate.fingerprint(pp) != evidence.get("content_fingerprint")
        or gate._current_revision(pp.post) != evidence.get("revision")
    ):
        raise DeliveryActionError(
            "Content or destination changed after this attempt. Ask your administrator to review its delivery evidence."
        )
    if gate.enforced(pp.post.workspace) and (
        not evidence.get("approved_fingerprint") or pp.approved_fingerprint != evidence.get("approved_fingerprint")
    ):
        raise DeliveryActionError(
            "The approval for this attempt changed. Ask your administrator to review its delivery evidence."
        )
    return pp, evidence


def _public_post_url(account, url: str) -> str:
    if not isinstance(url, str) or len(url) > 2000:
        raise DeliveryActionError("Enter a public HTTPS link to the existing post.")
    try:
        parts = urlsplit(url.strip())
    except ValueError as exc:
        raise DeliveryActionError("Enter a valid public HTTPS post link.") from exc
    hosts = {
        "facebook": {"facebook.com", "www.facebook.com", "m.facebook.com"},
        "instagram": {"instagram.com", "www.instagram.com"},
        "instagram_login": {"instagram.com", "www.instagram.com"},
        "threads": {"threads.net", "www.threads.net", "threads.com", "www.threads.com"},
        "x": {"x.com", "www.x.com", "twitter.com", "www.twitter.com"},
        "linkedin_personal": {"linkedin.com", "www.linkedin.com"},
        "linkedin_company": {"linkedin.com", "www.linkedin.com"},
        "tiktok": {"tiktok.com", "www.tiktok.com"},
        "youtube": {"youtube.com", "www.youtube.com", "youtu.be"},
        "pinterest": {"pinterest.com", "www.pinterest.com"},
        "bluesky": {"bsky.app"},
        "google_business": {"google.com", "www.google.com", "g.page"},
    }.get(account.platform, set())
    if account.platform == "mastodon":
        hosts = {urlsplit(account.instance_url).hostname}
    try:
        invalid_port = parts.port not in (None, 443)
    except ValueError:
        invalid_port = True
    if (
        parts.scheme != "https"
        or parts.hostname not in hosts
        or parts.username
        or parts.password
        or invalid_port
        or not parts.path.strip("/")
        or any(ord(c) < 32 for c in url)
        or any(k.lower() in {"access_token", "token", "key", "api_key", "secret"} for k in parse_qs(parts.query))
    ):
        raise DeliveryActionError("Enter a public HTTPS post link on this account's platform, without credentials.")
    return url.strip()


def reconcile_existing(
    pp_id,
    workspace,
    user,
    *,
    native_post_id: str,
    url: str,
    confirmed: bool,
    expected_attempt_id: str,
    expected_fingerprint: str,
) -> PlatformPost:
    """Record a person's account inspection; this does not independently verify a provider."""
    _authorize(workspace, user)
    if (
        confirmed is not True
        or not isinstance(native_post_id, str)
        or not native_post_id.strip()
        or len(native_post_id) > 255
        or any(c.isspace() or ord(c) < 32 for c in native_post_id)
    ):
        raise DeliveryActionError("Confirm that you inspected the intended account and enter its existing post ID.")
    with transaction.atomic(), delivery_write():
        _authorize(workspace, user, locked=True)
        pp, evidence = _locked(
            pp_id, workspace, expected_attempt_id=expected_attempt_id, expected_fingerprint=expected_fingerprint
        )
        if evidence["kind"] != "unknown":
            raise DeliveryActionError("An expired, unsent post cannot be marked as an existing publication.")
        public_url = _public_post_url(pp.social_account, url)
        extra = {
            **(pp.platform_extra or {}),
            "permalink": public_url,
            STATE_KEY: {
                **evidence,
                "kind": "reconciled",
                "confirmed_by": str(user.pk),
                "confirmed_at": timezone.now().isoformat(),
                "verification": "human_attestation",
            },
        }
        _record_hold(pp, extra[STATE_KEY])
        PlatformPost.objects.filter(pk=pp.pk).update(
            status=PlatformPost.Status.PUBLISHED,
            platform_post_id=native_post_id.strip(),
            platform_extra=extra,
            published_at=timezone.now(),
            publish_error="",
            next_retry_at=None,
            updated_at=timezone.now(),
        )
        ApprovalAction.objects.create(
            post=pp.post,
            platform_post=pp,
            user=user,
            action=ApprovalAction.ActionType.RECONCILED,
            comment=f"Human inspected the intended account and recorded existing post {native_post_id.strip()}: {public_url}. No publishing request was sent.",
            fingerprint=evidence["content_fingerprint"],
            revision=evidence.get("revision"),
            publish_at=pp.approved_publish_at,
            channel=DASHBOARD,
        )
        pp.refresh_from_db()
        from .engine import PublishEngine

        engine = PublishEngine()
        engine._drop_queue_entry(pp)
        engine._sync_parent_published_at(pp.post)
    return pp


def checked_absent(
    pp_id, workspace, user, *, confirmed: bool, reason: str, expected_attempt_id: str, expected_fingerprint: str
) -> PlatformPost:
    """Return an unsent/checked-absent attempt for fresh review, never for automatic retry."""
    _authorize(workspace, user)
    if confirmed is not True or not isinstance(reason, str) or not 10 <= len(reason.strip()) <= 1000:
        raise DeliveryActionError("Confirm the account check and explain the result in 10–1000 characters.")
    with transaction.atomic(), delivery_write():
        _authorize(workspace, user, locked=True)
        pp, evidence = _locked(
            pp_id, workspace, expected_attempt_id=expected_attempt_id, expected_fingerprint=expected_fingerprint
        )
        extra = {
            **(pp.platform_extra or {}),
            STATE_KEY: {
                **evidence,
                "kind": "checked_absent",
                "confirmed_by": str(user.pk),
                "confirmed_at": timezone.now().isoformat(),
                "verification": "human_attestation",
            },
        }
        _record_hold(pp, extra[STATE_KEY])
        PlatformPost.objects.filter(pk=pp.pk).update(
            status=PlatformPost.Status.PENDING_REVIEW,
            platform_extra=extra,
            scheduled_at=None,
            platform_post_id="",
            approved_fingerprint="",
            approved_revision=None,
            approved_by=None,
            approved_at=None,
            approved_publish_at=None,
            publish_error="",
            retry_count=0,
            next_retry_at=None,
            updated_at=timezone.now(),
        )
        ApprovalAction.objects.create(
            post=pp.post,
            platform_post=pp,
            user=user,
            action=ApprovalAction.ActionType.RECONCILIATION_CHECKED,
            comment=reason.strip(),
            fingerprint=evidence["content_fingerprint"],
            revision=evidence.get("revision"),
            publish_at=pp.approved_publish_at,
            channel=DASHBOARD,
        )
        pp.refresh_from_db()
    return pp
