"""Conversation first: the confirm button arrives by itself, and a person steers tasks and messages from the chat."""

import pytest
from django.test import TestCase

from apps.studio import engine
from apps.studio.models import AgencyJob, Message, StudioBrief
from apps.studio.roles import client as client_roles
from apps.studio.tests.test_guided_chat import GuidedManager
from apps.telegram import conversations, notifications, provisioning, weekly
from apps.telegram.models import TelegramChat, TelegramDelivery
from apps.telegram.tests.test_conversations import hub, send  # noqa: F401

pytestmark = pytest.mark.django_db


def _private(hub, role="owner"):  # noqa: F811
    return provisioning.private_chat(hub.connection, hub.links[role])


def test_brief_card_with_confirm_button_is_attached_to_the_mirrored_intake(hub, monkeypatch):  # noqa: F811
    from apps.studio import guards
    from apps.telegram import tasks

    deferred = []
    monkeypatch.setattr(tasks, "send_brief_card", lambda message_id, chat_id: deferred.append((message_id, chat_id)))
    monkeypatch.setattr(client_roles, "account_manager", GuidedManager())
    bound = _private(hub)
    result = send(hub, "/brief Explain shares", role="owner", bound=bound)
    job = AgencyJob.objects.get(pk=result["job_id"])
    with TestCase.captureOnCommitCallbacks(execute=False):
        engine.run_step(str(job.pk), job.revision, job.stage)
    reply = Message.objects.get(job=job, author_kind="agent")
    # The worker's mirror runs inside agency work: it defers the card to a task instead of issuing a button.
    with guards.agent_work("chat job answer"):
        assert notifications.mirror_message(reply.pk) == 0
    assert deferred == [(str(reply.pk), str(bound.pk))]
    assert not TelegramDelivery.objects.filter(source_key__contains=str(reply.pk)).exists()
    assert notifications.brief_card(reply.pk, bound.pk) == 1
    row = TelegramDelivery.objects.get(source_key=f"conversation:{bound.conversation_id}:message:{reply.pk}:part:0")
    button = row.payload["reply_markup"]["inline_keyboard"][0][0]
    # The same tap as the web card, with the same name.
    assert button["text"] == "Go ahead" and button["callback_data"].startswith("tg:a:")
    assert "Send /brief" not in row.payload["text"]
    assert "Go ahead confirms the brief and its facts" in row.payload["text"]
    assert "Nothing publishes without your approval" in row.payload["text"]
    before = TelegramDelivery.objects.count()
    assert notifications.brief_card(reply.pk, bound.pk) == 1 and TelegramDelivery.objects.count() == before
    assert not StudioBrief.objects.exists()


def test_mirror_outside_agency_work_issues_the_button_inline_and_only_to_the_requester(hub, monkeypatch):  # noqa: F811
    monkeypatch.setattr(client_roles, "account_manager", GuidedManager())
    bound = _private(hub)
    result = send(hub, "/brief Explain shares", role="owner", bound=bound)
    job = AgencyJob.objects.get(pk=result["job_id"])
    engine.run_step(str(job.pk), job.revision, job.stage)
    reply = Message.objects.get(job=job, author_kind="agent")
    TelegramDelivery.objects.all().delete()
    assert notifications.mirror_message(reply.pk) == 1
    row = TelegramDelivery.objects.get(chat=bound)
    assert row.payload["reply_markup"]["inline_keyboard"][0][0]["text"] == "Go ahead"
    other = TelegramChat.objects.create(
        connection=hub.connection,
        chat_id=hub.links["editor"].telegram_user_id,
        chat_type="private",
        audience="private",
        private_user=hub.users["editor"],
        conversation=bound.conversation,
    )
    assert notifications._confirmation_for(reply, other) is False


def test_started_draft_mirrors_with_an_open_progress_link(hub):  # noqa: F811
    bound = _private(hub)
    job = AgencyJob.objects.create(
        workspace=hub.ws, conversation=bound.conversation, kind="chat", requested_by=hub.users["owner"], status="done"
    )
    brief = StudioBrief.objects.create(workspace=hub.ws, author=hub.users["owner"], idea="Started", job=job)
    reply = Message.objects.create(
        conversation=bound.conversation,
        job=job,
        author_kind="agent",
        agent="account_manager",
        action="new_post",
        body="The confirmed brief is with the creative team.",
    )
    job.result = {"brief_id": str(brief.pk), "message_id": str(reply.pk), "awaiting_confirmation": False}
    job.save(update_fields=["result"])
    assert notifications.mirror_message(reply.pk) == 1
    row = TelegramDelivery.objects.get(chat=bound)
    button = row.payload["reply_markup"]["inline_keyboard"][0][0]
    assert button["text"] == "Open progress" and button["url"].endswith(f"/{brief.pk}/")
    assert "The team started." in row.payload["text"]


def test_mute_and_unmute_change_only_the_switch_and_keep_the_pairing_epoch(hub):  # noqa: F811
    link = hub.links["owner"]
    before = link.updated_at
    assert "Muted" in send(hub, "/mute", role="owner")["text"]
    link.refresh_from_db()
    assert link.notify_needs_you is False and link.updated_at == before
    assert "Unmuted" in send(hub, "/unmute", role="owner")["text"]
    link.refresh_from_db()
    assert link.notify_needs_you is True and link.updated_at == before
    assert "/mute" in send(hub, "/help")["text"]


def test_pause_uses_the_reviewed_control_and_private_work_points_to_stop(hub, monkeypatch):  # noqa: F811
    from apps.telegram import workflow_bridge

    monkeypatch.setattr(workflow_bridge, "job_control_event", lambda *a, **k: 0)
    assert "Nothing of yours is running" in send(hub, "/pause", bound=hub.team_chat)["text"]
    send(hub, "/brief Team request", bound=hub.team_chat)
    job = AgencyJob.objects.get()
    response = send(hub, "/pause", bound=hub.team_chat)
    assert response["text"].startswith("Paused")
    job.refresh_from_db()
    assert job.status == "cancelled" and job.state["_opendots_control"]["paused"] is True
    resume = send(hub, "/resume", bound=hub.team_chat)
    assert "Open it to resume" in resume["text"]
    assert resume["reply_markup"]["inline_keyboard"][0][0]["url"].endswith(f"/jobs/{job.pk}/")
    job.refresh_from_db()
    assert job.status == "cancelled" and AgencyJob.objects.count() == 1
    bound = _private(hub)
    send(hub, "/brief Private request", role="owner", bound=bound)
    response = send(hub, "/pause", role="owner", bound=bound)
    assert "/stop" in response["text"] and AgencyJob.objects.filter(status="queued").count() == 1


def test_retry_points_at_the_failed_task_and_clients_cannot_control(hub):  # noqa: F811
    send(hub, "/brief Team request", bound=hub.team_chat)
    job = AgencyJob.objects.get()
    AgencyJob.objects.filter(pk=job.pk).update(status="failed", error="Stopped.")
    response = send(hub, "/retry", bound=hub.team_chat)
    assert "Open it to retry" in response["text"] and f"/jobs/{job.pk}/" in str(response.get("reply_markup"))
    assert "Only a team member" in send(hub, "/pause", role="client")["text"]
    job.refresh_from_db()
    assert job.status == "failed"


def test_task_controls_in_a_client_group_are_refused_and_name_no_internal_task(hub, monkeypatch):  # noqa: F811
    """A team member's /pause in the client group neither acts on nor echoes their internal-thread task."""
    from apps.telegram import workflow_bridge

    monkeypatch.setattr(workflow_bridge, "job_control_event", lambda *a, **k: 0)
    send(hub, "/brief SECRET internal plan for the team", bound=hub.team_chat)
    job = AgencyJob.objects.get()
    assert job.status == "queued" and "SECRET" in job.title
    for command in ("/pause", "/resume", "/retry"):
        response = send(hub, command, bound=hub.client_chat)
        assert "private chat or the team group" in response["text"] and "reply_markup" not in response
        assert "SECRET" not in response["text"] and "Paused" not in response["text"]
    job.refresh_from_db()
    assert job.status == "queued" and "_opendots_control" not in (job.state or {})
    # The same person in the team group is still answered, and the task is still theirs to pause.
    assert send(hub, "/pause", bound=hub.team_chat)["text"].startswith("Paused")


def test_week_evidence_shows_the_sources_without_a_button(hub, monkeypatch):  # noqa: F811
    monkeypatch.setattr(weekly, "queue_week_plan", lambda *a, **k: {"needs_confirmation": True, "analysis": {}})
    monkeypatch.setattr(weekly, "analysis_text", lambda preview: "Website excerpt and captions")
    response = send(hub, "/week evidence", role="owner", bound=hub.team_chat)
    assert response["text"] == "Website excerpt and captions" and "reply_markup" not in response
    assert "private or internal" in send(hub, "/week evidence", role="owner")["text"]


def test_pairing_welcome_and_replies_are_short(hub, monkeypatch):  # noqa: F811
    monkeypatch.setattr(provisioning, "consume_pairing_message", lambda *a, **k: hub.links["owner"])
    welcome = send(hub, "/start abcdefghijklmnopqrstuvwxyz", role="owner")
    assert welcome["text"] == conversations.PAIRED_WELCOME and "Nothing publishes" in welcome["text"]
    assert "does not approve" not in send(hub, "/status")["text"]
    assert send(hub, "/help")["text"].count("\n") < 15
    # A client's help lists only what a client can do; team controls stay out of the client group.
    client_help = send(hub, "/help", role="client")["text"]
    assert "/post" in client_help and "sign off" in client_help
    for staff_only in ("/approvals", "/pause", "/mute", "/week prepare"):
        assert staff_only not in client_help
