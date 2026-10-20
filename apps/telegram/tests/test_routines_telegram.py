"""Routines from the phone: /routines lists them, a stuck routine reaches the inbox, the briefing is one.

The end-to-end check here is the one the design asks for: a due briefing
routine (area C) runs the code-built briefing (area B) and a paired approver
gets both the in-app notice and a queued Telegram delivery.
"""

import datetime as dt
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.notifications.models import Notification
from apps.studio import routines
from apps.studio.models import Routine, RoutineRun
from apps.telegram import conversations, notifications, provisioning
from apps.telegram.models import TelegramDelivery
from apps.telegram.tests.test_conversations import hub, send  # noqa: F401
from apps.telegram.tests.test_inbox import NOON, agency, daytime  # noqa: F401

pytestmark = pytest.mark.django_db


def _buttons(row):
    return [button for line in row.payload["reply_markup"]["inline_keyboard"] for button in line]


# ---------------------------------------------------------------------------
# /routines
# ---------------------------------------------------------------------------


def test_routines_lists_the_teams_standing_instructions_with_a_link(hub):  # noqa: F811
    bound = provisioning.private_chat(hub.connection, hub.links["owner"])
    empty = send(hub, "/routines", role="owner", bound=bound)
    assert "Nothing runs on its own yet" in empty["text"]
    assert empty["reply_markup"]["inline_keyboard"][0][0]["text"] == "Open routines"
    assert f"/workspace/{hub.ws.pk}/studio/routines/" in empty["reply_markup"]["inline_keyboard"][0][0]["url"]

    routines.create(
        hub.ws,
        hub.users["owner"],
        instruction="Tell me what is waiting.",
        cadence="weekdays",
        weekday=None,
        time=dt.time(8, 30),
        title="Mornings",
    )
    paused = routines.create(
        hub.ws,
        hub.users["owner"],
        instruction="Plan the week.",
        cadence="weekly",
        weekday=0,
        time=dt.time(9, 0),
        title="Monday plan",
    )
    routines.set_enabled(paused, False)

    response = send(hub, "/routines", role="owner", bound=bound)

    assert response["text"].startswith("What runs on its own:")
    assert "• Mornings — weekdays at 08:30 · next " in response["text"]
    assert "• Monday plan — mondays at 09:00 · paused" in response["text"]
    assert response["reply_markup"]["inline_keyboard"][0][0]["text"] == "Open routines"
    assert "/routines" in send(hub, "/help", role="owner", bound=bound)["text"]
    assert ("routines", "What runs on its own, and when") in provisioning.BOT_COMMANDS


def test_routines_is_for_the_team_not_clients(hub):  # noqa: F811
    routines.create(hub.ws, hub.users["owner"], instruction="x", cadence="daily", weekday=None, time=dt.time(9, 0))
    response = send(hub, "/routines", role="client")
    assert "Routines are for the team" in response["text"] and "reply_markup" not in response
    assert "/routines" not in conversations.HELP_CLIENT


# ---------------------------------------------------------------------------
# A routine that needs a person reaches the manager inbox
# ---------------------------------------------------------------------------


def test_a_failed_routine_reaches_every_approvers_inbox_once(agency, django_capture_on_commit_callbacks):  # noqa: F811
    routine = routines.create(
        agency.ws,
        agency.users["lead"],
        instruction="Tell me what is waiting.",
        cadence="daily",
        weekday=None,
        time=dt.time(9, 0),
        title="Mornings",
    )
    run = RoutineRun.objects.create(routine=routine, started_at=timezone.now())

    with django_capture_on_commit_callbacks(execute=True):
        assert routines._notify_creator(routine, run, routines.INTERRUPTED)

    notice = Notification.objects.get(event_type="team_message", data__kind="routine")
    assert notice.user == agency.users["lead"] and notice.data["run_id"] == str(run.pk)
    rows = list(TelegramDelivery.objects.filter(source_key__startswith="inbox:routine:").select_related("chat"))
    assert {row.chat.private_user_id for row in rows} == {
        agency.users["lead"].pk,
        agency.users["backup"].pk,
        agency.users["approver"].pk,
    }
    for row in rows:
        assert row.payload["text"] == f"Routine “Mornings” needs you: {routines.INTERRUPTED}"
        assert [button["text"] for button in _buttons(row)] == ["Open routines"]
        assert _buttons(row)[0]["url"].endswith(f"/workspace/{agency.ws.pk}/studio/routines/")
    # The same run never reaches Telegram twice, and a second notice for it is not even recorded.
    notifications.notification_event(notice.pk)
    assert not routines._notify_creator(routine, run, routines.INTERRUPTED)
    assert TelegramDelivery.objects.filter(source_key__startswith="inbox:routine:").count() == 3


def test_a_routine_notice_for_another_workspace_is_dropped(agency):  # noqa: F811
    from apps.workspaces.models import Workspace

    other = Workspace.objects.create(organization=agency.org, name="Other")
    routine = routines.create(
        other, agency.users["lead"], instruction="x", cadence="daily", weekday=None, time=dt.time(9, 0)
    )
    notice = Notification.objects.create(
        user=agency.users["lead"],
        event_type="team_message",
        title="A routine needs you",
        body="The run failed.",
        data={"kind": "routine", "routine_id": str(routine.pk), "workspace_id": str(agency.ws.pk), "run_id": "r"},
    )
    assert notifications.notification_event(notice.pk) == 0
    assert not TelegramDelivery.objects.exists()


# ---------------------------------------------------------------------------
# The morning briefing is a routine
# ---------------------------------------------------------------------------


def test_a_due_briefing_routine_sends_the_briefing_to_paired_approvers(agency):  # noqa: F811
    routine = routines.suggestion(agency.ws, agency.users["lead"], "morning")
    assert routine.kind == Routine.Kind.BRIEFING and routine.enabled
    Routine.objects.filter(pk=routine.pk).update(next_run_at=NOON - timedelta(minutes=1))

    assert routines.run_due(now=NOON) == 1

    notes = Notification.objects.filter(event_type="daily_briefing")
    assert {note.user for note in notes} == {agency.users["lead"], agency.users["backup"], agency.users["approver"]}
    assert all(note.data["routine_id"] == str(routine.pk) and note.data["day"] == "2026-10-19" for note in notes)
    rows = list(TelegramDelivery.objects.filter(source_key__startswith="inbox:briefing:").select_related("chat"))
    assert {row.chat.private_user_id for row in rows} == {note.user_id for note in notes}
    assert all("Good morning" in row.payload["text"] for row in rows)
    assert [button["text"] for button in _buttons(rows[0])] == ["Open approvals", "Open Home"]
    routine.refresh_from_db()
    run = routine.runs.get()
    assert run.status == RoutineRun.Status.FINISHED and run.summary == routines.BRIEFING_SENT
    assert routine.status == Routine.Status.IDLE and routine.next_run_at > NOON
    assert not Notification.objects.filter(event_type="team_message", data__kind="routine").exists()
    # The next tick does nothing: the routine waits for its next time, and the day's briefing is already out.
    assert routines.run_due(now=NOON) == 0
    assert TelegramDelivery.objects.filter(source_key__startswith="inbox:briefing:").count() == 3
