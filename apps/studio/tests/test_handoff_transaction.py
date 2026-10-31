"""Handoff publishes one committed review state, with alerts after that commit."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.db import close_old_connections, connection
from django.utils import timezone

from apps.approvals import gate
from apps.approvals import services as approval_services
from apps.approvals.actor import acting_as
from apps.approvals.models import ApprovalAction, ApprovalReminder
from apps.composer.models import PlatformPost, Post
from apps.notifications.models import Notification
from apps.studio import pipeline, services, trust
from apps.studio.models import AgentRun, BrandClaim, StudioBrief
from apps.studio.tests.conftest import make_brief, run_all

pytestmark = pytest.mark.django_db(transaction=True)


def _until_handoff(world):
    brief = make_brief(world, accounts=[world.linkedin, world.x])
    for _ in range(20):
        brief.refresh_from_db()
        if brief.stage == StudioBrief.Stage.HANDOFF:
            return brief
        assert brief.is_active, brief.error
        pipeline.run_step(str(brief.pk), brief.revision, brief.stage)
    raise AssertionError("The team never reached handoff")


def _separate_connection(callback):
    """A real committed-state observer, without inheriting agency contextvars."""

    def observe():
        close_old_connections()
        try:
            # A misplaced notification must fail this regression instead of
            # hanging while its caller holds the handoff's write locks.
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '3s'")
            return callback()
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(observe).result(timeout=5)


def _snapshot(brief_id):
    brief = StudioBrief.objects.get(pk=brief_id)
    return {
        "status": brief.status,
        "stage": brief.stage,
        "post_id": brief.post_id,
        "channels": list(
            PlatformPost.objects.filter(post_id=brief.post_id).order_by("pk").values_list("status", flat=True)
        ),
    }


def test_handoff_never_exposes_ready_with_draft_channels_and_notifies_after_commit(world, fake_team, monkeypatch):
    brief = _until_handoff(world)
    snapshots = {}
    submit = approval_services.submit_for_review
    notify = approval_services._notify_reviewers

    def observe_submission(*args, **kwargs):
        snapshots["before_submission"] = _separate_connection(lambda: _snapshot(brief.pk))
        return submit(*args, **kwargs)

    def observe_notification(*args, **kwargs):
        snapshots["notification_in_transaction"] = connection.in_atomic_block
        snapshots["at_notification"] = _separate_connection(lambda: _snapshot(brief.pk))
        return notify(*args, **kwargs)

    monkeypatch.setattr(approval_services, "submit_for_review", observe_submission)
    monkeypatch.setattr(approval_services, "_notify_reviewers", observe_notification)
    pipeline.run_step(str(brief.pk), brief.revision, brief.stage)

    assert snapshots["before_submission"] == {
        "status": "working",
        "stage": "handoff",
        "post_id": None,
        "channels": [],
    }
    brief.refresh_from_db()
    assert snapshots["at_notification"] == {
        "status": "ready",
        "stage": "done",
        "post_id": brief.post_id,
        "channels": ["pending_review", "pending_review"],
    }
    assert snapshots["notification_in_transaction"] is False
    assert Notification.objects.filter(user=world.owner, title="Post submitted for review").count() == 1
    assert Notification.objects.filter(user=world.editor, title__contains="ready for approval").count() == 1
    assert ApprovalAction.objects.filter(post=brief.post, action="submitted").count() == 1
    assert all(not row.approved_fingerprint and row.scheduled_at is None for row in brief.post.platform_posts.all())


@pytest.mark.parametrize("fail_channel", [1, 2])
def test_submission_failure_rolls_back_and_a_fresh_review_submits_once(world, fake_team, monkeypatch, fail_channel):
    brief = _until_handoff(world)
    transition = approval_services._transition_or_skip
    calls = 0

    def fail_submission(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == fail_channel:
            raise RuntimeError("Injected submission failure")
        return transition(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(approval_services, "_transition_or_skip", fail_submission)
        pipeline.run_step(str(brief.pk), brief.revision, brief.stage)

    brief.refresh_from_db()
    assert brief.status == StudioBrief.Status.FAILED
    assert brief.stage == StudioBrief.Stage.HANDOFF
    assert brief.post_id is None
    assert brief.finished_at is None
    assert not Post.objects.filter(workspace=world.workspace).exists()
    assert not ApprovalAction.objects.exists()
    assert not ApprovalReminder.objects.exists()
    assert not Notification.objects.filter(event_type="post_submitted").exists()
    assert brief.runs.get(agent=AgentRun.Agent.PRODUCER).status == AgentRun.Status.FAILED

    services.retry(brief)
    pipeline.run_step(str(brief.pk), brief.revision, brief.stage)
    brief.refresh_from_db()
    # Retry advances the revision fence, so the old publication review must
    # not be reused. A new review through the existing revision flow is needed.
    assert brief.status == StudioBrief.Status.FAILED
    assert "changed after review or have no current clear review" in brief.error
    assert brief.post_id is None
    assert not Notification.objects.filter(event_type="post_submitted").exists()
    services.request_changes(brief, "Review the post again before sending it for approval.")
    brief = run_all(brief)
    assert brief.status == StudioBrief.Status.READY, brief.error
    assert list(brief.post.platform_posts.values_list("status", flat=True)) == ["pending_review", "pending_review"]
    assert Post.objects.filter(workspace=world.workspace).count() == 1
    assert ApprovalAction.objects.filter(post=brief.post, action="submitted").count() == 1
    assert Notification.objects.filter(user=world.owner, title="Post submitted for review").count() == 1


@pytest.mark.parametrize("skip_channel", [1, 2])
def test_an_unmoved_channel_cannot_leave_a_partially_submitted_ready_brief(world, fake_team, monkeypatch, skip_channel):
    brief = _until_handoff(world)
    transition = approval_services._transition_or_skip
    calls = 0

    def skip_submission(*args, **kwargs):
        nonlocal calls
        calls += 1
        return False if calls == skip_channel else transition(*args, **kwargs)

    monkeypatch.setattr(approval_services, "_transition_or_skip", skip_submission)
    pipeline.run_step(str(brief.pk), brief.revision, brief.stage)
    brief.refresh_from_db()
    assert brief.status == StudioBrief.Status.FAILED
    assert brief.stage == StudioBrief.Stage.HANDOFF
    assert brief.post_id is None
    assert not Post.objects.filter(workspace=world.workspace).exists()
    assert not ApprovalAction.objects.exists()
    assert not ApprovalReminder.objects.exists()
    assert not Notification.objects.filter(event_type="post_submitted").exists()


@pytest.mark.parametrize("interruption", ["discard", "new_revision"])
def test_handoff_rechecks_revision_and_discard_before_writing(world, fake_team, monkeypatch, interruption):
    brief = _until_handoff(world)
    begin = pipeline._begin

    def interrupt_before_handoff_transaction(*args, **kwargs):
        current = StudioBrief.objects.get(pk=brief.pk)
        if interruption == "discard":
            services.discard(current)
        else:
            StudioBrief.objects.filter(pk=brief.pk).update(
                revision=brief.revision + 1, status="queued", stage="strategy"
            )
        return begin(*args, **kwargs)

    monkeypatch.setattr(pipeline, "_begin", interrupt_before_handoff_transaction)
    pipeline.run_step(str(brief.pk), brief.revision, brief.stage)
    brief.refresh_from_db()
    assert brief.status == ("discarded" if interruption == "discard" else "queued")
    assert brief.post_id is None
    assert not Post.objects.filter(workspace=world.workspace).exists()
    assert not ApprovalAction.objects.exists()
    assert not Notification.objects.filter(event_type="post_submitted").exists()
    assert brief.runs.get(agent=AgentRun.Agent.PRODUCER).status == AgentRun.Status.SKIPPED


@pytest.mark.parametrize("invalidate_claim", [False, True])
def test_human_review_during_notification_keeps_trust_checks_and_the_humans_decision(
    world, fake_team, monkeypatch, invalidate_claim
):
    world.workspace.require_dashboard_approval = True
    world.workspace.save(update_fields=["require_dashboard_approval"])
    claim = BrandClaim.objects.create(
        workspace=world.workspace,
        category="availability",
        claim="The owner confirmed two available units.",
        source_note="Owner inventory sheet.",
        verified_by=world.owner,
        verified_at=timezone.now(),
        valid_until=trust.local_date(world.workspace) + timedelta(days=7),
    )
    brief = _until_handoff(world)
    decisions = []

    def human_review():
        current = StudioBrief.objects.select_related("post", "workspace").get(pk=brief.pk)
        if invalidate_claim:
            BrandClaim.objects.filter(pk=claim.pk).update(is_active=False)
        with acting_as(world.owner):
            moved = approval_services.approve_post(current.post, world.owner, world.workspace)
        services.sync_status(current)
        return bool(moved)

    def review_when_notified(*args, **kwargs):
        decisions.append(_separate_connection(human_review))

    monkeypatch.setattr(approval_services, "_notify_reviewers", review_when_notified)
    pipeline.run_step(str(brief.pk), brief.revision, brief.stage)
    brief.refresh_from_db()
    rows = list(brief.post.platform_posts.select_related("post", "social_account"))
    assert decisions == [not invalidate_claim]
    assert brief.status == ("ready" if invalidate_claim else "approved")
    assert all(row.status == ("pending_review" if invalidate_claim else "approved") for row in rows)
    assert all(row.scheduled_at is None for row in rows)
    if invalidate_claim:
        assert all(not row.approved_fingerprint for row in rows)
    else:
        assert all(row.approved_fingerprint == gate.fingerprint(row) for row in rows)
        assert all(row.approved_by_id == world.owner.pk for row in rows)
        assert all(row.approved_publish_at == brief.proposed_publish_at for row in rows)
