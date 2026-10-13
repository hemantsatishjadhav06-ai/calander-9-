"""Activation milestones for a reviewed brand draft and its actual delivery."""

from datetime import timedelta

from django.urls import reverse


def get_checklist_items(workspace):
    """Guide the first useful agency outcome without treating a draft as delivery.

    The account milestone reflects saved connection health, not an independent
    live identity check. Publication requires a successful native post ID.
    ``icon_svg`` values are server constants because the template uses safe.
    """
    from apps.approvals.models import ApprovalAction
    from apps.composer.models import PlatformPost
    from apps.members.models import WorkspaceMembership
    from apps.social_accounts.models import SocialAccount
    from apps.studio.models import StudioBrief
    from apps.studio.trust import current_claims

    workspace_id = workspace.pk
    healthy = any(
        not account.needs_reconnect and not account.token_expires_within(timedelta(seconds=0))
        for account in SocialAccount.objects.filter(workspace=workspace, connection_status="connected")
    )
    checked_facts = current_claims(workspace).exists()
    confirmed = StudioBrief.objects.filter(
        workspace=workspace,
        origin=StudioBrief.Origin.CHAT,
        job__workspace=workspace,
        job__input__kind="confirm_brief",
        job__input__facts_confirmed=True,
    ).exists()
    reviewed = ApprovalAction.objects.filter(
        post__workspace=workspace,
        action=ApprovalAction.ActionType.APPROVED,
        channel="dashboard",
        user__isnull=False,
    ).exists()
    delivered = (
        PlatformPost.objects.filter(
            post__workspace=workspace,
            social_account__workspace=workspace,
            status=PlatformPost.Status.PUBLISHED,
            published_at__isnull=False,
        )
        .exclude(platform_post_id="")
        .exists()
    )
    calendar = reverse("calendar:calendar", kwargs={"workspace_id": workspace_id})
    milestones = [
        (
            "verified_facts",
            "Confirm your brand facts",
            "Add an owner-verified source and review date before briefing the team.",
            checked_facts,
            reverse("studio:trust", kwargs={"workspace_id": workspace_id}),
        ),
        (
            "connect_accounts",
            "Connect your brand account",
            "Connect an active account and check that it belongs to this brand.",
            healthy,
            reverse("social_accounts:connect", kwargs={"workspace_id": workspace_id}),
        ),
        (
            "confirmed_brief",
            "Confirm your first creative brief",
            "Answer the team's questions, check the source facts and confirm a draft.",
            confirmed,
            reverse("studio:thread", kwargs={"workspace_id": workspace_id}),
        ),
        (
            "review_draft",
            "Review your first draft",
            "Check the finished graphic and each channel's copy, then approve and schedule.",
            reviewed,
            calendar + "?mode=list&tab=approvals",
        ),
        (
            "published_post",
            "Check your first published post",
            "Confirm the actual post on the intended account after delivery.",
            delivered,
            calendar + "?mode=list&tab=sent",
        ),
        (
            "invite_members",
            "Invite your team",
            "Add an active teammate to collaborate on content and review.",
            WorkspaceMembership.objects.filter(workspace=workspace, user__is_active=True)
            .exclude(workspace_role=WorkspaceMembership.WorkspaceRole.OWNER)
            .exists(),
            reverse("members:list"),
        ),
    ]
    icon = '<path d="M9 12l2 2 4-4"/><circle cx="12" cy="12" r="9"/>'
    return [
        {
            "key": key,
            "title": title,
            "description": description,
            "completed": complete,
            "url": url,
            "icon_color": "sky",
            "icon_svg": icon,
        }
        for key, title, description, complete, url in milestones
    ]
