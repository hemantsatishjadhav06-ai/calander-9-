"""Autopilot: the weekly tick, feeding planned briefs, telling people, and the settings page."""

from __future__ import annotations

import zoneinfo
from datetime import date, datetime, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.members.models import WorkspaceMembership
from apps.notifications.models import EventType, Notification
from apps.studio import autopilot, services
from apps.studio.models import AgencyJob, AgencySettings, AutopilotWeek, StudioBrief
from apps.studio.tests.conftest import run_all
from apps.studio.tests.test_insights import (
    agency_settings,
    assert_nothing_approved,
    drive,
    install_fake_agency,
    overspend,
)


@pytest.fixture
def agency(monkeypatch):
    return install_fake_agency(monkeypatch)


IST = zoneinfo.ZoneInfo("Asia/Kolkata")
#: A Friday after the plan hour (Friday 16:00 by default), and the Monday it plans for.
FRIDAY_EVENING = datetime(2026, 10, 16, 17, 30, tzinfo=IST)
NEXT_MONDAY = date(2026, 10, 19)


def _url(name, world, **kwargs):
    return reverse(name, kwargs={"workspace_id": world.workspace.id, **kwargs})


def _client_user(world):
    user = world.viewer.__class__.objects.create_user(
        email="client@example.com", password="pw-12345678", name="Client", tos_accepted_at=timezone.now()
    )
    WorkspaceMembership.objects.create(user=user, workspace=world.workspace, workspace_role="client")
    return user


# ---------------------------------------------------------------------------
# The tick
# ---------------------------------------------------------------------------


def test_the_tick_plans_next_week_once(world, agency):
    agency_settings(world)

    assert autopilot.plan_due_workspaces(now=FRIDAY_EVENING) == 1
    assert autopilot.plan_due_workspaces(now=FRIDAY_EVENING) == 0  # a double tick is harmless

    week = AutopilotWeek.objects.get(workspace=world.workspace)
    assert week.week_start == NEXT_MONDAY and week.status == AutopilotWeek.Status.PLANNING
    job = week.job
    assert job.kind == "plan" and job.input["week_start"] == "2026-10-19" and job.input["week_id"] == str(week.pk)
    assert job.requested_by == world.owner and job.input["posts"] == 3


def test_the_tick_waits_for_the_plan_day_and_hour(world, agency):
    agency_settings(world)

    assert autopilot.plan_due_workspaces(now=datetime(2026, 10, 15, 22, 0, tzinfo=IST)) == 0  # Thursday
    assert autopilot.plan_due_workspaces(now=datetime(2026, 10, 16, 15, 59, tzinfo=IST)) == 0  # Friday 15:59
    assert not AutopilotWeek.objects.exists()


def test_the_tick_skips_a_week_it_cant_plan_and_says_why(world, agency):
    row = agency_settings(world, lead=world.editor)  # an editor can't approve

    autopilot.plan_due_workspaces(now=FRIDAY_EVENING)

    week = AutopilotWeek.objects.get(workspace=world.workspace)
    assert week.status == AutopilotWeek.Status.SKIPPED and week.job is None and "no longer" in week.note
    assert not AgencyJob.objects.filter(kind="plan").exists()

    # Nothing to post to.
    AutopilotWeek.objects.all().delete()
    row.lead = world.owner
    row.save()
    row.accounts.clear()
    autopilot.plan_due_workspaces(now=FRIDAY_EVENING)
    assert "None of the autopilot accounts" in AutopilotWeek.objects.get().note


def test_the_tick_skips_over_budget(world, agency):
    agency_settings(world, monthly_budget_usd=5)
    overspend(world.workspace)

    autopilot.plan_due_workspaces(now=FRIDAY_EVENING)

    week = AutopilotWeek.objects.get()
    assert week.status == AutopilotWeek.Status.SKIPPED and "budget" in week.note


def test_the_tick_leaves_archived_deleting_and_switched_off_workspaces_alone(world, agency):
    from apps.organizations.models import Organization

    row = agency_settings(world, autopilot_enabled=False)
    assert autopilot.plan_due_workspaces(now=FRIDAY_EVENING) == 0

    row.autopilot_enabled = True
    row.save()
    world.workspace.is_archived = True
    world.workspace.save(update_fields=["is_archived"])
    assert autopilot.plan_due_workspaces(now=FRIDAY_EVENING) == 0

    world.workspace.is_archived = False
    world.workspace.save(update_fields=["is_archived"])
    Organization.objects.filter(pk=world.org.pk).update(deletion_requested_at=timezone.now())
    assert autopilot.plan_due_workspaces(now=FRIDAY_EVENING) == 0
    assert not AutopilotWeek.objects.exists()


def test_the_cycle_runs_every_part_and_survives_a_broken_one(world, monkeypatch):
    def broken():
        raise RuntimeError("boom")

    monkeypatch.setattr(autopilot, "feed_planned_briefs", broken)

    done = autopilot.run_cycle()

    assert set(done) == set(autopilot.PARTS) and done["feed_planned_briefs"] == -1
    assert done["draft_inbox_replies_due"] == 0


# ---------------------------------------------------------------------------
# Feeding planned briefs to the team
# ---------------------------------------------------------------------------


def _planned(world, n, *, workspace=None, job=None, hours=24):
    briefs = []
    for i in range(n):
        briefs.append(
            services.create_brief(
                workspace or world.workspace,
                world.owner,
                idea=f"Planned idea {i}",
                accounts=[world.linkedin] if workspace is None else [],
                proposed_publish_at=timezone.now() + timedelta(hours=hours + i),
                origin=StudioBrief.Origin.AUTOPILOT,
                job=job,
                start=False,
            )
        )
    return briefs


def test_planned_briefs_are_fed_a_few_at_a_time(world, agency, settings):
    from apps.workspaces.models import Workspace

    settings.AGENCY_MAX_ACTIVE_BRIEFS = 3
    first = _planned(world, 4)
    other_ws = Workspace.objects.create(organization=world.org, name="Other")
    other = _planned(world, 2, workspace=other_ws, hours=200)

    assert autopilot.feed_planned_briefs() == 3

    statuses = {b.pk: StudioBrief.objects.get(pk=b.pk).status for b in first + other}
    # The oldest proposed times first, at most two per workspace, three in all.
    assert [statuses[b.pk] for b in first] == ["queued", "queued", "planned", "planned"]
    assert [statuses[b.pk] for b in other] == ["queued", "planned"]
    assert autopilot.feed_planned_briefs() == 0  # the team is full


def test_feeding_skips_workspaces_over_budget_and_drops_cancelled_plans(world, agency):
    agency_settings(world, monthly_budget_usd=5)
    job = AgencyJob.objects.create(workspace=world.workspace, kind="plan", status="cancelled")
    dropped = _planned(world, 1, job=job)[0]
    waiting = _planned(world, 1)[0]
    overspend(world.workspace)

    assert autopilot.feed_planned_briefs() == 0

    dropped.refresh_from_db()
    waiting.refresh_from_db()
    assert dropped.status == StudioBrief.Status.DISCARDED and waiting.status == StudioBrief.Status.PLANNED


# ---------------------------------------------------------------------------
# From plan to Approvals, and the one notification
# ---------------------------------------------------------------------------


def test_a_planned_week_ends_in_approvals_with_nothing_approved(world, agency, fake_team):
    from apps.calendar.services import create_default_queue_and_slots

    create_default_queue_and_slots(world.linkedin)
    agency_settings(world, posts_per_week=2)
    client_user = _client_user(world)
    assert not world.workspace.require_dashboard_approval  # the gate wouldn't stop a worker here

    outcome = autopilot.plan_week(AgencySettings.objects.get(), autopilot.next_week_start(world.workspace))
    job = drive(outcome.week.job)
    assert job.status == AgencyJob.Status.DONE, job.error

    assert autopilot.announce_planned_weeks() == 0  # the posts aren't made yet
    while autopilot.feed_planned_briefs():
        for brief in StudioBrief.objects.filter(job=job, status__in=StudioBrief.ACTIVE_STATUSES):
            run_all(brief)

    briefs = list(StudioBrief.objects.filter(job=job))
    assert len(briefs) == 2 and {b.status for b in briefs} == {StudioBrief.Status.READY}
    for brief in briefs:
        assert brief.post.proposed_publish_at == brief.proposed_publish_at
        assert {pp.status for pp in brief.post.platform_posts.all()} == {"pending_review"}
        assert brief.post.platform_posts.filter(scheduled_at__isnull=False).count() == 0
    assert_nothing_approved(world.workspace)

    assert autopilot.announce_planned_weeks() == 1
    assert autopilot.announce_planned_weeks() == 0  # told once
    week = AutopilotWeek.objects.get()
    assert week.status == AutopilotWeek.Status.PLANNED
    told = set(Notification.objects.filter(event_type=EventType.AUTOPILOT_PLANNED).values_list("user", flat=True))
    assert told == {world.owner.pk, world.manager.pk}  # approvers; not the editor, viewer or client
    assert client_user.pk not in told
    note = Notification.objects.filter(event_type=EventType.AUTOPILOT_PLANNED).first()
    assert note.data["action_url"].endswith(_url("studio:index", world)) and "2 posts" in note.title


def test_a_failed_plan_marks_the_week_failed_and_a_retry_brings_it_back(world, agency):
    agency_settings(world)
    agency.fail = {"planner": "Claude is rate-limiting this account right now."}
    outcome = autopilot.plan_week(AgencySettings.objects.get(), NEXT_MONDAY)
    job = drive(outcome.week.job)
    assert job.status == AgencyJob.Status.FAILED

    autopilot.announce_planned_weeks()
    week = AutopilotWeek.objects.get()
    assert week.status == AutopilotWeek.Status.FAILED and "rate-limiting" in week.note

    from apps.studio import engine

    engine.restart(job)
    autopilot.announce_planned_weeks()
    week.refresh_from_db()
    assert week.status == AutopilotWeek.Status.PLANNING


def test_plan_now_replans_a_skipped_week_but_not_a_planned_one(world, agency):
    row = agency_settings(world)
    AutopilotWeek.objects.create(workspace=world.workspace, week_start=NEXT_MONDAY, status="skipped", note="x")

    outcome = autopilot.plan_week(row, NEXT_MONDAY, manual=True)
    assert outcome.started and outcome.week.status == AutopilotWeek.Status.PLANNING and outcome.week.job

    again = autopilot.plan_week(row, NEXT_MONDAY, manual=True)
    assert not again.started and "already planning" in again.message
    assert AgencyJob.objects.filter(kind="plan").count() == 1


# ---------------------------------------------------------------------------
# The settings page
# ---------------------------------------------------------------------------


def _form(world, **overrides):
    data = {
        "autopilot_enabled": "on",
        "posts_per_week": "4",
        "accounts": [str(world.linkedin.pk)],
        "pillars": "Explainers, Projects\nBuyer questions",
        "plan_weekday": "4",
        "plan_hour": "16",
        "blog_posts_per_month": "0",
        "blog_site": "",
        "monthly_budget_usd": "120",
        "lead": str(world.manager.pk),
        "learn_from_best": "on",
    }
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not None}


def test_the_page_shows_the_promise_and_the_owner_saves(client, world):
    client.force_login(world.owner)

    html = client.get(_url("studio:autopilot", world)).content.decode()
    assert "Nothing goes out without you" in html and "Plan next week now" in html
    assert 'aria-current="page"' in html and "Asia/Kolkata" in html

    response = client.post(_url("studio:autopilot", world), _form(world))

    assert response.status_code == 302
    row = AgencySettings.objects.get(workspace=world.workspace)
    assert row.autopilot_enabled and row.posts_per_week == 4 and row.lead == world.manager
    assert row.pillars == ["Explainers", "Projects", "Buyer questions"]
    assert list(row.accounts.all()) == [world.linkedin] and row.learn_from_best and not row.inbox_drafts_enabled
    assert str(row.monthly_budget_usd) == "120.00"


def test_only_settings_managers_may_save(client, world):
    client.force_login(world.manager)  # managers may plan, not change what the team spends

    assert client.get(_url("studio:autopilot", world)).status_code == 200
    assert client.post(_url("studio:autopilot", world), _form(world)).status_code == 403
    assert not AgencySettings.objects.exists()

    for user in (world.viewer, _client_user(world)):
        client.force_login(user)
        assert client.get(_url("studio:autopilot", world)).status_code == 403


def test_choices_from_another_workspace_or_a_client_lead_are_refused(client, world):
    from apps.social_accounts.models import SocialAccount
    from apps.workspaces.models import Workspace

    other_ws = Workspace.objects.create(organization=world.org, name="Other")
    foreign = SocialAccount.objects.create(workspace=other_ws, platform="linkedin_company", account_platform_id="3")
    client_user = _client_user(world)
    client.force_login(world.owner)

    response = client.post(_url("studio:autopilot", world), _form(world, accounts=[str(foreign.pk)]))
    assert response.status_code == 400
    response = client.post(_url("studio:autopilot", world), _form(world, lead=str(client_user.pk)))
    assert response.status_code == 400
    response = client.post(_url("studio:autopilot", world), _form(world, lead=str(world.editor.pk)))
    assert response.status_code == 400
    response = client.post(_url("studio:autopilot", world), _form(world, posts_per_week="15"))
    assert response.status_code == 400
    response = client.post(_url("studio:autopilot", world), _form(world, blog_posts_per_month="2"))
    assert response.status_code == 400 and "Choose the website" in response.content.decode()
    assert not AgencySettings.objects.exists()


def test_plan_next_week_now(client, world, agency):
    agency_settings(world)
    client.force_login(world.manager)

    response = client.post(_url("studio:autopilot_plan", world))

    job = AgencyJob.objects.get(kind="plan")
    assert response.status_code == 302 and str(job.pk) in response["Location"]
    week = AutopilotWeek.objects.get()
    assert week.job == job and week.week_start == autopilot.next_week_start(world.workspace)

    client.force_login(world.editor)  # can create posts, can't approve
    assert client.post(_url("studio:autopilot_plan", world)).status_code == 403


def test_plan_now_needs_settings_claude_and_budget(client, world, agency, settings):
    client.force_login(world.owner)
    response = client.post(_url("studio:autopilot_plan", world), follow=True)
    assert "Save the autopilot settings first" in response.content.decode()

    agency_settings(world, monthly_budget_usd=5)
    overspend(world.workspace)
    response = client.post(_url("studio:autopilot_plan", world), follow=True)
    assert "budget" in response.content.decode()

    settings.ANTHROPIC_API_KEY = ""
    client.post(_url("studio:autopilot_plan", world))
    assert not AgencyJob.objects.filter(kind="plan").exists()
    assert not AutopilotWeek.objects.exists()


def test_the_page_shows_the_last_run(client, world, agency, fake_team):
    agency_settings(world, posts_per_week=1)
    outcome = autopilot.plan_week(AgencySettings.objects.get(), NEXT_MONDAY)
    drive(outcome.week.job)
    autopilot.feed_planned_briefs()
    for brief in StudioBrief.objects.filter(status="queued"):
        run_all(brief)
    client.force_login(world.owner)

    html = client.get(_url("studio:autopilot", world)).content.decode()

    assert "Last run" in html and "1 post planned, 1 made, 0 approved, 0 changed" in html
    assert "Moments scout:" in html and "Open the plan" in html


@pytest.mark.parametrize("page", ["studio:autopilot", "studio:memory"])
def test_the_pages_pass_the_accessibility_sweep(client, world, page):
    from apps.common.tests.test_a11y_sweep import FAINT_TEXT, _Audit

    agency_settings(world)
    client.force_login(world.owner)

    html = client.get(_url(page, world)).content.decode()

    audit = _Audit()
    audit.feed(html)
    audit.finish()
    assert audit.unnamed_buttons == [] and audit.unnamed_controls == []
    assert [m.group(3) for m in FAINT_TEXT.finditer(html) if m.group(3).strip() not in ("•", "·", "&bull;")] == []
