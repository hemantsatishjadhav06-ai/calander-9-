"""Real Neopolis planning/feed/recovery paths, with paid providers replaced by fakes."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from threading import Barrier
from time import sleep
from zoneinfo import ZoneInfo

import pytest
import time_machine
from django.db import close_old_connections
from django.utils import timezone

from apps.composer.models import PlatformPost
from apps.studio import autopilot, budget, engine, pipeline, services
from apps.studio.models import AgencyJob, AgencySettings, AutopilotWeek, StudioBrief
from apps.studio.tests.conftest import make_brief, run_all
from apps.studio.tests.test_insights import agency_settings, drive, install_fake_agency, overspend

pytestmark = pytest.mark.django_db(transaction=True)
FRIDAY = datetime(2026, 10, 16, 17, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
MONDAY = date(2026, 10, 19)


@pytest.fixture(autouse=True)
def at_the_friday_tick():
    """Every test runs at FRIDAY, so MONDAY's week is still ahead of the clock whatever today's date is."""
    with time_machine.travel(FRIDAY):
        yield


@pytest.fixture
def agency(monkeypatch):
    return install_fake_agency(monkeypatch)


def prepared_week(world, row, *, manual=False):
    outcome = autopilot.plan_week(row, autopilot.next_week_start(world.workspace), manual=manual)
    assert outcome.started, outcome.message
    job = drive(outcome.week.job)
    assert job.status == AgencyJob.Status.DONE, job.error
    return outcome.week, job


def test_off_switch_preserves_the_week_and_reenable_finishes_only_unapproved_drafts(world, agency, fake_team):
    row = agency_settings(world, posts_per_week=3)
    week, job = prepared_week(world, row)
    AgencySettings.objects.filter(pk=row.pk).update(autopilot_enabled=False)

    assert autopilot.feed_planned_briefs() == 0
    assert StudioBrief.objects.filter(job=job, status="planned").count() == 3
    assert not PlatformPost.objects.exists()

    AgencySettings.objects.filter(pk=row.pk).update(autopilot_enabled=True)
    while autopilot.feed_planned_briefs():
        for brief in StudioBrief.objects.filter(job=job, status__in=StudioBrief.ACTIVE_STATUSES):
            run_all(brief)
    assert StudioBrief.objects.filter(job=job, status="ready").count() == 3
    assert set(PlatformPost.objects.values_list("status", flat=True)) == {"pending_review"}
    assert not PlatformPost.objects.filter(scheduled_at__isnull=False).exists()
    assert autopilot.announce_planned_weeks() == 1
    assert autopilot.announce_planned_weeks() == 0
    assert autopilot.feed_planned_briefs() == 0
    assert AgencyJob.objects.filter(kind="plan").count() == 1
    week.refresh_from_db()
    assert week.status == "planned"


def test_explicit_manual_plan_can_prepare_drafts_while_recurring_autopilot_is_off(world, agency):
    row = agency_settings(world, autopilot_enabled=False, posts_per_week=2)
    _, job = prepared_week(world, row, manual=True)
    assert job.input["manual"] is True
    assert autopilot.feed_planned_briefs() == 2
    assert not PlatformPost.objects.exists()


def test_off_switch_is_rechecked_when_the_tick_holds_a_stale_settings_instance(world, agency):
    row = agency_settings(world)
    AgencySettings.objects.filter(pk=row.pk).update(autopilot_enabled=False)
    outcome = autopilot.plan_week(row, MONDAY)
    assert not outcome.started and "paused" in outcome.message
    assert not AgencyJob.objects.filter(kind="plan").exists()
    assert not AutopilotWeek.objects.exists()


def test_a_queued_plan_pauses_without_model_work_and_resumes_its_same_stage_once(world, agency):
    row = agency_settings(world)
    outcome = autopilot.plan_week(row, MONDAY)
    job = outcome.week.job
    AgencySettings.objects.filter(pk=row.pk).update(autopilot_enabled=False)
    engine.run_step(str(job.pk), job.revision, job.stage)
    job.refresh_from_db()
    assert job.status == "queued" and job.error == autopilot.AUTOPILOT_PAUSED
    assert job.stage == "listen" and job.revision == 1 and not job.runs.exists()
    assert autopilot.resume_paused_jobs() == 0

    AgencySettings.objects.filter(pk=row.pk).update(autopilot_enabled=True)
    assert autopilot.resume_paused_jobs() == 1
    assert autopilot.resume_paused_jobs() == 0
    assert drive(job).status == "done"
    assert len(agency.calls["planner"]) == 1
    assert AgencyJob.objects.filter(kind="plan").count() == 1
    assert not PlatformPost.objects.exists()


def test_a_partly_generated_automatic_draft_resumes_without_rebilling_finished_stages(world, agency, fake_team):
    row = agency_settings(world, posts_per_week=2)
    _, job = prepared_week(world, row)
    assert autopilot.feed_planned_briefs() == 2
    first, second = list(StudioBrief.objects.filter(job=job).order_by("created_at"))
    pipeline.run_step(str(first.pk), first.revision, "strategy")
    first.refresh_from_db()
    assert first.stage == "copy" and len(fake_team.calls["strategist"]) == 1
    AgencySettings.objects.filter(pk=row.pk).update(autopilot_enabled=False)
    pipeline.run_step(str(first.pk), first.revision, "copy")
    pipeline.run_step(str(second.pk), second.revision, "strategy")
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.error == second.error == autopilot.AUTOPILOT_PAUSED
    assert first.stage == "copy" and second.stage == "strategy"
    assert fake_team.calls["copywriter"] == []
    assert autopilot.feed_planned_briefs() == 0

    AgencySettings.objects.filter(pk=row.pk).update(autopilot_enabled=True)
    assert autopilot.feed_planned_briefs() == 2
    assert autopilot.feed_planned_briefs() == 0
    run_all(first)
    run_all(second)
    assert len(fake_team.calls["strategist"]) == 2
    assert len(fake_team.calls["copywriter"]) == 2
    assert set(PlatformPost.objects.values_list("status", flat=True)) == {"pending_review"}
    assert not PlatformPost.objects.filter(scheduled_at__isnull=False).exists()


@pytest.mark.parametrize("pause", ["archive", "deletion_requested_at", "deleted_at"])
def test_manual_plan_and_feeding_stop_for_archived_or_deleting_neopolis(world, agency, pause):
    row = agency_settings(world, posts_per_week=1)
    _, job = prepared_week(world, row)
    if pause == "archive":
        world.workspace.is_archived = True
        world.workspace.save(update_fields=["is_archived"])
    else:
        setattr(world.org, pause, timezone.now())
        world.org.save(update_fields=[pause])
    assert autopilot.feed_planned_briefs() == 0
    assert not autopilot.plan_week(row, MONDAY + timedelta(days=7), manual=True).started
    assert StudioBrief.objects.get(job=job).status == "planned"
    assert not PlatformPost.objects.exists()


@pytest.mark.parametrize("blocker", ["lead", "accounts", "budget"])
def test_a_skipped_week_recovers_once_after_its_configuration_is_fixed(world, agency, blocker):
    row = agency_settings(world, monthly_budget_usd=5)
    if blocker == "lead":
        row.lead = world.editor
        row.save(update_fields=["lead"])
    elif blocker == "accounts":
        row.accounts.clear()
    else:
        overspend(world.workspace)
    assert autopilot.plan_due_workspaces(now=FRIDAY) == 0
    week = AutopilotWeek.objects.get()
    assert week.status == "skipped" and week.job_id is None
    assert autopilot.plan_due_workspaces(now=FRIDAY) == 0
    assert not AgencyJob.objects.filter(kind="plan").exists()
    row.lead = world.owner
    row.monthly_budget_usd = 600
    row.save(update_fields=["lead", "monthly_budget_usd"])
    row.accounts.set([world.linkedin])

    assert autopilot.plan_due_workspaces(now=FRIDAY) == 1
    assert autopilot.plan_due_workspaces(now=FRIDAY) == 0
    week.refresh_from_db()
    assert week.status == "planning" and week.note == ""
    assert week.job.input["manual"] is False
    assert AgencyJob.objects.filter(kind="plan").count() == 1


def test_a_failed_paid_plan_is_never_automatically_rebilled(world, agency):
    row = agency_settings(world)
    agency.fail = {"planner": "The provider is temporarily unavailable."}
    outcome = autopilot.plan_week(row, MONDAY)
    assert drive(outcome.week.job).status == "failed"
    autopilot.announce_planned_weeks()
    agency.fail = {}
    assert autopilot.plan_due_workspaces(now=FRIDAY) == 0
    assert autopilot.plan_due_workspaces(now=FRIDAY) == 0
    assert len(agency.calls["planner"]) == 1
    assert AgencyJob.objects.filter(kind="plan").count() == 1


@pytest.mark.parametrize("parent_status", ["queued", "working", "failed"])
def test_partial_plan_outputs_are_not_fed_before_the_parent_completes(world, agency, parent_status):
    agency_settings(world)
    job = AgencyJob.objects.create(workspace=world.workspace, kind="plan", status=parent_status)
    brief = make_brief(world, job=job, start=False, origin=StudioBrief.Origin.AUTOPILOT)
    assert autopilot.feed_planned_briefs() == 0
    brief.refresh_from_db()
    assert brief.status == "planned" and not PlatformPost.objects.exists()


def test_a_real_partial_plan_failure_stays_unfed_and_can_be_replaced_before_paid_drafting(world, agency, monkeypatch):
    row = agency_settings(world, posts_per_week=3)
    original = services.create_brief
    made = []

    def interrupted(*args, **kwargs):
        if made:
            raise RuntimeError("The worker stopped after the first committed planned brief.")
        brief = original(*args, **kwargs)
        made.append(brief)
        return brief

    monkeypatch.setattr(services, "create_brief", interrupted)
    first = autopilot.plan_week(row, MONDAY)
    old_job = drive(first.week.job)
    assert old_job.status == "failed" and len(made) == 1
    assert autopilot.feed_planned_briefs() == 0
    autopilot.announce_planned_weeks()
    monkeypatch.setattr(services, "create_brief", original)
    replacement = autopilot.plan_week(row, MONDAY, manual=True)
    assert replacement.started and replacement.week.job_id != old_job.pk
    old_job.refresh_from_db()
    made[0].refresh_from_db()
    assert old_job.status == "cancelled" and made[0].status == "discarded"
    assert not PlatformPost.objects.exists()


def test_a_blocked_manual_replan_cannot_discard_the_old_partial_output(world, agency, monkeypatch):
    row = agency_settings(world)
    job = AgencyJob.objects.create(workspace=world.workspace, kind="plan", status="failed")
    week = AutopilotWeek.objects.create(workspace=world.workspace, week_start=MONDAY, status="failed", job=job)
    leftover = make_brief(world, job=job, start=False, origin=StudioBrief.Origin.AUTOPILOT)
    monkeypatch.setattr(budget, "can_spend", lambda workspace: False)
    assert not autopilot.plan_week(row, MONDAY, manual=True).started
    job.refresh_from_db()
    week.refresh_from_db()
    leftover.refresh_from_db()
    assert job.status == "failed" and week.job_id == job.pk and leftover.status == "planned"


def test_a_partial_week_is_not_announced_complete_and_replan_cannot_duplicate_its_ready_post(world, agency, fake_team):
    row = agency_settings(world, posts_per_week=2)
    week, job = prepared_week(world, row)
    assert autopilot.feed_planned_briefs() == 2
    first, second = list(StudioBrief.objects.filter(job=job).order_by("created_at"))
    first = run_all(first)
    StudioBrief.objects.filter(pk=second.pk).update(status="failed", error="A recoverable image failure.")
    assert autopilot.announce_planned_weeks() == 0
    week.refresh_from_db()
    assert week.status == "failed" and "1 of 2" in week.note
    outcome = autopilot.plan_week(row, week.week_start, manual=True)
    assert not outcome.started and "Retry or revise" in outcome.message
    assert AgencyJob.objects.filter(kind="plan").count() == 1
    assert PlatformPost.objects.count() == 1
    assert not PlatformPost.objects.filter(scheduled_at__isnull=False).exists()

    second.refresh_from_db()
    services.retry(second)
    run_all(second)
    assert autopilot.announce_planned_weeks() == 1
    assert autopilot.announce_planned_weeks() == 0
    week.refresh_from_db()
    assert week.status == "planned" and week.note == ""
    assert set(PlatformPost.objects.values_list("status", flat=True)) == {"pending_review"}


def test_deduplicated_planner_output_cannot_announce_a_short_week_complete(world, agency, fake_team, monkeypatch):
    row = agency_settings(world, posts_per_week=7)
    ideas = [
        "Explain landlord shares to first-time buyers, simply",
        "Show the Kokapet site at dusk and what changed this month",
        "Answer when possession of Tower B is expected, from the facts",
    ]
    agency.ideas = [
        {
            "idea": idea,
            "pillar": "Explainers",
            "goal": "education",
            "angle_notes": "Lead with the question.",
            "why_now": "evergreen",
            "accounts": ["a1"],
            "slot": "",
        }
        for idea in ideas + ideas + ideas[:1]
    ]
    week, job = prepared_week(world, row)
    assert job.input["posts"] == 7 and len(agency.calls["planner"]) == 1
    assert StudioBrief.objects.filter(job=job).count() == 3
    # Changing the next week's quota must not make this shortfall disappear.
    AgencySettings.objects.filter(pk=row.pk).update(posts_per_week=3)
    while autopilot.feed_planned_briefs():
        for brief in StudioBrief.objects.filter(job=job, status__in=StudioBrief.ACTIVE_STATUSES):
            run_all(brief)
    announced = []
    monkeypatch.setattr(autopilot, "notify_week_ready", lambda *args: announced.append(args))
    assert autopilot.announce_planned_weeks() == 0
    assert autopilot.announce_planned_weeks() == 0
    week.refresh_from_db()
    assert week.status == "failed" and "3 of 7" in week.note and "4 were not prepared" in week.note
    assert announced == []
    assert len(agency.calls["planner"]) == 1 and AgencyJob.objects.filter(kind="plan").count() == 1
    assert set(PlatformPost.objects.values_list("status", flat=True)) == {"pending_review"}
    assert not PlatformPost.objects.filter(scheduled_at__isnull=False).exists()


def test_an_over_budget_backlog_cannot_hide_neopolis_behind_the_candidate_bound(world, agency):
    from apps.workspaces.models import Workspace

    row = agency_settings(world)
    blocked = Workspace.objects.create(organization=world.org, name="Paused-budget brand")
    AgencySettings.objects.create(workspace=blocked, autopilot_enabled=True, lead=world.owner, monthly_budget_usd=0)
    for index in range(101):
        services.create_brief(
            blocked,
            world.owner,
            idea=f"Blocked draft {index}",
            start=False,
            origin=StudioBrief.Origin.AUTOPILOT,
            proposed_publish_at=timezone.now() + timedelta(hours=1),
        )
    services.create_brief(
        world.workspace,
        world.owner,
        idea="Neopolis current brand facts",
        accounts=[world.linkedin],
        start=False,
        origin=StudioBrief.Origin.AUTOPILOT,
        proposed_publish_at=timezone.now() + timedelta(days=1),
    )
    assert row.autopilot_enabled
    assert autopilot.feed_planned_briefs() == 1
    assert StudioBrief.objects.filter(workspace=world.workspace, status="queued").count() == 1
    assert StudioBrief.objects.filter(workspace=blocked, status="planned").count() == 101


def test_concurrent_cycles_cannot_claim_different_briefs_past_the_global_cap(world, agency, settings, monkeypatch):
    agency_settings(world)
    settings.AGENCY_MAX_ACTIVE_BRIEFS = 1
    for index in range(6):
        make_brief(world, idea=f"Neopolis feed race {index}", start=False, origin=StudioBrief.Origin.AUTOPILOT)
    original = services.start_planned

    def slow_claim(brief):
        # Both old feeder instances could read the same empty active count
        # before trying different conditional brief claims.
        sleep(0.04)
        return original(brief)

    monkeypatch.setattr(services, "start_planned", slow_claim)
    ready = Barrier(2)

    def feed():
        close_old_connections()
        try:
            ready.wait(timeout=5)
            return autopilot.feed_planned_briefs()
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(feed) for _ in range(2)]
        assert sum(future.result(timeout=10) for future in futures) == 1
    assert StudioBrief.objects.filter(status__in=StudioBrief.ACTIVE_STATUSES).count() == 1
    assert not PlatformPost.objects.exists()
