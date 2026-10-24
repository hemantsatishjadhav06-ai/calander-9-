"""Routines: standing instructions that run on their own, and the page that controls them.

The account manager is faked (as in ``test_chat``) and queued stages are
recorded, so a routine's chat job is driven by hand and nothing reaches a
provider. Every path here ends with nothing approved, scheduled or published.
"""

from __future__ import annotations

import datetime as dt
import sys
import threading
import types
import zoneinfo

import pytest
from django.db import connection, transaction
from django.urls import reverse
from django.utils import timezone

from apps.approvals import services as approval_services
from apps.composer.models import PlatformPost, Post
from apps.members.models import WorkspaceMembership
from apps.notifications.models import EventType, Notification
from apps.studio import autopilot, chat, engine, routines, tasks
from apps.studio.jobtypes import chat as chat_job
from apps.studio.models import (
    AgencyJob,
    AgencySettings,
    AutopilotWeek,
    Conversation,
    Message,
    Routine,
    RoutineRun,
    StudioBrief,
)
from apps.studio.roles import client as client_roles
from apps.studio.tests.conftest import run_all
from apps.studio.tests.test_chat import FakeAccountManager, assert_nothing_approved, drive
from apps.studio.tests.test_insights import agency_settings, install_fake_agency, overspend

IST = zoneinfo.ZoneInfo("Asia/Kolkata")
LONDON = zoneinfo.ZoneInfo("Europe/London")
#: Wednesday 14 Oct 2026, 10:00 in Kolkata.
WEDNESDAY = dt.datetime(2026, 10, 14, 10, 0, tzinfo=IST)
#: An instruction without the words that make the manager read the website first.
INSTRUCTION = "Tell me what is waiting for me today, in three lines."


@pytest.fixture
def manager_agent(monkeypatch):
    fake = FakeAccountManager(reply="Three things are waiting: two posts and one article.")
    monkeypatch.setattr(client_roles, "account_manager", fake)
    monkeypatch.setattr(chat_job, "_collect_sources", lambda *args, **kwargs: {})
    return fake


@pytest.fixture
def jobs(monkeypatch):
    queued: list = []
    monkeypatch.setattr(engine, "enqueue", lambda job, stage: queued.append((job.pk, job.revision, stage)))
    return queued


def _url(name, world, **kwargs):
    return reverse(name, kwargs={"workspace_id": world.workspace.id, **kwargs})


def make_routine(world, *, user=None, instruction=INSTRUCTION, cadence="daily", weekday=None, time=dt.time(9, 0), **kw):
    return routines.create(
        world.workspace, user or world.owner, instruction=instruction, cadence=cadence, weekday=weekday, time=time, **kw
    )


def due(routine, when=WEDNESDAY):
    """Make the routine due at ``when`` without touching anything else."""
    Routine.objects.filter(pk=routine.pk).update(next_run_at=when - dt.timedelta(minutes=1))
    routine.refresh_from_db()
    return routine


def the_job(routine) -> AgencyJob:
    run = routine.runs.filter(job__isnull=False).order_by("-started_at").first()
    assert run is not None, "the routine started no job"
    return run.job


# ---------------------------------------------------------------------------
# When it runs
# ---------------------------------------------------------------------------


class TestNextRun:
    def test_weekdays_skip_the_weekend_in_the_workspace_zone(self, world):
        routine = make_routine(world, cadence="weekdays", time=dt.time(8, 30))
        friday = dt.datetime(2026, 10, 16, 9, 0, tzinfo=IST)

        when = routines.next_run(routine, friday)

        assert when.tzinfo == dt.UTC
        assert when.astimezone(IST) == dt.datetime(2026, 10, 19, 8, 30, tzinfo=IST)  # Monday
        assert when == dt.datetime(2026, 10, 19, 3, 0, tzinfo=dt.UTC)

    def test_a_run_is_strictly_after_the_moment_asked(self, world):
        routine = make_routine(world, cadence="weekly", weekday=0, time=dt.time(9, 0))
        monday_nine = dt.datetime(2026, 10, 19, 9, 0, tzinfo=IST)

        assert routines.next_run(routine, monday_nine).astimezone(IST) == monday_nine + dt.timedelta(days=7)
        earlier = monday_nine - dt.timedelta(hours=1)
        assert routines.next_run(routine, earlier).astimezone(IST) == monday_nine

    def test_london_clocks_going_back_keep_the_wall_clock_time(self, world):
        world.workspace.timezone = "Europe/London"
        world.workspace.save(update_fields=["timezone"])
        routine = make_routine(world, cadence="daily", time=dt.time(8, 30))
        saturday = dt.datetime(2026, 10, 24, 9, 0, tzinfo=LONDON)  # BST; clocks go back on the 25th

        first = routines.next_run(routine, saturday)
        second = routines.next_run(routine, first)

        assert first.astimezone(LONDON).timetuple()[3:5] == (8, 30)
        assert second.astimezone(LONDON).timetuple()[3:5] == (8, 30)
        assert first == dt.datetime(2026, 10, 25, 8, 30, tzinfo=dt.UTC)  # GMT after the change
        assert second - first == dt.timedelta(hours=24)
        assert first - saturday.astimezone(dt.UTC) == dt.timedelta(hours=24, minutes=30)

    def test_london_clocks_going_forward_keep_the_wall_clock_time(self, world):
        world.workspace.timezone = "Europe/London"
        world.workspace.save(update_fields=["timezone"])
        routine = make_routine(world, cadence="daily", time=dt.time(8, 30))
        saturday = dt.datetime(2026, 3, 28, 9, 0, tzinfo=LONDON)  # GMT; clocks go forward on the 29th

        when = routines.next_run(routine, saturday)

        assert when.astimezone(LONDON).timetuple()[:5] == (2026, 3, 29, 8, 30)
        assert when == dt.datetime(2026, 3, 29, 7, 30, tzinfo=dt.UTC)
        assert when - saturday.astimezone(dt.UTC) == dt.timedelta(hours=22, minutes=30)

    def test_kolkata_has_no_clock_change_and_an_unknown_zone_falls_back_to_utc(self, world):
        routine = make_routine(world, cadence="daily", time=dt.time(8, 30))
        march = dt.datetime(2026, 3, 28, 9, 0, tzinfo=IST)
        assert routines.next_run(routine, march) == dt.datetime(2026, 3, 29, 3, 0, tzinfo=dt.UTC)

        world.workspace.timezone = "Mars/Olympus"
        world.workspace.save(update_fields=["timezone"])
        routine.workspace.refresh_from_db()
        assert routines.next_run(routine, march) == dt.datetime(
            2026, 3, 28, 8, 30, tzinfo=dt.UTC
        )  # 09:00 IST is 03:30 UTC

    def test_cadence_in_words(self, world):
        assert (
            routines.cadence_words(make_routine(world, cadence="weekdays", time=dt.time(8, 30))) == "Weekdays at 08:30"
        )
        assert routines.cadence_words(make_routine(world, cadence="weekly", weekday=0, time=dt.time(9, 0))) == (
            "Mondays at 09:00"
        )
        assert routines.cadence_words(make_routine(world, cadence="daily", time=dt.time(17, 0))) == "Every day at 17:00"


class TestMaking:
    def test_create_sets_the_next_run_and_refuses_nonsense(self, world):
        routine = make_routine(world, cadence="weekly", weekday=4, time=dt.time(16, 15), title="Friday wrap")
        assert routine.enabled and routine.status == Routine.Status.IDLE
        assert routine.next_run_at is not None and routine.next_run_at.astimezone(IST).weekday() == 4
        assert routine.display_title == "Friday wrap" and routine.weekday == 4

        with pytest.raises(routines.RoutineError, match="plain words"):
            make_routine(world, instruction="   ")
        with pytest.raises(routines.RoutineError, match="day of the week"):
            make_routine(world, cadence="weekly", weekday=None)
        with pytest.raises(routines.RoutineError, match="time"):
            make_routine(world, time=None)
        with pytest.raises(routines.RoutineError, match="how often"):
            make_routine(world, cadence="hourly")
        with pytest.raises(routines.RoutineError, match="2,000"):
            make_routine(world, instruction="x" * 2001)

    def test_propose_makes_a_switched_off_routine_for_the_chat_action(self, world):
        routine = routines.propose(
            world.workspace,
            world.editor,
            instruction=INSTRUCTION,
            cadence="weekdays",
            weekday=None,
            time=dt.time(8, 30),
        )
        assert not routine.enabled and routine.created_by == world.editor
        assert routine.kind == Routine.Kind.INSTRUCTION and routine.cadence == Routine.Cadence.WEEKDAYS

        assert routines.run_due(now=routine.next_run_at + dt.timedelta(days=30)) == 0  # off means off

    def test_a_routine_runs_in_one_of_this_workspaces_team_threads(self, world):
        from apps.workspaces.models import Workspace

        other = Workspace.objects.create(organization=world.org, name="Other")
        foreign = chat.general_conversation(other, created_by=world.owner)
        with pytest.raises(routines.RoutineError, match="team threads"):
            make_routine(world, conversation=foreign)
        client_thread = chat.general_conversation(world.workspace, audience=Conversation.Audience.CLIENT)
        with pytest.raises(routines.RoutineError, match="team threads"):
            make_routine(world, conversation=client_thread)


# ---------------------------------------------------------------------------
# The tick: starting
# ---------------------------------------------------------------------------


class TestRunDue:
    def test_a_due_instruction_posts_in_the_authors_name_and_the_manager_hears_it_is_a_routine(
        self, world, manager_agent, jobs
    ):
        routine = due(make_routine(world, user=world.editor, cadence="daily", time=dt.time(9, 0)))

        assert routines.run_due(now=WEDNESDAY) == 1

        routine.refresh_from_db()
        assert routine.status == Routine.Status.RUNNING
        assert routine.lease_until == WEDNESDAY + routines.LEASE
        assert routine.last_run_at == WEDNESDAY and routine.last_error == ""
        assert routine.next_run_at.astimezone(IST) == dt.datetime(2026, 10, 15, 9, 0, tzinfo=IST)
        job = the_job(routine)
        assert job.kind == AgencyJob.Kind.CHAT and job.requested_by == world.editor
        assert job.input["kind"] == "routine"
        message = Message.objects.get(pk=job.input["message_id"])
        assert message.author == world.editor and message.author_kind == Message.AuthorKind.STAFF
        assert message.body == INSTRUCTION and not message.is_internal
        assert message.conversation == chat.find_general(world.workspace)

        drive(job)
        assert manager_agent.calls[-1]["request_kind"] == "routine"
        assert manager_agent.calls[-1]["speaker"] == "staff"
        assert_nothing_approved(world.workspace)

    def test_not_due_paused_and_running_routines_are_left_alone(self, world, manager_agent, jobs):
        later = make_routine(world, cadence="daily", time=dt.time(9, 0))  # due tomorrow at the earliest
        paused = due(make_routine(world, cadence="daily", time=dt.time(9, 0), enabled=False))
        running = due(make_routine(world, cadence="daily", time=dt.time(9, 0)))
        Routine.objects.filter(pk=running.pk).update(status=Routine.Status.RUNNING)

        assert routines.run_due(now=WEDNESDAY) == 0
        assert not AgencyJob.objects.filter(kind=AgencyJob.Kind.CHAT).exists()
        for routine in (later, paused, running):
            routine.refresh_from_db()
        assert later.status == paused.status == Routine.Status.IDLE and running.status == Routine.Status.RUNNING

    def test_a_few_per_tick_oldest_due_first(self, world, manager_agent, jobs):
        first = due(make_routine(world), WEDNESDAY - dt.timedelta(hours=2))
        second = due(make_routine(world), WEDNESDAY - dt.timedelta(hours=1))
        third = due(make_routine(world))

        assert routines.run_due(limit=2, now=WEDNESDAY) == 2
        statuses = {r.pk: Routine.objects.get(pk=r.pk).status for r in (first, second, third)}
        assert statuses[first.pk] == statuses[second.pk] == Routine.Status.RUNNING
        assert statuses[third.pk] == Routine.Status.IDLE
        assert routines.run_due(limit=2, now=WEDNESDAY) == 1

    def test_the_routines_own_thread_is_used_when_it_still_exists(self, world, manager_agent, jobs):
        thread = Conversation.objects.create(
            workspace=world.workspace, audience=Conversation.Audience.INTERNAL, title="Mornings", created_by=world.owner
        )
        routine = due(make_routine(world, conversation=thread))

        assert routines.run_due(now=WEDNESDAY) == 1
        assert the_job(routine).conversation == thread

        thread.delete()
        routine.refresh_from_db()
        Routine.objects.filter(pk=routine.pk).update(status=Routine.Status.IDLE, next_run_at=WEDNESDAY)
        assert routines.run_due(now=WEDNESDAY + dt.timedelta(days=1)) == 1
        assert the_job(Routine.objects.get(pk=routine.pk)).conversation == chat.find_general(world.workspace)

    def test_a_private_thread_is_never_used(self, world, manager_agent, jobs):
        private = Conversation.objects.create(
            workspace=world.workspace, audience=Conversation.Audience.INTERNAL, title="Private", is_private=True
        )
        routine = due(make_routine(world, conversation=private))

        assert routines.run_due(now=WEDNESDAY) == 1
        job = the_job(routine)
        assert job.conversation != private and not chat.is_private_conversation(job.conversation)


class TestGates:
    def _skipped(self, routine) -> RoutineRun:
        routine.refresh_from_db()
        run = routine.runs.get()
        assert run.status == RoutineRun.Status.SKIPPED and run.job_id is None
        assert routine.status == Routine.Status.IDLE and routine.last_error == run.summary
        assert routine.next_run_at > WEDNESDAY
        assert not AgencyJob.objects.filter(kind=AgencyJob.Kind.CHAT).exists()
        return run

    def test_an_author_who_left_the_team(self, world, manager_agent, jobs):
        routine = due(make_routine(world, user=world.editor))
        WorkspaceMembership.objects.filter(user=world.editor, workspace=world.workspace).delete()

        assert routines.run_due(now=WEDNESDAY) == 0
        assert self._skipped(routine).summary == routines.AUTHOR_GONE

    def test_an_author_who_became_a_client(self, world, manager_agent, jobs):
        routine = due(make_routine(world, user=world.editor))
        WorkspaceMembership.objects.filter(user=world.editor, workspace=world.workspace).update(workspace_role="client")

        assert routines.run_due(now=WEDNESDAY) == 0
        assert self._skipped(routine).summary == routines.AUTHOR_GONE

    def test_no_provider(self, world, manager_agent, jobs, settings):
        routine = due(make_routine(world))
        settings.ANTHROPIC_API_KEY = ""

        assert routines.run_due(now=WEDNESDAY) == 0
        run = self._skipped(routine)
        assert run.summary == autopilot.PROVIDER_PAUSED and "API_KEY" not in run.summary

    def test_no_budget(self, world, manager_agent, jobs):
        routine = due(make_routine(world))
        AgencySettings.objects.create(workspace=world.workspace, monthly_budget_usd=5)
        overspend(world.workspace)

        assert routines.run_due(now=WEDNESDAY) == 0
        assert "budget" in self._skipped(routine).summary

    def test_an_archived_or_deleting_workspace(self, world, manager_agent, jobs):
        from apps.organizations.models import Organization

        routine = due(make_routine(world))
        world.workspace.is_archived = True
        world.workspace.save(update_fields=["is_archived"])
        assert routines.run_due(now=WEDNESDAY) == 0
        assert self._skipped(routine).summary == routines.WORKSPACE_PAUSED

        world.workspace.is_archived = False
        world.workspace.save(update_fields=["is_archived"])
        Organization.objects.filter(pk=world.org.pk).update(deletion_requested_at=timezone.now())
        due(routine)
        assert routines.run_due(now=WEDNESDAY) == 0
        assert routine.runs.count() == 2

    def test_the_reply_cap_skips_with_the_threads_own_sentence(self, world, manager_agent, jobs, monkeypatch):
        routine = due(make_routine(world))
        monkeypatch.setattr(chat, "replies_today", lambda workspace: chat.DAILY_REPLY_CAP)

        assert routines.run_due(now=WEDNESDAY) == 0
        run = self._skipped(routine)
        assert "the most it answers" in run.summary
        # The instruction was posted and the thread explains why nothing happened.
        assert Message.objects.filter(author=world.owner, body=INSTRUCTION).exists()


# ---------------------------------------------------------------------------
# The tick: settling
# ---------------------------------------------------------------------------


@pytest.fixture
def running(world, manager_agent, jobs):
    """A routine that the tick started at WEDNESDAY, with its chat job still queued."""
    routine = due(make_routine(world, user=world.editor))
    assert routines.run_due(now=WEDNESDAY) == 1
    routine.refresh_from_db()
    return routine


def _notices(user):
    return Notification.objects.filter(user=user, event_type=EventType.TEAM_MESSAGE, data__kind="routine")


class TestSettle:
    def test_a_finished_job_makes_the_routine_idle_with_the_reply_as_summary(self, world, running, manager_agent):
        manager_agent.reply = "Done: " + "x" * 300
        job = drive(the_job(running))
        assert job.status == AgencyJob.Status.DONE

        assert routines.settle_running(now=WEDNESDAY + dt.timedelta(minutes=5)) == 1

        running.refresh_from_db()
        run = running.runs.get()
        assert running.status == Routine.Status.IDLE and running.lease_until is None and running.last_error == ""
        assert run.status == RoutineRun.Status.FINISHED and run.finished_at is not None
        assert run.summary == ("Done: " + "x" * 300)[:200]
        assert "Last run" in routines.rows(world.workspace)[0]["last_result"]
        assert not _notices(world.editor).exists()
        assert routines.settle_running() == 0

    def test_a_failed_job_fails_the_routine_and_tells_the_author_once(self, world, running, manager_agent):
        manager_agent.fail = "The provider did not answer."
        job = drive(the_job(running))
        assert job.status == AgencyJob.Status.FAILED

        assert routines.settle_running(now=WEDNESDAY + dt.timedelta(minutes=5)) == 1
        assert routines.settle_running(now=WEDNESDAY + dt.timedelta(minutes=6)) == 0

        running.refresh_from_db()
        run = running.runs.get()
        assert running.status == Routine.Status.FAILED and running.last_error == job.error
        assert run.status == RoutineRun.Status.FAILED and run.summary == job.error
        notice = _notices(world.editor).get()
        assert notice.data["run_id"] == str(run.pk) and notice.data["routine_id"] == str(running.pk)
        assert running.display_title in notice.title and "/routines/" in notice.data["action_url"]
        assert "Failed" in routines.rows(world.workspace)[0]["last_result"]

    def test_a_cancelled_job_counts_as_failed(self, world, running):
        engine.cancel(the_job(running))

        assert routines.settle_running(now=WEDNESDAY + dt.timedelta(minutes=5)) == 1
        running.refresh_from_db()
        assert running.status == Routine.Status.FAILED and running.last_error == "The run was stopped."
        assert running.runs.get().status == RoutineRun.Status.FAILED
        assert _notices(world.editor).count() == 1

    def test_a_failed_routine_still_runs_at_its_next_time(self, world, running, manager_agent, jobs):
        manager_agent.fail = "Boom."
        drive(the_job(running))
        routines.settle_running(now=WEDNESDAY + dt.timedelta(minutes=5))
        running.refresh_from_db()
        assert running.status == Routine.Status.FAILED

        assert routines.run_due(now=running.next_run_at) == 1
        running.refresh_from_db()
        assert running.status == Routine.Status.RUNNING and running.last_error == ""


class TestLease:
    def test_an_expired_lease_with_the_job_still_active_interrupts_and_never_retries(self, world, running, jobs):
        job = the_job(running)
        assert job.is_active
        too_early = WEDNESDAY + routines.LEASE - dt.timedelta(minutes=1)
        assert routines.settle_running(now=too_early) == 0

        late = WEDNESDAY + routines.LEASE + dt.timedelta(minutes=1)
        assert routines.settle_running(now=late) == 1

        running.refresh_from_db()
        run = running.runs.get()
        assert running.status == Routine.Status.INTERRUPTED and running.last_error == routines.INTERRUPTED
        assert run.status == RoutineRun.Status.INTERRUPTED and run.summary == routines.INTERRUPTED
        job.refresh_from_db()
        assert job.is_active  # the job is left for a person to look at
        notice = _notices(world.editor).get()
        assert "stopped part-way" in notice.body and "worker" not in notice.body
        row = routines.rows(world.workspace)[0]
        assert row["last_result"] == routines.INTERRUPTED and row["next_run_words"] == "" and row["needs_attention"]

        # Neither the next tick nor the next scheduled time starts it again...
        assert routines.settle_running(now=late + dt.timedelta(minutes=1)) == 0
        assert routines.run_due(now=running.next_run_at + dt.timedelta(days=3)) == 0
        assert len(jobs) == 1 and _notices(world.editor).count() == 1
        # ...only a person does.
        outcome = routines.run_now(running, now=late + dt.timedelta(hours=1))
        assert outcome.started
        running.refresh_from_db()
        assert running.status == Routine.Status.RUNNING and running.runs.count() == 2 and len(jobs) == 2

    def test_a_job_that_finished_before_the_lease_check_is_settled_normally(self, world, running, manager_agent):
        drive(the_job(running))
        late = WEDNESDAY + routines.LEASE + dt.timedelta(hours=1)

        assert routines.settle_running(now=late) == 1
        running.refresh_from_db()
        assert running.status == Routine.Status.IDLE and running.runs.get().status == RoutineRun.Status.FINISHED

    def test_a_job_still_queued_behind_other_work_keeps_its_lease(self, world, running, jobs, monkeypatch):
        """A busy day is not a dead run: the queue still holds the job, so the routine waits with it."""
        job = the_job(running)
        monkeypatch.setattr(engine, "_has_pending_task", lambda *args, **kwargs: True)
        late = WEDNESDAY + routines.LEASE + dt.timedelta(minutes=1)

        assert routines.settle_running(now=late) == 0

        running.refresh_from_db()
        assert running.status == Routine.Status.RUNNING and running.lease_until == late + routines.LEASE
        assert running.runs.get().status == RoutineRun.Status.RUNNING and not _notices(world.editor).exists()
        # A job the engine holds for a pause reason it resumes by itself is waiting too.
        monkeypatch.setattr(engine, "_has_pending_task", lambda *args, **kwargs: False)
        AgencyJob.objects.filter(pk=job.pk).update(error=autopilot.PROVIDER_PAUSED)
        later = late + routines.LEASE + dt.timedelta(minutes=1)
        assert routines.settle_running(now=later) == 0
        running.refresh_from_db()
        assert running.status == Routine.Status.RUNNING and running.lease_until == later + routines.LEASE
        # Once nothing holds the job any more, the lease really expires.
        AgencyJob.objects.filter(pk=job.pk).update(error="")
        last = later + routines.LEASE + dt.timedelta(minutes=1)
        assert routines.settle_running(now=last) == 1
        running.refresh_from_db()
        assert running.status == Routine.Status.INTERRUPTED

    def test_resume_after_an_interruption_puts_it_back_on_its_schedule(self, client, world, running, jobs):
        late = WEDNESDAY + routines.LEASE + dt.timedelta(minutes=1)
        assert routines.settle_running(now=late) == 1
        running.refresh_from_db()
        assert running.status == Routine.Status.INTERRUPTED

        routines.set_enabled(running, False, now=late)
        running.refresh_from_db()
        assert running.status == Routine.Status.INTERRUPTED and not running.enabled  # pausing changes nothing else
        routines.set_enabled(running, True, now=late)

        running.refresh_from_db()
        assert running.enabled and running.status == Routine.Status.IDLE and running.last_error == ""
        row = routines.rows(world.workspace)[0]
        assert row["next_run_words"] and not row["needs_attention"]
        # The next run the page announced is one the tick really takes.
        assert routines.run_due(now=running.next_run_at) == 1
        assert len(jobs) == 2
        # From the page: Resume says the next run, and that run is on the schedule.
        client.force_login(world.editor)
        Routine.objects.filter(pk=running.pk).update(status=Routine.Status.INTERRUPTED, enabled=False)
        response = client.post(_url("studio:routines_toggle", world, routine_id=running.pk), follow=True)
        assert "On. Next run" in response.content.decode()
        assert Routine.objects.get(pk=running.pk).status == Routine.Status.IDLE


# ---------------------------------------------------------------------------
# Two ticks at once
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_two_ticks_never_start_the_same_routine_twice(world, manager_agent, jobs):
    routine = due(make_routine(world))
    held = threading.Event()
    release = threading.Event()
    errors: list[Exception] = []

    def other_tick_holds_the_row():
        try:
            with transaction.atomic():
                Routine.objects.select_for_update().get(pk=routine.pk)
                held.set()
                release.wait(10)
        except Exception as exc:  # pragma: no cover - surfaced through ``errors``
            errors.append(exc)
            held.set()
        finally:
            connection.close()

    thread = threading.Thread(target=other_tick_holds_the_row)
    thread.start()
    assert held.wait(10)
    try:
        assert routines.run_due(now=WEDNESDAY) == 0  # locked by the other tick: skipped, not waited for
    finally:
        release.set()
        thread.join(10)
    assert errors == []
    assert not AgencyJob.objects.filter(kind=AgencyJob.Kind.CHAT).exists()

    assert routines.run_due(now=WEDNESDAY) == 1
    assert routines.run_due(now=WEDNESDAY) == 0
    assert AgencyJob.objects.count() == 1 and routine.runs.count() == 1


@pytest.mark.django_db(transaction=True)
def test_run_now_while_the_tick_holds_the_row_says_busy(world, manager_agent, jobs):
    routine = due(make_routine(world))
    held = threading.Event()
    release = threading.Event()

    def tick_holds_the_row():
        try:
            with transaction.atomic():
                Routine.objects.select_for_update().get(pk=routine.pk)
                held.set()
                release.wait(10)
        finally:
            connection.close()

    thread = threading.Thread(target=tick_holds_the_row)
    thread.start()
    assert held.wait(10)
    try:
        outcome = routines.run_now(routine)
    finally:
        release.set()
        thread.join(10)
    assert not outcome.started and outcome.message == routines.BUSY


# ---------------------------------------------------------------------------
# Briefings
# ---------------------------------------------------------------------------


class TestBriefing:
    @pytest.fixture
    def briefing(self, world):
        return due(routines.suggestion(world.workspace, world.owner, "morning"))

    def test_without_the_briefing_module_the_run_is_skipped_and_the_routine_stays_idle(self, briefing, monkeypatch):
        monkeypatch.delitem(sys.modules, "apps.studio.briefing", raising=False)
        monkeypatch.setattr(routines.importlib, "import_module", lambda name: (_ for _ in ()).throw(ImportError(name)))

        assert routines.run_due(now=WEDNESDAY) == 0

        briefing.refresh_from_db()
        run = briefing.runs.get()
        assert run.status == RoutineRun.Status.SKIPPED and run.summary == routines.BRIEFING_UNAVAILABLE
        assert briefing.status == Routine.Status.IDLE and briefing.last_error == routines.BRIEFING_UNAVAILABLE
        assert briefing.next_run_at > WEDNESDAY

    def test_a_module_without_send_daily_is_skipped_the_same_way(self, briefing, monkeypatch):
        monkeypatch.setitem(sys.modules, "apps.studio.briefing", types.ModuleType("apps.studio.briefing"))

        assert routines.run_due(now=WEDNESDAY) == 0
        assert briefing.runs.get().summary == routines.BRIEFING_UNAVAILABLE

    def test_the_briefing_is_sent_without_a_model_or_a_budget(self, world, briefing, monkeypatch, settings):
        sent = []
        module = types.ModuleType("apps.studio.briefing")
        module.send_daily = lambda workspace, *, routine: sent.append((workspace, routine))  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "apps.studio.briefing", module)
        settings.ANTHROPIC_API_KEY = ""
        AgencySettings.objects.create(workspace=world.workspace, monthly_budget_usd=5)
        overspend(world.workspace)

        assert routines.run_due(now=WEDNESDAY) == 1

        assert sent == [(world.workspace, briefing)]
        briefing.refresh_from_db()
        run = briefing.runs.get()
        assert run.status == RoutineRun.Status.FINISHED and run.summary == routines.BRIEFING_SENT
        assert briefing.status == Routine.Status.IDLE and briefing.last_run_at == WEDNESDAY
        assert not AgencyJob.objects.filter(kind=AgencyJob.Kind.CHAT).exists()

    def test_a_briefing_that_raises_fails_the_run_and_tells_the_author(self, world, briefing, monkeypatch):
        module = types.ModuleType("apps.studio.briefing")

        def boom(workspace, *, routine):
            raise RuntimeError("no transport")

        module.send_daily = boom  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "apps.studio.briefing", module)

        assert routines.run_due(now=WEDNESDAY) == 0
        briefing.refresh_from_db()
        assert briefing.status == Routine.Status.FAILED and briefing.last_error == routines.BRIEFING_FAILED
        assert briefing.runs.get().status == RoutineRun.Status.FAILED
        assert _notices(world.owner).count() == 1


# ---------------------------------------------------------------------------
# The task
# ---------------------------------------------------------------------------


def test_the_tick_is_registered_every_minute_and_never_raises(world, monkeypatch):
    from background_task.models import Task

    from apps.studio.apps import StudioConfig

    StudioConfig._register_tasks(sender=None)
    task = Task.objects.get(verbose_name="run_routine_tick")
    assert task.repeat == 60 and task.task_name == "apps.studio.tasks.run_routine_tick"

    calls = []
    monkeypatch.setattr(routines, "tick", lambda: calls.append(1) or (_ for _ in ()).throw(RuntimeError("boom")))
    tasks.run_routine_tick.now()  # swallowed by keep_schedule
    assert calls == [1]


def test_the_tick_settles_then_starts(world, running, manager_agent, jobs):
    drive(the_job(running))
    other = due(make_routine(world, user=world.owner))

    done = routines.tick(now=WEDNESDAY + dt.timedelta(minutes=5))

    assert done == {"settled": 1, "started": 1}
    running.refresh_from_db()
    other.refresh_from_db()
    assert running.status == Routine.Status.IDLE and other.status == Routine.Status.RUNNING


# ---------------------------------------------------------------------------
# A routine's instruction goes ahead on its own
# ---------------------------------------------------------------------------


class TestRoutinePosts:
    """Nobody is typing when a routine runs: a post it proposes starts without a tap, in every creation mode."""

    @pytest.fixture
    def post_manager(self, monkeypatch):
        from apps.studio.tests.test_conversation_manager import topic_only
        from apps.studio.tests.test_guided_chat import GuidedManager

        manager = GuidedManager(creative_brief=topic_only())
        monkeypatch.setattr(client_roles, "account_manager", manager)
        monkeypatch.setattr(chat_job, "_collect_sources", lambda *args, **kwargs: {})
        return manager

    def test_a_due_instruction_that_proposes_a_post_starts_the_brief_in_confirm_mode(
        self, world, jobs, fake_team, post_manager
    ):
        assert chat.creation_mode(world.workspace) == AgencySettings.CreationMode.CONFIRM
        routine = due(make_routine(world, user=world.editor, instruction="Draft a market update for LinkedIn."))

        assert routines.run_due(now=WEDNESDAY) == 1
        job = drive(the_job(routine))

        assert job.status == AgencyJob.Status.DONE and post_manager.calls[-1]["request_kind"] == "routine"
        assert job.result["auto_started"] is True and job.result["awaiting_confirmation"] is False
        brief = StudioBrief.objects.get(workspace=world.workspace)
        assert brief.status == StudioBrief.Status.QUEUED and brief.origin == StudioBrief.Origin.CHAT
        assert brief.requested_by == world.editor and brief.author == world.editor and brief.job_id == job.pk
        assert job.result["brief_id"] == str(brief.pk) and fake_team.queued == [(brief.pk, 1, "strategy")]
        reply = Message.objects.get(job=job, author_kind=Message.AuthorKind.AGENT)
        assert reply.action_status == Message.ActionStatus.STARTED and reply.body.startswith("On it")
        assert routines.settle_running(now=WEDNESDAY + dt.timedelta(minutes=5)) == 1
        routine.refresh_from_db()
        assert routine.status == Routine.Status.IDLE and routine.runs.get().status == RoutineRun.Status.FINISHED

        run_all(brief)

        # The finished post waits for a person, exactly as a typed idea's would.
        assert brief.status == StudioBrief.Status.READY
        assert set(PlatformPost.objects.filter(post=brief.post).values_list("status", flat=True)) == {"pending_review"}
        assert_nothing_approved(world.workspace)

    def test_a_person_typing_the_same_words_still_waits_for_the_tap(self, world, jobs, fake_team, post_manager):
        conversation = chat.general_conversation(world.workspace, created_by=world.editor)

        job = drive(chat.post_message(conversation, world.editor, "Draft a market update for LinkedIn.").job)

        assert job.result["awaiting_confirmation"] is True and not job.result.get("auto_started")
        assert not StudioBrief.objects.exists() and fake_team.queued == []

    def test_a_routine_in_a_telegram_team_group_still_waits_for_the_tap(self, world, jobs, fake_team, post_manager):
        """The team's own threads only: a group chat is never started without a tap, routine or not."""
        from apps.telegram.models import TelegramChat, TelegramConnection

        connection = TelegramConnection.objects.create(
            workspace=world.workspace, token="t", webhook_secret="s", bot_id=1, bot_username="b", is_active=True
        )
        group = Conversation.objects.create(workspace=world.workspace, audience=Conversation.Audience.INTERNAL)
        TelegramChat.objects.create(
            connection=connection, chat_id=-5, chat_type="group", audience="team", conversation=group
        )
        job = engine.create(
            world.workspace,
            AgencyJob.Kind.CHAT,
            input={"kind": "routine", "telegram_context": {}},
            requested_by=world.editor,
            conversation=group,
        )
        trigger = Message(conversation=group, author=world.editor, author_kind=Message.AuthorKind.STAFF, body="x")

        assert not chat_job._auto_eligible(job, group, trigger, "staff")
        general = chat.general_conversation(world.workspace, created_by=world.editor)
        web_job = engine.create(
            world.workspace,
            AgencyJob.Kind.CHAT,
            input={"kind": "routine"},
            requested_by=world.editor,
            conversation=general,
        )
        assert chat_job._auto_eligible(web_job, general, trigger, "staff")
        assert not chat_job._auto_eligible(web_job, general, trigger, "client")
        assert not StudioBrief.objects.exists()


# ---------------------------------------------------------------------------
# Nothing a routine starts can approve, schedule or publish
# ---------------------------------------------------------------------------


class TestRoutinesNeverApprove:
    @pytest.fixture
    def pending(self, world):
        post = Post.objects.create(workspace=world.workspace, author=world.owner, caption="Hello")
        pp = PlatformPost.objects.create(post=post, social_account=world.linkedin, status="pending_review")
        return post, pp

    def test_a_routines_job_that_tries_to_approve_fails_and_the_post_waits(
        self, world, running, manager_agent, pending, monkeypatch
    ):
        post, pp = pending

        def sneaky(profile, **kwargs):
            approval_services.approve_post(post, world.owner, world.workspace)
            return manager_agent(profile, **kwargs)

        monkeypatch.setattr(client_roles, "account_manager", sneaky)
        job = drive(the_job(running))

        assert job.status == AgencyJob.Status.FAILED
        pp.refresh_from_db()
        assert pp.status == "pending_review"
        routines.settle_running(now=WEDNESDAY + dt.timedelta(minutes=5))
        running.refresh_from_db()
        assert running.status == Routine.Status.FAILED
        assert_nothing_approved(world.workspace)

    def test_the_whole_routine_path_leaves_posts_where_people_left_them(self, world, running, manager_agent, pending):
        _post, pp = pending
        drive(the_job(running))
        routines.settle_running(now=WEDNESDAY + dt.timedelta(minutes=5))
        routines.run_now(running)
        pp.refresh_from_db()
        assert pp.status == "pending_review"
        assert_nothing_approved(world.workspace)


# ---------------------------------------------------------------------------
# The page and its controls
# ---------------------------------------------------------------------------


class TestPage:
    def test_the_tab_sits_after_overview(self, world):
        from apps.studio import dashboard

        keys = [tab["key"] for tab in dashboard.tabs(world.workspace, "routines")]
        assert keys[:2] == ["overview", "routines"]
        assert next(tab for tab in dashboard.tabs(world.workspace, "routines") if tab["key"] == "routines")["active"]

    def test_the_page_lists_routines_with_their_schedule_and_controls(self, client, world):
        routine = make_routine(world, user=world.editor, cadence="weekdays", time=dt.time(8, 30), title="Mornings")
        make_routine(world, cadence="weekly", weekday=0, time=dt.time(9, 0), enabled=False, title="Monday plan")
        client.force_login(world.editor)

        html = client.get(_url("studio:routines", world)).content.decode()

        assert "Mornings" in html and "Weekdays at 08:30" in html and "Mondays at 09:00" in html
        assert "run yet" in html and "Paused" in html and "Asia/Kolkata" in html
        assert "Morning briefing" in html and "Monday plan" in html and "Draft replies to new comments" in html
        assert _url("studio:routines_run_now", world, routine_id=routine.pk) in html
        assert _url("studio:routines_toggle", world, routine_id=routine.pk) in html
        assert _url("studio:routines_delete", world, routine_id=routine.pk) in html
        assert 'aria-current="page"' in html and "Routines" in html
        for word in ("AI Studio", "assistant", "operator", "CTO", "API_KEY"):
            assert word not in html

    def test_someone_else_sees_run_now_but_not_pause_or_delete(self, client, world):
        other = make_routine(world, user=world.manager, title="Manager's routine")
        client.force_login(world.editor)
        html = client.get(_url("studio:routines", world)).content.decode()
        assert _url("studio:routines_run_now", world, routine_id=other.pk) in html
        assert _url("studio:routines_delete", world, routine_id=other.pk) not in html

        client.force_login(world.owner)  # manages the workspace's settings
        html = client.get(_url("studio:routines", world)).content.decode()
        assert _url("studio:routines_delete", world, routine_id=other.pk) in html

    def test_the_form_makes_a_routine_and_says_so(self, client, world):
        client.force_login(world.editor)
        response = client.post(
            _url("studio:routines_create", world),
            {"instruction": INSTRUCTION, "cadence": "weekly", "weekday": "0", "time": "09:00", "title": "Mondays"},
            follow=True,
        )
        routine = Routine.objects.get()
        assert routine.created_by == world.editor and routine.cadence == "weekly" and routine.weekday == 0
        assert routine.time == dt.time(9, 0) and routine.enabled and routine.title == "Mondays"
        assert "Saved" in response.content.decode() and "mondays at 09:00" in response.content.decode()

    def test_a_bad_form_comes_back_with_a_sentence(self, client, world):
        client.force_login(world.editor)
        response = client.post(
            _url("studio:routines_create", world), {"instruction": "", "cadence": "daily", "time": "25:99"}
        )
        assert response.status_code == 400 and "plain words" in response.content.decode()
        response = client.post(
            _url("studio:routines_create", world), {"instruction": INSTRUCTION, "cadence": "daily", "time": "25:99"}
        )
        assert response.status_code == 400 and "time of day" in response.content.decode()
        assert not Routine.objects.exists()

    def test_one_tap_suggestions(self, client, world):
        client.force_login(world.owner)
        for key in ("morning", "monday", "replies"):
            assert client.post(_url("studio:routines_create", world), {"suggestion": key}).status_code == 302
        by_title = {r.title: r for r in Routine.objects.all()}
        morning = by_title["Morning briefing"]
        assert (
            morning.kind == Routine.Kind.BRIEFING and morning.cadence == "weekdays" and morning.time == dt.time(8, 30)
        )
        monday = by_title["Monday plan"]
        assert monday.kind == Routine.Kind.INSTRUCTION and (monday.cadence, monday.weekday) == ("weekly", 0)
        assert monday.time == dt.time(9, 0) and "pillars" in monday.instruction and "approval" in monday.instruction
        replies = by_title["Draft replies to new comments"]
        assert replies.cadence == "weekdays" and replies.time == dt.time(17, 0) and replies.instruction
        assert all(r.enabled and r.created_by == world.owner for r in by_title.values())
        assert client.post(_url("studio:routines_create", world), {"suggestion": "nope"}).status_code == 400

    def test_pause_resume_run_now_and_delete(self, client, world, manager_agent, jobs):
        routine = make_routine(world, user=world.editor)
        client.force_login(world.editor)

        client.post(_url("studio:routines_toggle", world, routine_id=routine.pk))
        routine.refresh_from_db()
        assert not routine.enabled
        before = routine.next_run_at
        client.post(_url("studio:routines_toggle", world, routine_id=routine.pk))
        routine.refresh_from_db()
        assert routine.enabled and routine.next_run_at >= before

        response = client.post(_url("studio:routines_run_now", world, routine_id=routine.pk), follow=True)
        assert "Started" in response.content.decode()
        routine.refresh_from_db()
        assert routine.status == Routine.Status.RUNNING and the_job(routine).input["kind"] == "routine"
        response = client.post(_url("studio:routines_run_now", world, routine_id=routine.pk), follow=True)
        assert routines.ALREADY_RUNNING in response.content.decode()
        assert len(jobs) == 1

        client.post(_url("studio:routines_delete", world, routine_id=routine.pk))
        assert not Routine.objects.filter(pk=routine.pk).exists()
        assert AgencyJob.objects.count() == 1  # the work it started is not undone
        assert_nothing_approved(world.workspace)

    def test_controls_return_to_the_page_they_were_pressed_on(self, client, world):
        routine = make_routine(world, user=world.editor)
        client.force_login(world.editor)
        home = _url("studio:index", world)
        response = client.post(_url("studio:routines_toggle", world, routine_id=routine.pk), {"next": home})
        assert response.status_code == 302 and response["Location"] == home
        response = client.post(
            _url("studio:routines_toggle", world, routine_id=routine.pk), {"next": "https://evil.example/x"}
        )
        assert response["Location"] == _url("studio:routines", world)

    def test_run_now_is_rate_limited(self, client, world, settings, manager_agent, jobs):
        settings.RATELIMIT_ENABLE = True
        routine = make_routine(world, user=world.editor)
        client.force_login(world.editor)
        codes = [
            client.post(_url("studio:routines_run_now", world, routine_id=routine.pk)).status_code for _ in range(11)
        ]
        assert codes[:10] == [302] * 10 and codes[10] == 403

    def test_the_page_passes_the_accessibility_sweep(self, client, world):
        from apps.common.tests.test_a11y_sweep import FAINT_TEXT, _Audit

        make_routine(world, user=world.editor, title="Mornings")
        make_routine(world, user=world.owner, title="Owner's", enabled=False)
        client.force_login(world.owner)

        html = client.get(_url("studio:routines", world)).content.decode()

        audit = _Audit()
        audit.feed(html)
        audit.finish()
        assert audit.unnamed_buttons == [] and audit.unnamed_controls == []
        assert [m.group(3) for m in FAINT_TEXT.finditer(html) if m.group(3).strip() not in ("•", "·", "&bull;")] == []


class TestPermissions:
    @pytest.fixture
    def client_user(self, world):
        user = world.viewer.__class__.objects.create_user(
            email="client@example.com", password="pw-12345678", name="Client", tos_accepted_at=timezone.now()
        )
        WorkspaceMembership.objects.create(user=user, workspace=world.workspace, workspace_role="client")
        return user

    def test_clients_and_viewers_get_nothing(self, client, world, client_user):
        routine = make_routine(world)
        for person in (client_user, world.viewer):
            client.force_login(person)
            assert client.get(_url("studio:routines", world)).status_code == 403
            assert client.post(_url("studio:routines_create", world), {"suggestion": "morning"}).status_code == 403
            for name in ("routines_toggle", "routines_run_now", "routines_delete"):
                assert client.post(_url(f"studio:{name}", world, routine_id=routine.pk)).status_code == 403
        assert Routine.objects.count() == 1 and Routine.objects.get().enabled

    def test_anonymous_people_are_sent_to_log_in(self, client, world):
        response = client.get(_url("studio:routines", world))
        assert response.status_code == 302 and "login" in response["Location"]

    def test_the_creator_and_a_manager_can_delete_or_pause_but_another_editor_cannot(self, client, world):
        other_editor = world.viewer.__class__.objects.create_user(
            email="ed2@example.com", password="pw-12345678", name="Ed", tos_accepted_at=timezone.now()
        )
        WorkspaceMembership.objects.create(user=other_editor, workspace=world.workspace, workspace_role="editor")
        routine = make_routine(world, user=world.editor)

        client.force_login(other_editor)
        assert client.post(_url("studio:routines_toggle", world, routine_id=routine.pk)).status_code == 403
        assert client.post(_url("studio:routines_delete", world, routine_id=routine.pk)).status_code == 403
        routine.refresh_from_db()
        assert routine.enabled

        client.force_login(world.owner)
        assert client.post(_url("studio:routines_toggle", world, routine_id=routine.pk)).status_code == 302
        routine.refresh_from_db()
        assert not routine.enabled

        client.force_login(world.editor)
        assert client.post(_url("studio:routines_delete", world, routine_id=routine.pk)).status_code == 302
        assert not Routine.objects.exists()

        routine = make_routine(world, user=world.editor)
        client.force_login(world.owner)
        assert client.post(_url("studio:routines_delete", world, routine_id=routine.pk)).status_code == 302
        assert not Routine.objects.exists()

    def test_can_change_in_code(self, world):
        routine = make_routine(world, user=world.editor)
        assert routines.can_change(routine, world.editor, {})
        assert routines.can_change(routine, world.owner, {"manage_workspace_settings": True})
        assert not routines.can_change(routine, world.owner, {"manage_workspace_settings": False})
        assert not routines.can_change(routine, None, {"manage_workspace_settings": True})


class TestIsolation:
    @pytest.fixture
    def elsewhere(self, world):
        from apps.workspaces.models import Workspace

        other = Workspace.objects.create(organization=world.org, name="Other", timezone="Asia/Kolkata")
        WorkspaceMembership.objects.create(user=world.owner, workspace=other, workspace_role="owner")
        return other, routines.create(
            other, world.owner, instruction=INSTRUCTION, cadence="daily", weekday=None, time=dt.time(9, 0)
        )

    def test_another_workspaces_routine_is_not_found_from_here(self, client, world, elsewhere):
        _other, foreign = elsewhere
        client.force_login(world.owner)
        assert foreign.pk not in {r["routine"].pk for r in routines.rows(world.workspace)}
        html = client.get(_url("studio:routines", world)).content.decode()
        assert str(foreign.pk) not in html
        for name in ("routines_toggle", "routines_run_now", "routines_delete"):
            assert client.post(_url(f"studio:{name}", world, routine_id=foreign.pk)).status_code == 404
        foreign.refresh_from_db()
        assert foreign.enabled and foreign.status == Routine.Status.IDLE

    def test_a_run_posts_only_in_its_own_workspace(self, world, elsewhere, manager_agent, jobs):
        other, foreign = elsewhere
        due(foreign)
        due(make_routine(world))

        assert routines.run_due(now=WEDNESDAY) == 2

        by_workspace = {job.workspace_id: job for job in AgencyJob.objects.all()}
        assert set(by_workspace) == {world.workspace.pk, other.pk}
        assert by_workspace[other.pk].conversation.workspace == other
        assert by_workspace[world.workspace.pk].conversation.workspace == world.workspace
        assert [r["routine"].pk for r in routines.rows(other)] == [foreign.pk]


# ---------------------------------------------------------------------------
# Rows for Home
# ---------------------------------------------------------------------------


def test_rows_are_compact_dicts_on_first_soonest_first(world):
    soon = make_routine(world, user=world.editor, cadence="daily", time=dt.time(23, 0), title="Soon")
    later = make_routine(world, user=world.owner, cadence="weekly", weekday=6, time=dt.time(23, 30), title="Sunday")
    paused = make_routine(world, user=world.owner, cadence="daily", time=dt.time(0, 5), enabled=False, title="Off")
    Routine.objects.filter(pk=soon.pk).update(next_run_at=timezone.now() + dt.timedelta(hours=1))
    Routine.objects.filter(pk=later.pk).update(next_run_at=timezone.now() + dt.timedelta(days=2))

    rows = routines.rows(world.workspace, limit=3, viewer=world.editor, perms={})

    assert [row["title"] for row in rows] == ["Soon", "Sunday", "Off"]
    assert [row["can_change"] for row in rows] == [True, False, False]
    assert rows[0]["next_run_words"] and rows[2]["next_run_words"] == "" and not rows[2]["enabled"]
    assert rows[0]["last_result"] == "Hasn't run yet" and rows[0]["cadence_words"] == "Every day at 23:00"
    assert {"id", "routine", "status", "running", "needs_attention", "is_briefing", "created_by_name"} <= set(rows[0])
    assert routines.rows(world.workspace, limit=1)[0]["title"] == "Soon"
    assert paused.pk in {row["routine"].pk for row in routines.rows(world.workspace)}


# ---------------------------------------------------------------------------
# Autopilot waits for the provider instead of failing
# ---------------------------------------------------------------------------


class TestProviderGate:
    FRIDAY = dt.datetime(2026, 10, 16, 17, 30, tzinfo=IST)

    def test_the_weekly_plan_is_skipped_with_a_set_up_note_and_recovers(self, world, monkeypatch, settings):
        install_fake_agency(monkeypatch)
        agency_settings(world)
        settings.ANTHROPIC_API_KEY = ""

        assert autopilot.plan_due_workspaces(now=self.FRIDAY) == 0

        week = AutopilotWeek.objects.get()
        assert week.status == AutopilotWeek.Status.SKIPPED and week.note == autopilot.PROVIDER_PAUSED
        assert "API_KEY" not in week.note and not AgencyJob.objects.exists()

        settings.ANTHROPIC_API_KEY = "sk-ant-test"
        assert autopilot.plan_due_workspaces(now=self.FRIDAY) == 1
        week.refresh_from_db()
        assert week.status == AutopilotWeek.Status.PLANNING and week.job is not None

    def test_a_queued_plan_waits_for_the_provider_then_resumes(self, world, monkeypatch, settings):
        from apps.studio.tests.test_insights import drive as drive_job

        agency = install_fake_agency(monkeypatch)
        row = agency_settings(world)
        outcome = autopilot.plan_week(row, autopilot.next_week_start(world.workspace, self.FRIDAY))
        job = outcome.week.job
        settings.ANTHROPIC_API_KEY = ""

        engine.run_step(str(job.pk), job.revision, job.stage)

        job.refresh_from_db()
        assert job.status == AgencyJob.Status.QUEUED and job.error == autopilot.PROVIDER_PAUSED
        assert not job.runs.exists() and autopilot.resume_paused_jobs() == 0

        settings.ANTHROPIC_API_KEY = "sk-ant-test"
        assert autopilot.resume_paused_jobs() == 1
        assert drive_job(job).status == AgencyJob.Status.DONE
        assert len(agency.calls["planner"]) == 1
        assert_nothing_approved(world.workspace)

    def test_a_persons_own_request_is_not_held_by_the_gate(self, world, settings):
        settings.ANTHROPIC_API_KEY = ""
        assert autopilot.automatic_work_blocker(world.workspace) == ""
        job = AgencyJob.objects.create(workspace=world.workspace, kind=AgencyJob.Kind.CHAT)
        assert autopilot.automatic_work_blocker(world.workspace, job=job) == ""


# ---------------------------------------------------------------------------
# Integration: the chat action, the card, and Home
# ---------------------------------------------------------------------------


def _staff_membership(world, user):
    return WorkspaceMembership.objects.get(workspace=world.workspace, user=user)


class TestChatAction:
    """ "Every weekday at 8:30 tell me what's waiting" in the thread becomes a routine, switched off."""

    def test_set_routine_is_offered_to_staff_in_internal_threads_only(self, world):
        internal = chat.general_conversation(world.workspace, created_by=world.editor)
        client_thread = chat.general_conversation(world.workspace, audience=Conversation.Audience.CLIENT)
        target = chat_job.Target()

        assert "set_routine" in chat_job.allowed_actions(_staff_membership(world, world.editor), internal, target)
        assert "set_routine" in chat_job.allowed_actions(_staff_membership(world, world.owner), internal, target)
        assert "set_routine" not in chat_job.allowed_actions(
            _staff_membership(world, world.editor), client_thread, target
        )
        assert "set_routine" not in chat_job.allowed_actions(_staff_membership(world, world.viewer), internal, target)
        assert "set_routine" in client_roles.ACTION_GUIDE and "schedule" in client_roles.ACTION_GUIDE["set_routine"]

    def test_the_manager_proposes_a_routine_and_the_person_turns_it_on_from_the_card(
        self, client, world, manager_agent, jobs
    ):
        manager_agent.action = "set_routine"
        manager_agent.reply = "Every weekday at 08:30 I'll tell you what's waiting. Turn it on when you're ready."
        manager_agent.routine_instruction = "Tell me what is waiting for me today."
        manager_agent.routine_cadence = "weekdays"
        manager_agent.routine_weekday = -1
        manager_agent.routine_time = "08:30"
        conversation = chat.general_conversation(world.workspace, created_by=world.editor)

        posted = chat.post_message(conversation, world.editor, "Every weekday at 8:30 tell me what's waiting")
        job = drive(posted.job)

        assert "set_routine" in manager_agent.calls[0]["allowed_actions"]
        routine = Routine.objects.get(workspace=world.workspace)
        assert routine.created_by == world.editor and routine.conversation == conversation
        assert not routine.enabled and routine.cadence == Routine.Cadence.WEEKDAYS and routine.time == dt.time(8, 30)
        assert routine.instruction == "Tell me what is waiting for me today."
        assert job.result["routine_id"] == str(routine.pk) and job.result["routine_cadence"] == "Weekdays at 08:30"
        reply = Message.objects.get(job=job, author_kind=Message.AuthorKind.AGENT)
        assert reply.action == "set_routine" and reply.action_status == "" and "Turn it on" in reply.body
        assert not AgencyJob.objects.filter(kind=AgencyJob.Kind.CHAT).exclude(pk=job.pk).exists()

        client.force_login(world.editor)
        html = client.get(_url("studio:thread", world) + f"?c={conversation.pk}").content.decode()
        toggle = _url("studio:routines_toggle", world, routine_id=routine.pk)
        assert f'data-routine-card="{routine.pk}"' in html and 'data-routine-state="proposed"' in html
        assert "Routine proposed" in html and "Weekdays at 08:30" in html and ">Turn on<" in html
        assert toggle in html and "Nothing runs until it is on." in html

        response = client.post(toggle, {"next": _url("studio:thread", world) + f"?c={conversation.pk}"})
        assert response.status_code == 302 and response["Location"].endswith(f"?c={conversation.pk}")
        routine.refresh_from_db()
        assert routine.enabled and routine.next_run_at is not None
        html = client.get(_url("studio:thread", world) + f"?c={conversation.pk}").content.decode()
        assert 'data-routine-state="on"' in html and "Routine on" in html and ">Turn on<" not in html
        assert_nothing_approved(world.workspace)

    def test_on_home_the_card_returns_to_home(self, client, world, manager_agent, jobs):
        manager_agent.action = "set_routine"
        manager_agent.routine_instruction = "Draft replies to new comments."
        manager_agent.routine_cadence = "weekly"
        manager_agent.routine_weekday = 0
        manager_agent.routine_time = "09:00"
        conversation = chat.general_conversation(world.workspace, created_by=world.owner)
        drive(chat.post_message(conversation, world.owner, "Every Monday at 9 draft replies to new comments").job)
        routine = Routine.objects.get()
        assert routine.cadence == Routine.Cadence.WEEKLY and routine.weekday == 0
        client.force_login(world.owner)

        response = client.get(_url("studio:index", world))
        home = response.content.decode()

        assert 'data-routine-state="proposed"' in home
        assert f'name="next" value="{_url("studio:index", world)}"' in home
        # The panel polls with ?home=1 while the manager answers, so a refreshed card keeps Home as its return address.
        assert response.context["thread"]["home_panel"] and response.context["thread"]["messages_url"].endswith(
            "?home=1"
        )
        polled = client.get(
            reverse(
                "studio:thread_messages",
                kwargs={"workspace_id": world.workspace.id, "conversation_id": conversation.pk},
            )
            + "?home=1"
        ).content.decode()
        assert f'name="next" value="{_url("studio:index", world)}"' in polled

    def test_a_message_sent_from_home_keeps_the_panel_on_home(self, client, world, manager_agent, jobs):
        """Send swaps the panel back in: it must stay Home's, or the next card's Turn on leaves Home."""
        conversation = chat.general_conversation(world.workspace, created_by=world.owner)
        client.force_login(world.owner)
        home = client.get(_url("studio:index", world)).content.decode()
        assert '<input type="hidden" name="home" value="1">' in home
        send = reverse(
            "studio:thread_send", kwargs={"workspace_id": world.workspace.id, "conversation_id": conversation.pk}
        )

        swapped = client.post(
            send,
            {"body": "Every Monday at 9 draft replies to new comments", "kind": "question", "home": "1"},
            HTTP_HX_REQUEST="true",
        )

        assert swapped.status_code == 200
        assert swapped.context["thread"]["home_panel"]
        assert swapped.context["thread"]["messages_url"].endswith("?home=1")
        assert '<input type="hidden" name="home" value="1">' in swapped.content.decode()
        # Without JavaScript the form posts plainly and comes back to Home, not the thread page.
        plain = client.post(send, {"body": "And a reel about the clubhouse", "kind": "question", "home": "1"})
        assert plain.status_code == 302 and plain["Location"] == _url("studio:index", world)
        # The thread page itself is not Home: no flag, and it returns to itself.
        page = client.post(send, {"body": "One more thing", "kind": "question", "full": "1"})
        assert page.status_code == 302 and "/studio/thread/" in page["Location"]

    def test_someone_else_sees_the_card_without_the_button(self, client, world, manager_agent, jobs):
        manager_agent.action = "set_routine"
        manager_agent.routine_instruction = "Tell me what is waiting."
        manager_agent.routine_cadence = "daily"
        manager_agent.routine_time = "08:30"
        conversation = chat.general_conversation(world.workspace, created_by=world.editor)
        drive(chat.post_message(conversation, world.editor, "Every day at 8:30 tell me what's waiting").job)
        routine = Routine.objects.get()

        client.force_login(world.manager)  # neither the author nor a settings manager
        html = client.get(_url("studio:thread", world) + f"?c={conversation.pk}").content.decode()
        assert "Routine proposed" in html and ">Turn on<" not in html and "All routines" in html

        client.force_login(world.owner)  # manages the workspace's settings
        html = client.get(_url("studio:thread", world) + f"?c={conversation.pk}").content.decode()
        assert _url("studio:routines_toggle", world, routine_id=routine.pk) in html

    def test_a_time_the_manager_could_not_read_declines_in_one_sentence(self, world, manager_agent, jobs):
        manager_agent.action = "set_routine"
        manager_agent.routine_instruction = "Tell me what is waiting."
        manager_agent.routine_cadence = "weekdays"
        manager_agent.routine_time = "later"
        conversation = chat.general_conversation(world.workspace, created_by=world.editor)

        job = drive(chat.post_message(conversation, world.editor, "Tell me what's waiting, later every day").job)

        assert not Routine.objects.exists() and "routine_id" not in job.result
        reply = Message.objects.get(job=job, author_kind=Message.AuthorKind.AGENT)
        assert reply.action_status == Message.ActionStatus.DECLINED
        assert reply.body == f"{chat_job.ROUTINE_NOT_MADE} Choose the time of day."

    def test_a_private_telegram_chats_routine_runs_in_the_general_thread(self, world, manager_agent, jobs):
        """The model's choice is validated in code: a routine never binds to a private thread."""
        private = Conversation.objects.create(
            workspace=world.workspace, audience=Conversation.Audience.INTERNAL, is_private=True, title="Private"
        )
        manager_agent.action = "set_routine"
        manager_agent.routine_instruction = "Tell me what is waiting."
        manager_agent.routine_cadence = "daily"
        manager_agent.routine_time = "08:30"
        out = manager_agent(None).output
        trigger = Message(conversation=private, author=world.editor, author_kind=Message.AuthorKind.STAFF, body="x")

        outcome = chat_job._set_routine(private, world.editor, _staff_membership(world, world.editor), out, trigger, "")

        routine = Routine.objects.get(pk=outcome.result["routine_id"])
        assert routine.conversation_id is None


class TestHomeRows:
    def test_home_shows_the_next_three_routines_with_a_link_to_all(self, client, world):
        for index in range(4):
            make_routine(world, user=world.editor, time=dt.time(7 + index, 0), title=f"Routine {index}")
        client.force_login(world.editor)

        html = client.get(_url("studio:index", world)).content.decode()

        assert "data-home-routines" in html and _url("studio:routines", world) in html
        assert sum(f"Routine {index}" in html for index in range(4)) == 3  # the next three, whatever the clock says
        assert html.index("data-home-thread") < html.index("data-home-routines") < html.index("data-home-recent")
        assert "All routines" in html and "Run now" in html

    def test_without_routines_home_says_how_to_start_one(self, client, world):
        """The example is a task the manager carries out itself; the morning briefing is its own one tap."""
        from html import unescape

        client.force_login(world.editor)
        html = unescape(client.get(_url("studio:index", world)).content.decode())
        assert "data-home-routines-empty" in html and _url("studio:routines", world) in html
        assert "every Monday at 9 draft a market update" in html and "tell me what's waiting" not in html
        assert "data-home-morning-briefing" in html and 'name="suggestion" value="morning"' in html

        response = client.post(
            _url("studio:routines_create", world), {"suggestion": "morning", "next": _url("studio:index", world)}
        )

        assert response.status_code == 302 and response["Location"] == _url("studio:index", world)
        routine = Routine.objects.get()
        assert routine.kind == Routine.Kind.BRIEFING and routine.enabled and routine.time == dt.time(8, 30)
        home = client.get(_url("studio:index", world)).content.decode()
        assert "data-home-morning-briefing" not in home and "Morning briefing" in home

    def test_a_viewer_gets_no_routines_section(self, client, world):
        make_routine(world, user=world.editor, title="Mornings")
        client.force_login(world.viewer)
        html = client.get(_url("studio:index", world)).content.decode()
        assert "data-home-routines" not in html and "Mornings" not in html
