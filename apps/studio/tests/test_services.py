"""Approving, scheduling, revising and discarding what the team made."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.approvals.actor import acting_as
from apps.approvals.models import ApprovalAction
from apps.composer.models import Idea, PlatformPost, Post
from apps.studio import services
from apps.studio.models import StudioBrief
from apps.studio.tests.conftest import make_brief, run_all


@pytest.fixture
def ready(world, fake_team):
    return run_all(make_brief(world, accounts=[world.linkedin, world.x]))


def _statuses(brief):
    return set(PlatformPost.objects.filter(post=brief.post).values_list("status", flat=True))


def test_approve_and_publish_now_schedules_every_channel_for_now(world, ready):
    with acting_as(world.owner):
        message = services.approve(ready, world.owner, publish_now=True)
    assert "publishing now to 2 account(s)" in message
    rows = PlatformPost.objects.filter(post=ready.post)
    assert {pp.status for pp in rows} == {"scheduled"}
    assert all(pp.scheduled_at <= timezone.now() for pp in rows)
    ready.refresh_from_db()
    assert ready.status == StudioBrief.Status.APPROVED


def test_approve_and_schedule_uses_the_chosen_time(world, ready):
    when = timezone.now() + timedelta(days=2)
    with acting_as(world.manager):
        message = services.approve(ready, world.manager, publish_at=when)
    assert "scheduled for" in message
    assert {pp.scheduled_at for pp in PlatformPost.objects.filter(post=ready.post)} == {when}


def test_approve_only_leaves_it_to_schedule_later(world, ready):
    with acting_as(world.owner):
        services.approve(ready, world.owner)
    assert _statuses(ready) == {"approved"}


def test_a_past_time_is_refused(world, ready):
    with acting_as(world.owner), pytest.raises(services.StudioActionError, match="future"):
        services.approve(ready, world.owner, publish_at=timezone.now() - timedelta(minutes=5))
    assert _statuses(ready) == {"pending_review"}


def test_an_enforced_workspace_needs_an_internal_approver_in_the_dashboard(world, ready):
    world.workspace.require_dashboard_approval = True
    world.workspace.save()
    # Not in the dashboard (the worker, the API…): nothing is approved.
    with pytest.raises(services.StudioActionError, match="internal approver"):
        services.approve(ready, world.owner, publish_now=True)
    assert _statuses(ready) == {"pending_review"}

    with acting_as(world.owner):
        services.approve(ready, world.owner, publish_now=True)
    rows = list(PlatformPost.objects.filter(post=ready.post))
    assert {pp.status for pp in rows} == {"scheduled"}
    # The approval is stamped with exactly what goes out, and audited.
    assert all(pp.approved_fingerprint and pp.approved_by == world.owner for pp in rows)
    assert ApprovalAction.objects.filter(post=ready.post, action="approved").count() == 2


def test_two_stage_workflows_go_to_the_client(world, ready):
    world.workspace.approval_workflow_mode = "required_internal_and_client"
    world.workspace.save()
    with acting_as(world.owner):
        message = services.approve(ready, world.owner, publish_now=True)
    assert "client" in message
    assert _statuses(ready) == {"pending_client"}


def test_request_changes_starts_a_new_revision_at_the_copywriter(world, ready, fake_team):
    services.request_changes(ready, "Shorter hook, please", new_picture=True)
    ready.refresh_from_db()
    assert ready.revision == 2 and ready.stage == "copy" and ready.status == StudioBrief.Status.QUEUED
    assert ready.regenerate_picture is True

    revised = run_all(ready)
    call = fake_team.calls["copywriter"][-1]
    assert call["feedback"] == "Shorter hook, please" and call["previous"]
    # Still one post: updated in place, still awaiting approval.
    assert Post.objects.filter(studio_briefs=revised).count() == 1
    assert _statuses(revised) == {"pending_review"}
    assert revised.post.versions.count() == 2


def test_changes_need_a_reason_and_an_unapproved_post(world, ready):
    with pytest.raises(services.StudioActionError, match="Say what should change"):
        services.request_changes(ready, "  ")
    with acting_as(world.owner):
        services.approve(ready, world.owner)
    ready.refresh_from_db()
    with pytest.raises(services.StudioActionError, match="can't be revised"):
        services.request_changes(ready, "More energy")


def test_using_another_angle_rewrites_from_scratch(world, ready, fake_team):
    other = ready.concepts.exclude(pk=ready.chosen_concept_id).first()
    services.use_concept(ready, other)
    revised = run_all(ready)
    assert revised.chosen_concept == other
    assert fake_team.calls["copywriter"][-1]["previous"] is None  # a new angle is a fresh draft


def test_new_angles_ask_the_strategist_again(world, ready, fake_team):
    services.new_angles(ready, "More about documents")
    revised = run_all(ready)
    assert len(fake_team.calls["strategist"]) == 2
    assert revised.concepts.filter(revision=2).count() == 3


def test_discard_drops_the_draft_but_never_an_approved_post(world, fake_team):
    brief = run_all(make_brief(world))
    post_id = brief.post_id
    services.discard(brief)
    assert not Post.objects.filter(pk=post_id).exists()
    assert StudioBrief.objects.get(pk=brief.pk).status == StudioBrief.Status.DISCARDED

    approved = run_all(make_brief(world, idea="Another"))
    with acting_as(world.owner):
        services.approve(approved, world.owner)
    approved.refresh_from_db()
    with pytest.raises(services.StudioActionError, match="approved"):
        services.discard(approved)


def test_approval_elsewhere_is_reflected(world, ready):
    from apps.approvals import services as approval_services

    with acting_as(world.owner):
        approval_services.approve_post(ready.post, world.owner, world.workspace)
    services.sync_status(ready)
    assert ready.status == StudioBrief.Status.APPROVED


def test_unused_angles_can_be_kept_as_ideas(world, ready):
    other = ready.concepts.exclude(pk=ready.chosen_concept_id).first()
    idea = services.save_concept_as_idea(other, world.editor)
    assert idea.title == other.title and "ai-studio" in idea.tags
    assert services.save_concept_as_idea(other, world.editor) == idea
    assert Idea.objects.filter(workspace=world.workspace).count() == 1


def test_retry_is_only_for_failed_briefs(world, ready):
    with pytest.raises(services.StudioActionError):
        services.retry(ready)
