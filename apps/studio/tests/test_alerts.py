"""Failed unprompted work reaches the lead and backup once; chat replies keep their thread note; nothing is approved."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
import time_machine

from apps.notifications.models import Notification
from apps.studio import alerts, autopilot, chat, engine
from apps.studio.models import AgencySettings, AutopilotWeek, Conversation, Message
from apps.studio.tests.test_insights import agency_settings, assert_nothing_approved, drive, install_fake_agency

#: The Friday plan tick (after 16:00 by default), and the Monday it plans for.
FRIDAY_EVENING = datetime(2026, 10, 23, 17, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
NEXT_MONDAY = date(2026, 10, 26)


@pytest.fixture(autouse=True)
def at_the_friday_tick():
    """Every test runs at FRIDAY_EVENING, so NEXT_MONDAY's week is still ahead of the clock whatever today's date is."""
    with time_machine.travel(FRIDAY_EVENING):
        yield


@pytest.fixture
def quiet_queue(monkeypatch):
    monkeypatch.setattr(engine, "enqueue", lambda *a, **k: None)


def _alerts(**filters):
    return Notification.objects.filter(event_type="agency_alert", **filters)


def test_failed_unprompted_job_alerts_lead_and_backup_once(world, quiet_queue):
    agency_settings(world, backup=world.manager)
    job = engine.create(world.workspace, "plan", title="Plan the week", requested_by=world.owner)
    engine.fail(job, "The planner could not reach its sources.")
    assert {note.user for note in _alerts()} == {world.owner, world.manager}
    note = _alerts(user=world.owner).get()
    assert note.title == "The team needs you: Plan the week"
    assert "could not reach its sources" in note.body
    assert note.data["action_url"].endswith(f"/jobs/{job.pk}/") and note.data["alert_key"] == f"job:{job.pk}:1"
    assert alerts.job_failed(job) == 0 and _alerts().count() == 2
    assert_nothing_approved(world.workspace)


def test_an_interrupted_job_is_described_in_plain_words(world, quiet_queue):
    agency_settings(world, backup=world.manager)
    job = engine.create(world.workspace, "plan", title="Plan the week", requested_by=world.owner)
    engine.fail(job, engine.INTERRUPTED_ERROR)
    note = _alerts(user=world.owner).get()
    assert "stopped part-way" in note.body and "worker" not in note.body
    from apps.studio import opendots

    job.refresh_from_db()
    assert opendots.task_record(job)["status"] == "interrupted"


def test_without_a_lead_every_internal_approver_is_told(world, quiet_queue):
    job = engine.create(world.workspace, "report", requested_by=world.owner)
    engine.fail(job, "x")
    assert {note.user for note in _alerts()} == {world.owner, world.manager}


def test_chat_failures_keep_their_thread_note_and_raise_no_alert(world, quiet_queue, monkeypatch):
    monkeypatch.setattr(chat, "notify_staff", lambda *a, **k: 0)
    conversation = chat.general_conversation(world.workspace, created_by=world.owner)
    job = engine.create(world.workspace, "chat", requested_by=world.owner, conversation=conversation)
    engine.fail(job, "The reply failed.")
    assert not _alerts().exists()
    assert Message.objects.filter(conversation=conversation, author_kind="system", is_internal=False).exists()


def test_private_work_alerts_only_its_requester_and_links_nowhere(world, quiet_queue):
    agency_settings(world, backup=world.manager)
    private = Conversation.objects.create(
        workspace=world.workspace, audience="internal", is_private=True, created_by=world.editor
    )
    job = engine.create(world.workspace, "plan", requested_by=world.editor, conversation=private)
    engine.fail(job, "Private plan failed.")
    note = _alerts().get()
    assert note.user == world.editor and note.data["action_url"] == ""


def test_week_failed_alerts_once_per_reason(world):
    agency_settings(world, backup=world.manager)
    week = AutopilotWeek.objects.create(
        workspace=world.workspace, week_start=NEXT_MONDAY, status="failed", note="The planner failed."
    )
    assert alerts.week_failed(week) == 2
    assert alerts.week_failed(week) == 0
    note = _alerts(user=world.owner).get()
    assert "the week of 26 Oct" in note.title and note.data["action_url"].endswith("/autopilot/")
    AutopilotWeek.objects.filter(pk=week.pk).update(note="Two drafts were not prepared.")
    assert alerts.week_failed(week) == 2 and _alerts().count() == 4
    AutopilotWeek.objects.filter(pk=week.pk).update(status="planned")
    assert alerts.week_failed(week) == 0


def test_announce_planned_weeks_alerts_a_failed_plan_without_approving_anything(world, monkeypatch):
    agency = install_fake_agency(monkeypatch)
    agency_settings(world, backup=world.manager)
    agency.fail = {"planner": "The planner is rate-limited right now."}
    outcome = autopilot.plan_week(AgencySettings.objects.get(), NEXT_MONDAY)
    drive(outcome.week.job)
    autopilot.announce_planned_weeks()
    keys = set(_alerts().values_list("data__alert_key", flat=True))
    assert any(key.startswith("job:") for key in keys) and any(key.startswith("week:") for key in keys)
    before = _alerts().count()
    autopilot.announce_planned_weeks()
    assert _alerts().count() == before
    assert_nothing_approved(world.workspace)
