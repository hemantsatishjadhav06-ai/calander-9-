"""The weekly client report: the job, the client-safe read side, and when the cycle writes it."""

from __future__ import annotations

import zoneinfo
from datetime import date, datetime, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.members.models import WorkspaceMembership
from apps.studio import autopilot, engine, reports
from apps.studio.jobtypes import report as report_job
from apps.studio.models import AgencyJob, AgentRun, StudioBrief
from apps.studio.tests.test_insights import (
    agency_settings,
    drive,
    inbox_message,
    install_fake_agency,
    overspend,
    published_post,
)


@pytest.fixture
def agency(monkeypatch):
    return install_fake_agency(monkeypatch)


IST = zoneinfo.ZoneInfo("Asia/Kolkata")


def _url(name, world, **kwargs):
    return reverse(name, kwargs={"workspace_id": world.workspace.id, **kwargs})


def _this_week_start(world) -> date:
    local = timezone.now().astimezone(IST)
    return local.date() - timedelta(days=local.weekday())


def _report(world, week_start=None):
    week_start = week_start or _this_week_start(world) - timedelta(days=7)
    return engine.create(world.workspace, "report", input={"week_start": week_start.isoformat()})


def _week_of_posts(world):
    """Posts published in the last seven days (rolling window) and a planned brief for next week."""
    for n, value in enumerate([1, 2, 3, 4, 5]):
        published_post(world, world.linkedin, days_ago=20 + n, value=value)  # history for the ratio
    best = published_post(world, world.linkedin, days_ago=4, value=10, caption="Same tower. A fairer number.\nmore")
    published_post(world, world.x, days_ago=5, value=1, caption="On X this week")
    StudioBrief.objects.create(
        workspace=world.workspace,
        author=world.owner,
        idea="Site visit Saturday",
        status=StudioBrief.Status.PLANNED,
        proposed_publish_at=timezone.now() + timedelta(days=2),
    )
    return best


def test_the_report_tells_the_week_in_plain_words(world, agency):
    _week_of_posts(world)
    inbox_message(world, "When is possession? Call me on +91 98765 43210", days_ago=2)

    job = drive(engine.create(world.workspace, "report"))  # no week given: the last seven days

    assert job.status == AgencyJob.Status.DONE, job.error
    facts = agency.calls["reporter"][0]["facts"]
    assert "LinkedIn: 1 post(s)" in facts and "X: 1 post(s)" in facts
    assert "did about 2.9× as well as the account's usual post" in facts
    assert '<untrusted source="best_post_opening">\nSame tower. A fairer number.' in facts
    assert "1 post(s) being prepared for next week" in facts
    assert "98765" not in str(agency.calls["audience_listener"][0]["messages"])
    result = job.result
    assert [s["kind"] for s in result["sections"]] == ["went_out", "best", "next"]  # in the house order
    assert result["went_out"] == {"LinkedIn": 1, "X": 1} and result["period"]["label"]
    agents = {run.agent: run.status for run in job.runs.all()}
    assert agents == {"audience_listener": AgentRun.Status.SUCCEEDED, "reporter": AgentRun.Status.SUCCEEDED}


def test_a_quiet_week_is_written_without_the_model(world, agency):
    job = drive(_report(world))

    assert job.status == AgencyJob.Status.DONE
    assert "reporter" not in agency.calls and "audience_listener" not in agency.calls
    assert job.result["summary"].startswith("A quiet week")
    assert job.runs.get(agent="reporter").status == AgentRun.Status.SKIPPED


def test_the_report_refuses_to_start_over_budget(world, agency):
    _week_of_posts(world)
    agency_settings(world, monthly_budget_usd=5)
    overspend(world.workspace)

    job = drive(engine.create(world.workspace, "report"))

    assert job.status == AgencyJob.Status.FAILED and "budget" in job.error
    assert "reporter" not in agency.calls


def test_a_failed_reporter_fails_the_job_with_a_sentence(world, agency):
    _week_of_posts(world)
    agency.fail = {"reporter": "Claude declined this request."}

    job = drive(engine.create(world.workspace, "report"))

    assert job.status == AgencyJob.Status.FAILED and "declined" in job.error
    assert reports.latest_report(world.workspace) is None


def test_the_client_safe_report_has_only_the_reports_own_words(world, agency):
    from apps.workspaces.models import Workspace

    _week_of_posts(world)
    job = drive(engine.create(world.workspace, "report"))
    AgencyJob.objects.filter(pk=job.pk).update(
        result={
            **job.result,
            "sections": [*job.result["sections"], {"kind": "internal", "heading": "Costs", "body": "$4.20"}],
            "cost": 4.2,
        },
        state={"audience": {"summary": "secret"}},
    )
    other_ws = Workspace.objects.create(organization=world.org, name="Other")
    AgencyJob.objects.create(
        workspace=other_ws, kind="report", status="done", result={"title": "Other brand's week", "sections": []}
    )

    report = reports.latest_report(world.workspace)

    assert report["title"] == "Your week on social: 5–11 October"
    assert set(report) == {"id", "title", "summary", "sections", "period", "went_out", "created_at"}
    assert [s["kind"] for s in report["sections"]] == ["went_out", "best", "next"]
    assert "4.2" not in str(report) and "secret" not in str(report)
    assert reports.latest_report(other_ws)["title"] == "Other brand's week"
    assert [r["id"] for r in reports.recent_reports(world.workspace)] == [str(job.pk)]


def test_failed_or_unfinished_reports_are_never_shown(world):
    AgencyJob.objects.create(workspace=world.workspace, kind="report", status="failed", result={"title": "Half"})
    AgencyJob.objects.create(workspace=world.workspace, kind="report", status="working", result={"title": "Busy"})
    AgencyJob.objects.create(workspace=world.workspace, kind="plan", status="done", result={"title": "A plan"})

    assert reports.latest_report(world.workspace) is None


def test_the_week_window_and_label(world):
    job = AgencyJob(workspace=world.workspace, kind="report", input={"week_start": "2026-10-05"})
    start, end = report_job.report_window(job)
    assert start == datetime(2026, 10, 5, tzinfo=IST) and end == datetime(2026, 10, 12, tzinfo=IST)
    assert report_job.period_label(start, end) == "5–11 October"
    assert report_job.period_label(datetime(2026, 9, 28), datetime(2026, 10, 5)) == "28 September – 4 October"


# ---------------------------------------------------------------------------
# When it is written
# ---------------------------------------------------------------------------


def test_the_cycle_writes_last_weeks_report_on_monday_morning_once(world, agency):
    agency_settings(world)
    monday_9 = datetime(2026, 10, 19, 9, 0, tzinfo=IST)

    assert autopilot.queue_weekly_reports(now=datetime(2026, 10, 19, 7, 0, tzinfo=IST)) == 0  # too early
    assert autopilot.queue_weekly_reports(now=datetime(2026, 10, 18, 9, 0, tzinfo=IST)) == 0  # Sunday
    assert autopilot.queue_weekly_reports(now=monday_9) == 1
    assert autopilot.queue_weekly_reports(now=monday_9) == 0
    job = AgencyJob.objects.get(kind="report")
    assert job.input == {"week_start": "2026-10-12"} and job.title == "Weekly report: 12–18 October"

    # A failed report isn't rewritten (and re-billed) by the cycle on its own.
    AgencyJob.objects.filter(pk=job.pk).update(status="failed")
    assert autopilot.queue_weekly_reports(now=monday_9 + timedelta(days=1)) == 0


def test_no_report_without_autopilot_or_over_budget(world, agency):
    monday_9 = datetime(2026, 10, 19, 9, 0, tzinfo=IST)
    row = agency_settings(world, autopilot_enabled=False)
    assert autopilot.queue_weekly_reports(now=monday_9) == 0

    row.autopilot_enabled = True
    row.monthly_budget_usd = 5
    row.save()
    overspend(world.workspace)
    assert autopilot.queue_weekly_reports(now=monday_9) == 0
    assert not AgencyJob.objects.filter(kind="report").exists()


def test_staff_can_ask_for_the_report_now_and_clients_cant(client, world, agency):
    client.force_login(world.editor)

    response = client.post(_url("studio:autopilot_report", world))

    job = AgencyJob.objects.get(kind="report")
    assert response.status_code == 302 and str(job.pk) in response["Location"]
    assert job.requested_by == world.editor
    assert job.input["week_start"] == (_this_week_start(world) - timedelta(days=7)).isoformat()
    client.post(_url("studio:autopilot_report", world))
    assert AgencyJob.objects.filter(kind="report").count() == 1  # one is already being written

    client_user = world.viewer.__class__.objects.create_user(
        email="client@example.com", password="pw-12345678", name="Client", tos_accepted_at=timezone.now()
    )
    WorkspaceMembership.objects.create(user=client_user, workspace=world.workspace, workspace_role="client")
    client.force_login(client_user)
    assert client.post(_url("studio:autopilot_report", world)).status_code == 403


def test_the_autopilot_page_shows_the_latest_report(client, world, agency):
    _week_of_posts(world)
    drive(engine.create(world.workspace, "report"))
    client.force_login(world.owner)

    html = client.get(_url("studio:autopilot", world)).content.decode()

    assert "Your week on social: 5–11 October" in html and "The explainer did best." in html
