"""Private transport transcripts never broadcast through ordinary app/email notices."""

import pytest
from django.test import TestCase
from django.utils import timezone

from apps.studio import chat
from apps.studio.models import Conversation, Message
from apps.telegram import provisioning
from apps.telegram.models import TelegramChat
from apps.telegram.tests.test_conversations import hub as hub

_NOTIFY_STAFF = chat.notify_staff
_NOTIFY_CLIENT_MESSAGE = chat.notify_staff_of_client_message
_NOTIFY_CLIENT_REPLY = chat.notify_clients_of_reply


@pytest.mark.parametrize("audience", ["client", "internal"])
@pytest.mark.parametrize("lifecycle", ["active", "inactive", "orphan"])
def test_private_transcript_and_handoff_never_notify_workspace_recipients(hub, monkeypatch, audience, lifecycle):
    conversation = Conversation.objects.create(
        workspace=hub.ws,
        audience=audience,
        is_private=True,
        title="Private transport history",
        created_by=hub.users["client" if audience == "client" else "owner"],
    )
    if lifecycle != "orphan":
        TelegramChat.objects.create(
            connection=hub.connection,
            chat_id=900900,
            chat_type="private",
            audience="private",
            conversation=conversation,
            private_user=conversation.created_by,
            is_active=lifecycle == "active",
        )
    message = Message.objects.create(
        conversation=conversation,
        author=conversation.created_by,
        author_kind="client" if audience == "client" else "staff",
        body="PRIVATE SENSITIVE TRANSCRIPT",
    )
    calls = []
    monkeypatch.setattr("apps.notifications.engine.notify", lambda *a, **k: calls.append(k))
    monkeypatch.setattr(chat, "notify_staff", _NOTIFY_STAFF)
    assert _NOTIFY_STAFF(conversation, title="Private handoff", body=message.body) == 0
    assert _NOTIFY_CLIENT_MESSAGE(conversation, message) == 0
    assert _NOTIFY_CLIENT_REPLY(conversation, only=hub.users["client"]) == 0
    assert calls == []


def test_real_private_client_post_does_not_forward_snippet_after_commit(hub, monkeypatch):
    bound = provisioning.private_chat(hub.connection, hub.links["client"])
    calls = []
    monkeypatch.setattr("apps.notifications.engine.notify", lambda *a, **k: calls.append(k))
    monkeypatch.setattr(chat, "notify_staff", _NOTIFY_STAFF)
    monkeypatch.setattr(chat, "notify_staff_of_client_message", _NOTIFY_CLIENT_MESSAGE)
    with TestCase.captureOnCommitCallbacks(execute=True):
        posted = chat.post_message(
            bound.conversation,
            hub.users["client"],
            "PRIVATE CLIENT QUESTION",
            telegram_context={"chat_id": str(bound.pk), "user_link_id": str(hub.links["client"].pk)},
        )
    assert posted.job is not None and calls == []


def test_cached_false_private_marker_does_not_bypass_notification_suppression(hub, monkeypatch):
    conversation = Conversation.objects.create(workspace=hub.ws, audience="client", is_private=False)
    message = Message.objects.create(
        conversation=conversation, author=hub.users["client"], author_kind="client", body="PRIVATE"
    )
    Conversation.objects.filter(pk=conversation.pk).update(is_private=True)
    calls = []
    monkeypatch.setattr("apps.notifications.engine.notify", lambda *a, **k: calls.append(k))
    monkeypatch.setattr(chat, "notify_staff", _NOTIFY_STAFF)
    assert conversation.is_private is False
    assert _NOTIFY_CLIENT_MESSAGE(conversation, message) == 0
    assert _NOTIFY_CLIENT_REPLY(conversation, only=hub.users["client"]) == 0
    assert calls == []


def test_shared_client_thread_still_notifies_its_permitted_recipients(hub, monkeypatch):
    conversation = hub.client_chat.conversation
    message = Message.objects.create(
        conversation=conversation, author=hub.users["client"], author_kind="client", body="Shared client question"
    )
    conversation.last_message_at = timezone.now()
    conversation.save(update_fields=["last_message_at"])
    calls = []
    monkeypatch.setattr("apps.notifications.engine.notify", lambda *a, **k: calls.append(k))
    monkeypatch.setattr(chat, "notify_staff", _NOTIFY_STAFF)
    assert _NOTIFY_CLIENT_MESSAGE(conversation, message) == 1
    assert calls and all("Shared client question" in call["body"] for call in calls)


@pytest.mark.parametrize("role", ["owner", "client"])
def test_private_worker_handoff_requires_persons_own_group_share_without_private_reply_promise(hub, monkeypatch, role):
    from apps.studio import engine
    from apps.studio.models import AgencyJob
    from apps.studio.roles import client as client_roles
    from apps.studio.tests.test_guided_chat import GuidedManager
    from apps.telegram import conversations
    from apps.telegram.tests.test_conversations import payload

    bound = provisioning.private_chat(hub.connection, hub.links[role])
    manager = GuidedManager(action="escalate", creative_brief=None) if role == "owner" else GuidedManager()
    monkeypatch.setattr(client_roles, "account_manager", manager)
    notifications = []
    monkeypatch.setattr(chat, "notify_staff", lambda *a, **k: notifications.append(k))
    result = conversations.handle_message(
        hub.connection, payload(hub, "/brief Help with a campaign", role=role, bound=bound)
    )
    job = AgencyJob.objects.get(pk=result["job_id"])
    engine.run_step(str(job.pk), job.revision, job.stage)
    reply = Message.objects.get(job=job, author_kind="agent")
    expected_group = "client group" if role == "client" else "internal team group"
    assert f"Share the request yourself in the intended {expected_group}" in reply.body
    assert "not forwarded to the agency" in reply.body
    assert "A person from the team will reply here" not in reply.body
    assert "send /brief here" not in reply.body
    assert notifications == []
