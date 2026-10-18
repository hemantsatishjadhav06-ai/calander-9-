"""First-value milestones require current facts, a confirmed draft and actual delivery."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.approvals.models import ApprovalAction
from apps.composer.models import PlatformPost, Post
from apps.onboarding.checklist import get_checklist_items
from apps.studio.forms_agency import eligible_leads
from apps.studio.models import AgencyJob, BrandClaim, StudioBrief
from apps.studio.trust import local_date


def _milestones(world):
    return {item["key"]: item for item in get_checklist_items(world.workspace)}


@pytest.mark.parametrize("revocation", ["organization", "workspace", "inactive", "client_facing"])
def test_autopilot_lead_and_backup_choices_require_current_internal_authority(world, revocation):
    from apps.members.models import CustomRole, OrgMembership, WorkspaceMembership

    assert world.owner.pk in {user.pk for user, _role in eligible_leads(world.workspace)}
    if revocation == "organization":
        OrgMembership.objects.filter(user=world.owner, organization=world.org).delete()
    elif revocation == "workspace":
        WorkspaceMembership.objects.filter(user=world.owner, workspace=world.workspace).delete()
    elif revocation == "inactive":
        world.owner.is_active = False
        world.owner.save(update_fields=["is_active"])
    else:
        role = CustomRole.objects.create(
            organization=world.org,
            name="Client reviewer with misleading create permissions",
            permissions={"client_facing": True, "create_posts": True, "approve_posts": True},
        )
        WorkspaceMembership.objects.filter(user=world.owner, workspace=world.workspace).update(custom_role=role)
    assert world.owner.pk not in {user.pk for user, _role in eligible_leads(world.workspace)}


def test_activation_does_not_treat_unverified_background_notes_or_stale_accounts_as_ready(world):
    assert not _milestones(world)["verified_facts"]["completed"]
    world.linkedin.connection_status = "disconnected"
    world.linkedin.save(update_fields=["connection_status"])
    world.x.token_expires_at = timezone.now() - timedelta(days=1)
    world.x.save(update_fields=["token_expires_at"])
    assert not _milestones(world)["connect_accounts"]["completed"]
    claim = BrandClaim.objects.create(
        workspace=world.workspace,
        claim="Contact the Neopolis team",
        source_note="Owner's confirmed contact details",
        verified_by=world.owner,
        verified_at=timezone.now(),
        valid_until=local_date(world.workspace) - timedelta(days=1),
    )
    assert not _milestones(world)["verified_facts"]["completed"]
    claim.valid_until = local_date(world.workspace) + timedelta(days=7)
    claim.save(update_fields=["valid_until"])
    assert _milestones(world)["verified_facts"]["completed"]


def test_activation_distinguishes_confirmed_brief_human_review_schedule_and_native_delivery(world):
    post = Post.objects.create(workspace=world.workspace, caption="Site-visit invitation")
    pp = PlatformPost.objects.create(post=post, social_account=world.linkedin, status="draft")
    job = AgencyJob.objects.create(
        workspace=world.workspace,
        kind="chat",
        requested_by=world.editor,
        input={"kind": "confirm_brief", "facts_confirmed": True},
    )
    StudioBrief.objects.create(
        workspace=world.workspace, author=world.editor, idea="Site visits", origin="chat", job=job, post=post
    )
    initial = _milestones(world)
    assert initial["confirmed_brief"]["completed"]
    assert not initial["review_draft"]["completed"] and not initial["published_post"]["completed"]
    ApprovalAction.objects.create(post=post, user=world.owner, action="approved", channel="dashboard")
    PlatformPost.objects.filter(pk=pp.pk).update(status="scheduled", scheduled_at=timezone.now())
    assert _milestones(world)["review_draft"]["completed"]
    assert not _milestones(world)["published_post"]["completed"]
    PlatformPost.objects.filter(pk=pp.pk).update(status="published", published_at=timezone.now())
    assert not _milestones(world)["published_post"]["completed"]  # no native result yet
    PlatformPost.objects.filter(pk=pp.pk).update(platform_post_id="native-site-visit-result")
    assert _milestones(world)["published_post"]["completed"]


def test_unconfirmed_or_other_workspace_job_cannot_grant_the_first_brief_milestone(world):
    job = AgencyJob.objects.create(workspace=world.workspace, kind="chat", input={"kind": "question"})
    StudioBrief.objects.create(
        workspace=world.workspace, author=world.editor, idea="Not confirmed", origin="chat", job=job
    )
    assert not _milestones(world)["confirmed_brief"]["completed"]
    assert "/thread/" in _milestones(world)["confirmed_brief"]["url"]
