from datetime import UTC, date, datetime, timedelta

import pytest
from django.utils import timezone

from apps.composer.models import PlatformPost, Post
from apps.publisher import delivery
from apps.studio import pipeline, scheduling, services
from apps.studio.jobtypes import plan
from apps.studio.models import AgentRun, StudioBrief
from apps.studio.tests.conftest import make_brief


def _scheduled(world, account, when):
    post = Post.objects.create(workspace=world.workspace, author=world.owner, caption="Retain this existing post")
    return PlatformPost.objects.create(post=post, social_account=account, status="scheduled", scheduled_at=when)


def test_no_slot_fallback_honors_the_requested_week(world, monkeypatch):
    now = datetime(2026, 10, 13, 4, 30, tzinfo=UTC)
    monkeypatch.setattr(scheduling.timezone, "now", lambda: now)
    monkeypatch.setattr("apps.calendar.services._next_slot_datetimes", lambda *_args, **_kwargs: [])
    start, end = plan.week_window(world.workspace, date(2026, 10, 19))
    proposed = scheduling.propose(world.workspace, [world.linkedin], after=start)
    assert start <= proposed.when < end
    assert proposed.when.astimezone(plan.zone_of(world.workspace)).hour == 10


def test_a_slot_must_be_free_on_every_selected_destination(world, monkeypatch):
    first = timezone.now() + timedelta(days=2)
    second = first + timedelta(hours=1)
    _scheduled(world, world.x, first)
    monkeypatch.setattr("apps.calendar.services._next_slot_datetimes", lambda *_args, **_kwargs: [first, second])
    proposed = scheduling.propose(world.workspace, [world.linkedin, world.x])
    assert proposed.when == second


def test_no_slot_fallback_skips_existing_scheduled_posts(world, monkeypatch):
    now = datetime(2026, 10, 13, 2, 30, tzinfo=UTC)
    monkeypatch.setattr(scheduling.timezone, "now", lambda: now)
    occupied = datetime(2026, 10, 13, 4, 30, tzinfo=UTC)
    _scheduled(world, world.x, occupied)
    monkeypatch.setattr("apps.calendar.services._next_slot_datetimes", lambda *_args, **_kwargs: [])
    proposed = scheduling.propose(world.workspace, [world.linkedin, world.x])
    assert proposed.when > occupied


def test_week_allocator_and_fallback_do_not_collide_with_retained_posts(world, monkeypatch):
    now = datetime(2026, 10, 13, 2, 30, tzinfo=UTC)
    monkeypatch.setattr(scheduling.timezone, "now", lambda: now)
    start, end = plan.week_window(world.workspace, date(2026, 10, 19))
    occupied = start + timedelta(hours=10)
    _scheduled(world, world.x, occupied)
    monkeypatch.setattr(
        scheduling, "propose", lambda *_args, **_kwargs: scheduling.Proposal(occupied, "old suggestion")
    )
    when = plan.allocate(world.workspace, [world.linkedin, world.x], None, start, end, set())
    assert when is not None and start <= when < end and when != occupied


def test_week_fallback_slots_exclude_existing_scheduled_content(world, monkeypatch):
    now = datetime(2026, 10, 13, 2, 30, tzinfo=UTC)
    monkeypatch.setattr(scheduling.timezone, "now", lambda: now)
    start, end = plan.week_window(world.workspace, date(2026, 10, 19))
    occupied = start + timedelta(hours=10)
    _scheduled(world, world.x, occupied)
    monkeypatch.setattr("apps.calendar.services._next_slot_datetimes", lambda *_args, **_kwargs: [])
    slots = plan.open_slots(world.workspace, [world.linkedin, world.x], start, end, limit=4)
    assert slots and occupied not in {when for when, _accounts in slots}


def test_retry_prevents_an_interrupted_paid_callback_overwriting_the_new_execution(world, monkeypatch):
    old = make_brief(world)
    old.status = StudioBrief.Status.WORKING
    old.save(update_fields=["status"])
    source_review = old.trust_snapshot
    StudioBrief.objects.filter(pk=old.pk).update(status=StudioBrief.Status.FAILED)
    queued = []
    monkeypatch.setattr(pipeline, "enqueue", lambda brief, stage: queued.append((brief.revision, stage)))
    retry = StudioBrief.objects.get(pk=old.pk)
    services.retry(retry)
    assert retry.revision == old.revision + 1
    assert retry.trust_snapshot == {**source_review, "revision": retry.revision}
    assert queued == [(retry.revision, "strategy")]
    StudioBrief.objects.filter(pk=retry.pk).update(status=StudioBrief.Status.WORKING, post_copy={"caption": "New turn"})
    with pytest.raises(pipeline._StaleStepError):
        pipeline._save(old, post_copy={"caption": "Obsolete paid answer"})
    retry.refresh_from_db()
    assert retry.post_copy == {"caption": "New turn"}


def test_old_failure_does_not_fail_new_revision_usage_rows(world, monkeypatch):
    old = make_brief(world)
    StudioBrief.objects.filter(pk=old.pk).update(status=StudioBrief.Status.FAILED)
    monkeypatch.setattr(pipeline, "enqueue", lambda *_args: None)
    retry = StudioBrief.objects.get(pk=old.pk)
    services.retry(retry)
    StudioBrief.objects.filter(pk=retry.pk).update(status=StudioBrief.Status.WORKING)
    current_run = AgentRun.objects.create(
        brief=retry, workspace=world.workspace, revision=retry.revision, agent="strategist", status="running"
    )
    pipeline._fail(old, "Old callback failed")
    retry.refresh_from_db()
    current_run.refresh_from_db()
    assert retry.status == StudioBrief.Status.WORKING
    assert current_run.status == AgentRun.Status.RUNNING


def test_retry_rechecks_fresh_status_before_restarting(world, monkeypatch):
    brief = make_brief(world)
    brief.status = StudioBrief.Status.FAILED
    brief.save(update_fields=["status"])
    StudioBrief.objects.filter(pk=brief.pk).update(status=StudioBrief.Status.READY)
    monkeypatch.setattr(pipeline, "enqueue", lambda *_args: pytest.fail("A stale retry queued paid work"))
    with pytest.raises(services.StudioActionError, match="failed"):
        services.retry(brief)
    brief.refresh_from_db()
    assert brief.status == StudioBrief.Status.READY and brief.revision == 1


@pytest.mark.parametrize("kind", ["unknown", "expired"])
@pytest.mark.parametrize("operation", ["discard", "retry"])
def test_unresolved_delivery_evidence_survives_discard_and_retry(world, monkeypatch, kind, operation):
    brief = make_brief(world)
    post = Post.objects.create(workspace=world.workspace, author=world.owner, caption="Recovery evidence")
    row = PlatformPost.objects.create(post=post, social_account=world.linkedin, status="pending_review")
    assert delivery.mark(
        row, kind=kind, reason="Inspect the actual account before any new send", from_status="pending_review"
    )
    brief.post, brief.status = post, StudioBrief.Status.FAILED
    brief.save(update_fields=["post", "status"])
    post.refresh_from_db()
    original_holds = post.delivery_holds
    monkeypatch.setattr(pipeline, "enqueue", lambda *_args: pytest.fail("An unresolved hold queued paid work"))
    with pytest.raises(services.StudioActionError, match="previous delivery"):
        getattr(services, operation)(brief)
    brief.refresh_from_db()
    post.refresh_from_db()
    assert brief.status == StudioBrief.Status.FAILED and brief.post_id == post.pk
    assert post.delivery_holds == original_holds
    assert PlatformPost.objects.filter(pk=row.pk).exists()
