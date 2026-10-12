"""Manually recorded campaign events, without personal lead data or inferred attribution."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from uuid import UUID, uuid4

from django.contrib.auth import get_user_model
from django.core import signing
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.approvals.actor import current_actor
from apps.composer.models import Post
from apps.members.models import WorkspaceMembership

from .guards import forbid_in_agent_work
from .models import CampaignOutcome

OUTCOME_KINDS = ("enquiry", "qualified_enquiry", "site_visit")
_TOKEN_SALT = "studio-campaign-outcome"
_POST_STATES = ("approved", "scheduled", "publishing", "published")


def eligible_posts(workspace):
    """Only this workspace's actually approved/delivered content can be attributed."""
    return (
        Post.objects.filter(
            workspace=workspace,
            platform_posts__social_account__workspace=workspace,
            platform_posts__status__in=_POST_STATES,
        )
        .distinct()
        .order_by("-created_at")
    )


def totals(workspace, start: datetime, end: datetime) -> dict[str, int]:
    """Manual date-level event totals for the report's local date range.

    A midnight end is exclusive; a partial-day end includes that date's
    confirmed events. These aggregate entries cannot infer unique people or
    reconstruct automatic conversions, and backdated corrections are explicit.
    """
    rows = (
        CampaignOutcome.objects.filter(
            workspace=workspace,
            occurred_on__gte=start.date(),
            occurred_on__lte=(end - timedelta(microseconds=1)).date(),
        )
        .filter(Q(post__isnull=True) | Q(post__workspace=workspace))
        .values("kind")
        .annotate(total=Sum("count"))
    )
    counts = dict.fromkeys(OUTCOME_KINDS, 0)
    for row in rows:
        if row["kind"] in counts:
            counts[row["kind"]] = int(row["total"] or 0)
    return counts


def submission_token(workspace, user) -> str:
    return signing.dumps(
        {"workspace": str(workspace.pk), "user": str(user.pk), "entry": str(uuid4())},
        salt=_TOKEN_SALT,
    )


def _submission_id(workspace, user, token: str) -> UUID:
    try:
        payload = signing.loads(token, salt=_TOKEN_SALT, max_age=3600)
        if payload["workspace"] != str(workspace.pk) or payload["user"] != str(user.pk):
            raise ValueError
        return UUID(payload["entry"])
    except (signing.BadSignature, ValueError, KeyError, TypeError) as exc:
        raise ValueError("This entry form expired or belongs to another workspace. Refresh it and try again.") from exc


def can_record(membership) -> bool:
    return bool(
        membership is not None
        and membership.workspace_role != WorkspaceMembership.WorkspaceRole.CLIENT
        and (
            membership.workspace_role in {"owner", "manager"}
            or membership.effective_permissions.get("create_posts", False)
        )
    )


def record(workspace, user, *, token: str, campaign_name: str, occurred_on, kind: str, count: int, post=None):
    """Record a human's scoped entry once, rechecking current permissions under lock."""
    forbid_in_agent_work("record campaign outcomes")
    actor = current_actor()
    if not actor.is_dashboard or getattr(actor.user, "pk", None) != user.pk:
        raise ValueError("Campaign outcomes must be recorded by a signed-in person in the dashboard.")
    entry_id = _submission_id(workspace, user, token)
    campaign_name = (campaign_name or "").strip()
    if not campaign_name or len(campaign_name) > 120 or kind not in OUTCOME_KINDS:
        raise ValueError("Choose a campaign label and a supported outcome type.")
    if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 1_000_000:
        raise ValueError("Record between one and one million confirmed events.")
    from .jobtypes.plan import zone_of

    if not isinstance(occurred_on, date) or isinstance(occurred_on, datetime):
        raise ValueError("Choose the date the confirmed outcome happened.")
    if occurred_on > timezone.now().astimezone(zone_of(workspace)).date():
        raise ValueError("Record an outcome that already happened, rather than a future visit.")
    with transaction.atomic():
        active = get_user_model().objects.select_for_update().filter(pk=user.pk, is_active=True).exists()
        membership = (
            WorkspaceMembership.objects.select_for_update(of=("self",))
            .select_related("custom_role")
            .filter(
                workspace=workspace,
                user=user,
            )
            .first()
        )
        from apps.workspaces.models import Workspace

        current_workspace = Workspace.objects.select_for_update().filter(pk=workspace.pk, is_archived=False).exists()
        if not active or not can_record(membership) or not current_workspace:
            raise ValueError("Your current workspace permissions do not allow recording campaign outcomes.")
        if post is not None:
            locked_post = Post.objects.select_for_update().filter(pk=post.pk, workspace=workspace).first()
            if locked_post is None or not eligible_posts(workspace).filter(pk=locked_post.pk).exists():
                raise ValueError("Choose an approved or published post from this workspace.")
        existing = CampaignOutcome.objects.filter(pk=entry_id).first()
        fields = {
            "workspace_id": workspace.pk,
            "recorded_by_id": user.pk,
            "post_id": post.pk if post is not None else None,
            "campaign_name": campaign_name,
            "occurred_on": occurred_on,
            "kind": kind,
            "count": count,
        }
        if existing is not None:
            if any(getattr(existing, key) != value for key, value in fields.items()):
                raise ValueError(
                    "This entry was already recorded with different values. Refresh the form for a new entry."
                )
            return existing, False
        return CampaignOutcome.objects.create(pk=entry_id, **fields), True
