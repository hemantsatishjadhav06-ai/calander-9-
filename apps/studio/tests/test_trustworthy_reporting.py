"""Operational truth, fresh creative evidence and date/tenant-safe campaign outcomes."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.analytics.models import PostInsightsSnapshot
from apps.approvals.models import ApprovalAction
from apps.composer.models import PlatformPost, Post
from apps.studio import engine, memory, performance, reports
from apps.studio.jobtypes import report
from apps.studio.models import AgencyJob, AutopilotWeek, CampaignOutcome, CreativeInsight, StudioBrief
from apps.studio.tests.test_insights import drive, install_fake_agency, published_post
from apps.workspaces.models import Workspace


@pytest.fixture
def agency(monkeypatch):
    return install_fake_agency(monkeypatch)


def test_report_does_not_hide_failed_work_or_an_approval_backlog_as_a_quiet_week(world, agency):
    post = Post.objects.create(workspace=world.workspace, caption="Waiting for owner review")
    PlatformPost.objects.create(post=post, social_account=world.linkedin, status="pending_review")
    StudioBrief.objects.create(
        workspace=world.workspace,
        author=world.owner,
        idea="A failed draft",
        status="failed",
        finished_at=timezone.now(),
    )
    AgencyJob.objects.create(
        workspace=world.workspace, kind="plan", status="failed", finished_at=timezone.now(), error="PRIVATE-MODEL-ERROR"
    )
    AutopilotWeek.objects.create(
        workspace=world.workspace, week_start=timezone.now().date(), status="skipped", note="PRIVATE-PLAN-NOTE"
    )

    job = drive(engine.create(world.workspace, "report"))

    assert job.status == "done", job.error
    assert not job.result["summary"].startswith("A quiet week")
    assert job.result["operations"]["awaiting_approval"] == 1
    assert job.result["operations"]["failed"] == 1
    assert job.result["operations"]["job_failures"] == 1
    assert job.result["operations"]["paused_weeks"] == 1
    visible = reports.latest_report(world.workspace)
    assert "PRIVATE-" not in str(visible)
    assert "Failed, held or paused" in visible["summary"]


def test_operational_period_snapshot_excludes_foreign_content_and_future_activity(world):
    now = timezone.now()
    start, end = now - timedelta(days=14), now - timedelta(days=7)
    inside = start + timedelta(days=1)
    post = Post.objects.create(workspace=world.workspace, caption="Period content")
    Post.objects.filter(pk=post.pk).update(created_at=inside)
    PlatformPost.objects.create(post=post, social_account=world.linkedin, status="failed", scheduled_at=inside)
    ApprovalAction.objects.create(post=post, action="publish_blocked", comment="PRIVATE-TOKEN")
    ApprovalAction.objects.filter(post=post).update(created_at=inside)
    current = Post.objects.create(workspace=world.workspace, caption="Future to that report")
    PlatformPost.objects.create(post=current, social_account=world.linkedin, status="pending_review")
    other = Workspace.objects.create(organization=world.org, name="More Space")
    foreign = Post.objects.create(workspace=other, caption="FOREIGN-PRIVATE")
    Post.objects.filter(pk=foreign.pk).update(created_at=inside)
    PlatformPost.objects.create(post=foreign, social_account=world.linkedin, status="published", published_at=inside)

    facts = report.report_facts(world.workspace, start, end)

    assert facts["operations"]["requested"] == 1
    assert facts["operations"]["prepared"] == 1
    assert facts["operations"]["failed"] == 1 and facts["operations"]["blocked"] == 1
    assert facts["operations"]["awaiting_approval"] == 0
    assert facts["went_out"] == {}
    assert "FOREIGN" not in report.facts_text(facts, "Historical week")


def test_old_unapproved_content_is_visible_as_current_backlog_without_rewriting_historical_counts(world, agency):
    now = timezone.now()
    post = Post.objects.create(workspace=world.workspace, caption="An old draft awaiting review")
    Post.objects.filter(pk=post.pk).update(created_at=now - timedelta(days=60))
    PlatformPost.objects.create(post=post, social_account=world.linkedin, status="pending_review")
    week = now.date() - timedelta(days=now.weekday() + 14)
    job = drive(engine.create(world.workspace, "report", input={"week_start": week.isoformat()}))
    assert job.status == "done", job.error
    assert job.result["operations"]["awaiting_approval"] == 0
    assert job.result["current_backlog"]["awaiting_approval"] == 1
    assert "Current backlog" in job.result["summary"] and not job.result["summary"].startswith("A quiet week")


def test_fresh_metric_snapshot_uses_the_workspace_day_after_utc_midnight_boundary(world):
    cutoff = datetime(2026, 10, 12, 19, tzinfo=UTC)
    post = Post.objects.create(workspace=world.workspace, caption="A measured post")
    pp = PlatformPost.objects.create(
        post=post, social_account=world.linkedin, status="published", published_at=cutoff - timedelta(days=5)
    )
    snapshot = PostInsightsSnapshot.objects.create(
        platform_post=pp, metric_key="engagement", date=cutoff.astimezone(ZoneInfo("Asia/Kolkata")).date(), value=9
    )
    PostInsightsSnapshot.objects.filter(pk=snapshot.pk).update(captured_at=cutoff - timedelta(minutes=5))
    assert performance.measured(workspace=world.workspace, now=cutoff)[0].value == 9


@pytest.mark.parametrize(
    ("age", "history", "expected"),
    [(1, False, "younger than three"), (5, False, "at least five"), (5, True, "within seven days")],
)
def test_missing_performance_explains_actual_maturity_history_or_freshness(world, age, history, expected):
    pp = published_post(world, world.linkedin, days_ago=age, value=8)
    if history:
        PostInsightsSnapshot.objects.filter(platform_post=pp).update(captured_at=timezone.now() - timedelta(days=8))
    facts = report.report_facts(world.workspace, timezone.now() - timedelta(days=7), timezone.now())
    assert expected in facts["performance_note"]


def test_historical_performance_does_not_use_metrics_captured_after_the_cutoff(world):
    for number in range(6):
        published_post(world, world.linkedin, days_ago=20 + number, value=number + 1)
    end = timezone.now() - timedelta(days=10)
    assert performance.measured(workspace=world.workspace, now=end) == []


def test_stale_analytics_cannot_be_winners_but_chosen_designer_references_survive(world, photo, agency):
    for number in range(6):
        pp = published_post(world, world.linkedin, days_ago=5 + number, value=number + 1)
        CreativeInsight.objects.create(
            workspace=world.workspace,
            platform_post=pp,
            post=pp.post,
            media_asset=photo(),
            score=0.9,
            ratio=4,
            is_reference=number == 0,
            description="Owner's chosen visual direction",
        )
    assert len(memory.best_performers(world.workspace)) == 5
    PostInsightsSnapshot.objects.update(captured_at=timezone.now() - timedelta(days=8))
    assert performance.measured(workspace=world.workspace) == []
    assert memory.best_performers(world.workspace) == []
    assert len(memory.references(world.workspace)) == 1
    assert memory.learning_set(world.workspace)[0].is_reference
    job = drive(engine.create(world.workspace, "learn"))
    assert job.status == "done", job.error
    assert CreativeInsight.objects.filter(is_reference=True).exists()
    assert not CreativeInsight.objects.filter(score__isnull=False).exists()


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), -1.0])
def test_invalid_metric_values_do_not_create_performance_claims(world, bad_value):
    pp = published_post(world, world.linkedin, days_ago=5, value=bad_value)
    assert not performance.fresh_post_stats([pp.pk], ["engagement"])


def test_failed_metric_capture_is_not_a_successful_performance_result(world):
    pp = published_post(world, world.linkedin, days_ago=5, value=7)
    PostInsightsSnapshot.objects.filter(platform_post=pp).update(errors={"request": "PRIVATE-PROVIDER-ERROR"})
    assert performance.measured(workspace=world.workspace) == []


def test_manual_outcomes_use_the_local_report_dates_and_do_not_infer_unique_leads(world, agency):
    zone = report.zone_of(world.workspace)
    today = timezone.now().astimezone(zone).date()
    week_start = today - timedelta(days=today.weekday()) - timedelta(days=7)
    for kind, count in [("enquiry", 5), ("qualified_enquiry", 2), ("site_visit", 1)]:
        CampaignOutcome.objects.create(
            workspace=world.workspace,
            campaign_name="Site visits",
            occurred_on=week_start,
            kind=kind,
            count=count,
            recorded_by=world.editor,
        )
    CampaignOutcome.objects.create(
        workspace=world.workspace,
        campaign_name="Outside week",
        occurred_on=week_start + timedelta(days=7),
        kind="enquiry",
        count=100,
    )
    other = Workspace.objects.create(organization=world.org, name="More Space")
    CampaignOutcome.objects.create(
        workspace=other, campaign_name="FOREIGN", occurred_on=week_start, kind="enquiry", count=200
    )
    job = drive(engine.create(world.workspace, "report", input={"week_start": week_start.isoformat()}))
    assert job.status == "done", job.error
    visible = reports.latest_report(world.workspace)
    assert visible["outcomes"] == {"enquiry": 5, "qualified_enquiry": 2, "site_visit": 1}
    assert "not unique people" in visible["outcome_note"]
    assert not visible["summary"].startswith("A quiet week")
    assert "FOREIGN" not in str(visible)
    assert job.result["period"]["start"] == week_start.isoformat()


def test_legacy_report_has_no_fabricated_new_operational_history(world):
    job = AgencyJob.objects.create(
        workspace=world.workspace,
        kind="report",
        status="done",
        result={"title": "Old report", "went_out": {"Facebook": 1}, "sections": []},
    )
    assert "operations" not in reports.client_safe(job)
    assert "outcomes" not in reports.client_safe(job)


def test_report_read_side_exposes_only_allowlisted_counts(world):
    job = AgencyJob.objects.create(
        workspace=world.workspace,
        kind="report",
        status="done",
        result={
            "title": "Report",
            "operations": {"requested": 2, "secret": "PRIVATE", "failed": True, "blocked": -1},
            "outcomes": {"enquiry": 3, "contact": "PRIVATE", "site_visit": False},
            "cost": "PRIVATE",
        },
    )
    visible = reports.client_safe(job)
    assert visible["operations"] == {"requested": 2}
    assert visible["outcomes"] == {"enquiry": 3}
    assert "PRIVATE" not in str(visible)


def test_report_card_shows_operational_counts_and_manual_outcome_definition(world, client, agency):
    CampaignOutcome.objects.create(
        workspace=world.workspace,
        campaign_name="Buyer questions",
        occurred_on=timezone.now().date(),
        kind="enquiry",
        count=1,
    )
    job = drive(engine.create(world.workspace, "report"))
    assert job.status == "done", job.error
    client.force_login(world.owner)
    response = client.get(reverse("studio:autopilot", kwargs={"workspace_id": world.workspace.pk}))
    assert response.status_code == 200
    html = response.content.decode()
    assert "Awaiting approval" in html and "Recorded campaign outcomes" in html
    assert "not unique people" in html
