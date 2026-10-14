"""Real web idea -> authenticated private receipt reply, with fresh worker authorization."""

import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.core.exceptions import PermissionDenied
from django.db import connection as db_connection
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.composer.models import PlatformPost, Post
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.notifications.models import Notification
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.studio import chat, customer_workflow, engine, opendots
from apps.studio.jobtypes import chat as chat_job
from apps.studio.models import AgencyJob, Conversation, Message, StudioBrief
from apps.telegram import notifications, outbox, provisioning, workflow_bridge
from apps.telegram.api import TelegramAPIError
from apps.telegram.models import (
    TelegramChat,
    TelegramDelivery,
    TelegramUpdate,
    TelegramUserLink,
    TelegramWorkflowPrompt,
)
from apps.telegram.processing import process_one
from apps.telegram.tests.test_webhooks import authenticated, create_hub

pytestmark = pytest.mark.django_db


@pytest.fixture
def hub(organization, user, monkeypatch):
    connection, group = create_hub(organization, user, monkeypatch)
    connection.webhook_status = "active"
    connection.save()
    OrgMembership.objects.create(organization=organization, user=user, org_role="owner")
    WorkspaceMembership.objects.create(workspace=connection.workspace, user=user, workspace_role="owner")
    link = TelegramUserLink.objects.create(connection=connection, user=user, telegram_user_id=99)
    private = provisioning.private_chat(connection, link)
    source = customer_workflow.save_idea(
        connection.workspace, user, request_id=uuid.uuid4(), idea="A launch campaign", telegram_updates=True
    )
    job = AgencyJob.objects.create(
        workspace=connection.workspace,
        conversation=source,
        kind="chat",
        stage="answer",
        status="done",
        requested_by=user,
    )
    message = Message.objects.create(
        conversation=source,
        job=job,
        author_kind="agent",
        agent="account_manager",
        action="new_post",
        body="PRIVATE cost/token/provider details that must never leave as a prompt",
    )
    job.result = {"message_id": str(message.pk), "creative_brief": {"topic": "Launch"}, "awaiting_confirmation": False}
    job.save(update_fields=["result"])
    api = Mock()
    api.call.return_value = {"message_id": 700, "chat": {"id": 99, "type": "private"}}
    monkeypatch.setattr(outbox, "BotAPI", Mock(return_value=api))
    monkeypatch.setattr(chat, "reply_refusal", lambda workspace: None)
    return connection, group, link, private, source, job, message, api


def queued(hub):
    assert workflow_bridge.queue_workflow_message(hub[6].pk) == 1
    return TelegramWorkflowPrompt.objects.get(source_message=hub[6])


def sent(hub):
    prompt = queued(hub)
    assert outbox.send_one(prompt.delivery_id) == "sent"
    prompt.refresh_from_db()
    return prompt


def incoming(hub, *, text="Audience: first-time homeowners", reply_id=700, update_id=40, **changes):
    message = {
        "message_id": 800,
        "chat": {"id": 99, "type": "private"},
        "from": {"id": 99, "is_bot": False},
        "text": text,
        "reply_to_message": {"message_id": reply_id, "text": "Copied text never authenticates a prompt"},
    }
    message.update(changes)
    row = TelegramUpdate.objects.create(
        connection=hub[0],
        update_id=update_id,
        payload=authenticated(hub[0], {"update_id": update_id, "message": message}),
    )
    return row


def continued(hub):
    prompt = sent(hub)
    row = incoming(hub)
    assert process_one(row.pk) == "processed"
    prompt.refresh_from_db()
    assert prompt.response_message_id is not None
    return prompt, AgencyJob.objects.get(input__message_id=str(prompt.response_message_id))


def test_complete_question_callback_receipt_reply_and_original_web_thread(hub, django_capture_on_commit_callbacks):
    source, source_job = hub[4:6]
    with django_capture_on_commit_callbacks(execute=True), transaction.atomic():
        message = chat.post_agent_message(source, "Actual intake question", job=source_job, action="new_post")
        source_job.result = {
            "message_id": str(message.pk),
            "creative_brief": {"topic": "Launch"},
            "awaiting_confirmation": False,
        }
        source_job.save(update_fields=["result"])
    prompt = TelegramWorkflowPrompt.objects.get(source_message=message)
    payload = prompt.delivery.payload
    assert "Before the team creates a draft" in payload["text"]
    assert "Reply to this message" in payload["text"]
    assert outbox.send_one(prompt.delivery_id) == "sent"
    row = incoming(hub)
    assert process_one(row.pk) == "processed"
    prompt.refresh_from_db()
    job = AgencyJob.objects.get(input__message_id=str(prompt.response_message_id))
    assert job.conversation_id == source.pk and prompt.response_message.conversation_id == source.pk
    assert prompt.response_message.job_id == job.pk
    assert workflow_bridge.workflow_member(job, source, hub[2].user).user_id == hub[2].user_id
    assert not TelegramChat.objects.filter(conversation=source).exists()
    source.refresh_from_db()
    assert source.is_private is False
    assert chat.web_conversations().filter(pk=source.pk).exists()
    assert not hub[3].conversation.messages.filter(body__contains="first-time homeowners").exists()
    assert prompt.response_message.action == "" and (job.input or {}).get("kind") == ""


def test_question_content_dedup_and_encryption_exclude_history_setup_and_costs(hub):
    prompt = queued(hub)
    assert workflow_bridge.queue_workflow_message(hub[6].pk) == 0
    text = prompt.delivery.payload["text"]
    assert all(word not in text for word in ["PRIVATE", "token", "provider", "cost", hub[4].title])
    with db_connection.cursor() as cursor:
        cursor.execute("SELECT snapshot FROM telegram_workflow_prompt WHERE id = %s", [prompt.pk])
        assert str(hub[4].pk) not in cursor.fetchone()[0]
    assert TelegramWorkflowPrompt.objects.count() == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "opt_out",
        "client",
        "org_removed",
        "disabled",
        "unpair",
        "private_disabled",
        "private_epoch",
        "link_epoch",
        "connection_epoch",
        "source_internal",
        "source_moved",
        "source_job_revision",
        "source_result",
        "source_author",
        "idea_changed",
        "organization_moved",
        "expired",
        "snapshot_cleared",
    ],
)
def test_queued_questions_fail_closed_before_transport(hub, mutation):
    prompt = queued(hub)
    connection, _, link, private, source, job, message, api = hub
    if mutation == "opt_out":
        Message.objects.filter(conversation=source, action=customer_workflow.TELEGRAM_OPT_IN_ACTION).delete()
    elif mutation == "client":
        WorkspaceMembership.objects.filter(workspace=connection.workspace, user=link.user).update(
            workspace_role="client"
        )
    elif mutation == "org_removed":
        OrgMembership.objects.filter(organization=connection.workspace.organization, user=link.user).delete()
    elif mutation == "disabled":
        User.objects.filter(pk=link.user_id).update(is_active=False)
    elif mutation == "unpair":
        TelegramUserLink.objects.filter(pk=link.pk).update(is_active=False)
    elif mutation == "private_disabled":
        TelegramChat.objects.filter(pk=private.pk).update(is_active=False)
    elif mutation == "private_epoch":
        TelegramChat.objects.filter(pk=private.pk).update(updated_at=timezone.now() + timedelta(seconds=1))
    elif mutation == "link_epoch":
        TelegramUserLink.objects.filter(pk=link.pk).update(updated_at=timezone.now() + timedelta(seconds=1))
    elif mutation == "connection_epoch":
        connection.webhook_secret = "reconnected-secret"
        connection.save()
    elif mutation == "source_internal":
        Message.objects.filter(pk=message.pk).update(is_internal=True)
    elif mutation == "source_moved":
        Message.objects.filter(pk=message.pk).update(conversation=private.conversation)
    elif mutation == "source_job_revision":
        AgencyJob.objects.filter(pk=job.pk).update(revision=job.revision + 1)
    elif mutation == "source_result":
        AgencyJob.objects.filter(pk=job.pk).update(result={})
    elif mutation == "source_author":
        Conversation.objects.filter(pk=source.pk).update(created_by=None)
    elif mutation == "idea_changed":
        Message.objects.filter(conversation=source, action=customer_workflow.IDEA_ACTION).update(body="Changed idea")
    elif mutation == "organization_moved":
        other = Organization.objects.create(name="Different company")
        OrgMembership.objects.create(organization=other, user=link.user, org_role="owner")
        source.workspace.organization = other
        source.workspace.save(update_fields=["organization"])
    elif mutation == "expired":
        TelegramWorkflowPrompt.objects.filter(pk=prompt.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    else:
        TelegramWorkflowPrompt.objects.filter(pk=prompt.pk).update(snapshot={})
    assert outbox.send_one(prompt.delivery_id) == "failed"
    api.call.assert_not_called()


@pytest.mark.parametrize(
    "receipt",
    [
        {},
        {"message_id": True},
        {"message_id": 700},
        {"message_id": 700, "chat": {"id": 77, "type": "private"}},
        {"message_id": 700, "chat": {"id": 99, "type": "supergroup"}},
    ],
)
def test_unverified_private_receipt_is_unknown_never_replayed(hub, receipt):
    prompt = queued(hub)
    hub[-1].call.return_value = receipt
    assert outbox.send_one(prompt.delivery_id) == "unknown"
    assert outbox.send_one(prompt.delivery_id) == "skipped"
    assert hub[-1].call.call_count == 1


def test_unknown_send_has_no_reply_capability(hub):
    prompt = queued(hub)
    hub[-1].call.side_effect = TelegramAPIError(kind="transport", ambiguous=True)
    assert outbox.send_one(prompt.delivery_id) == "unknown"
    prompt.refresh_from_db()
    assert prompt.delivery.native_message_id is None
    with pytest.raises(PermissionDenied):
        workflow_bridge._sent(prompt)


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_sender",
        "bot_sender",
        "wrong_chat",
        "forwarded",
        "command",
        "quote_only",
        "media",
        "sent_revoked",
        "unpaired",
    ],
)
def test_only_exact_authentic_author_reply_can_continue_original_thread(hub, mutation, monkeypatch):
    prompt = sent(hub)
    changes = {}
    if mutation == "wrong_sender":
        changes["from"] = {"id": 77, "is_bot": False}
    elif mutation == "bot_sender":
        changes["from"] = {"id": 99, "is_bot": True}
    elif mutation == "wrong_chat":
        changes["chat"] = {"id": 77, "type": "private"}
    elif mutation == "forwarded":
        changes["forward_origin"] = {"type": "user"}
    elif mutation == "command":
        changes["text"] = "/stop"
    elif mutation == "quote_only":
        changes["reply_to_message"] = {"text": prompt.delivery.payload["text"]}
    elif mutation == "media":
        changes["photo"] = [{"file_id": "opaque"}]
    elif mutation == "sent_revoked":
        TelegramDelivery.objects.filter(pk=prompt.delivery_id).update(status="unknown")
    else:
        TelegramUserLink.objects.filter(pk=hub[2].pk).update(is_active=False)
    monkeypatch.setattr("apps.telegram.conversations.handle_message", Mock(return_value={"silent": True}))
    before = hub[4].messages.count()
    process_one(incoming(hub, **changes).pk)
    prompt.refresh_from_db()
    assert prompt.consumed_at is None and hub[4].messages.count() == before


def test_authentication_and_one_use_guard_blocks_direct_or_duplicate_reply(hub):
    prompt = sent(hub)
    row = incoming(hub, text="yes")
    assert workflow_bridge.handle_workflow_reply(hub[0], row.payload)["text"].startswith("This workflow reply request")
    assert process_one(row.pk) == "processed"
    assert process_one(incoming(hub, text="yes", update_id=41).pk) == "processed"
    prompt.refresh_from_db()
    assert hub[4].messages.filter(author=hub[2].user, body="yes").count() == 1
    assert prompt.response_message.action == ""


@pytest.mark.parametrize("mutation", ["link", "opt_in", "role", "body", "job_clone"])
def test_delayed_worker_context_requires_same_author_body_receipt_and_current_access(hub, mutation):
    prompt, job = continued(hub)
    if mutation == "link":
        TelegramUserLink.objects.filter(pk=hub[2].pk).update(is_active=False)
    elif mutation == "opt_in":
        Message.objects.filter(conversation=hub[4], action=customer_workflow.TELEGRAM_OPT_IN_ACTION).delete()
    elif mutation == "role":
        WorkspaceMembership.objects.filter(workspace=hub[0].workspace, user=hub[2].user).update(workspace_role="viewer")
    elif mutation == "body":
        Message.objects.filter(pk=prompt.response_message_id).update(body="Forged new request")
    else:
        job = AgencyJob.objects.create(
            workspace=job.workspace,
            conversation=job.conversation,
            kind="chat",
            requested_by=job.requested_by,
            input=job.input,
        )
    with pytest.raises(PermissionDenied):
        workflow_bridge.workflow_member(job, hub[4], hub[2].user)


def test_revocation_during_source_lookup_stops_before_provider_spend(hub, monkeypatch):
    _, job = continued(hub)
    job.status = "working"
    job.save(update_fields=["status"])
    monkeypatch.setattr(chat_job.budget, "can_spend", lambda workspace: True)
    monkeypatch.setattr(chat_job, "ensure_profile", Mock())

    def revoke(*args, **kwargs):
        TelegramUserLink.objects.filter(pk=hub[2].pk).update(is_active=False)
        return None

    monkeypatch.setattr(chat_job, "_guided_context", revoke)
    provider = Mock(side_effect=AssertionError("No paid provider call is authorized"))
    monkeypatch.setattr(engine, "call", provider)
    chat_job.answer(job)
    provider.assert_not_called()
    job.refresh_from_db()
    assert "skipped" in job.result


def test_reviewed_same_job_pause_resume_preserves_receipt_origin_and_fences_old_worker(hub, monkeypatch):
    _, job = continued(hub)
    monkeypatch.setattr(opendots.llm, "configuration_error", lambda: "")
    monkeypatch.setattr(opendots.budget, "can_spend", lambda workspace: True)
    paused = opendots.control_job(job.workspace, job.requested_by, job.pk, "pause", expected_revision=job.revision)
    resumed = opendots.control_job(job.workspace, job.requested_by, job.pk, "resume", expected_revision=paused.revision)
    assert resumed.revision > job.revision
    assert workflow_bridge.workflow_member(resumed, hub[4], hub[2].user).user_id == hub[2].user_id
    with pytest.raises(PermissionDenied):
        workflow_bridge.workflow_member(job, hub[4], hub[2].user)


def test_post_lifecycle_follows_original_author_and_never_sends_captions_or_reviewer_body(hub):
    post = Post.objects.create(
        workspace=hub[0].workspace, author=hub[2].user, caption="SECRET CAPTION", title="SECRET TITLE"
    )
    hub[4].post = post
    hub[4].save(update_fields=["post"])
    reviewer = User.objects.create_user(email="unpaired-reviewer@example.test", password="fake")
    notice = Notification.objects.create(
        user=reviewer,
        event_type="post_approved",
        title="SECRET QUOTE",
        body="SECRET PROVIDER COST",
        data={"post_id": str(post.pk), "workspace_id": str(post.workspace_id)},
    )
    assert notifications.notification_event(notice.pk) == 1
    prompt = TelegramWorkflowPrompt.objects.get(source_key__startswith="post:")
    assert prompt.author_id == hub[2].user_id and prompt.chat_id == hub[3].pk
    assert "approved" in prompt.delivery.payload["text"] and "SECRET" not in prompt.delivery.payload["text"]
    assert notifications.notification_event(notice.pk) == 0
    assert outbox.send_one(prompt.delivery_id) == "sent"


def test_confirmed_publication_requires_native_receipt_and_private_lineage_is_denied(hub):
    post = Post.objects.create(workspace=hub[0].workspace, author=hub[2].user)
    hub[4].post = post
    hub[4].save(update_fields=["post"])
    account = SocialAccount.objects.create(workspace=post.workspace, platform="instagram", account_name="A company")
    pp = PlatformPost.objects.create(post=post, social_account=account)
    PlatformPost.objects.filter(pk=pp.pk).update(status="published", published_at=timezone.now())
    assert notifications.platform_receipt(pp.pk) == 0
    PlatformPost.objects.filter(pk=pp.pk).update(platform_post_id="native-private-receipt")
    assert notifications.platform_receipt(pp.pk) == 1
    assert "native-private-receipt" not in TelegramWorkflowPrompt.objects.get().delivery.payload["text"]
    Conversation.objects.create(workspace=post.workspace, post=post, created_by=hub[2].user, is_private=True)
    assert workflow_bridge.queue_post_event(post, "review", "new-event") == 0


def test_real_ready_draft_entrypoint_notifies_original_web_author(hub):
    post = Post.objects.create(workspace=hub[0].workspace, author=hub[2].user)
    brief = StudioBrief.objects.create(
        workspace=post.workspace,
        author=hub[2].user,
        job=hub[5],
        post=post,
        status="ready",
        stage="done",
        finished_at=timezone.now(),
    )
    assert notifications.ready_draft(brief.pk) == 1
    text = TelegramWorkflowPrompt.objects.get().delivery.payload["text"]
    assert "ready" in text and "continue" in text.lower()
    brief.revision += 1
    brief.save(update_fields=["revision"])
    assert outbox.send_one(TelegramWorkflowPrompt.objects.get().delivery_id) == "failed"


def test_cyclic_sweep_cannot_be_starved_by_an_unpaired_authors_earlier_work(hub):
    from apps.common.models import TaskHeartbeat

    for index in range(3):
        conversation = customer_workflow.save_idea(
            hub[0].workspace, hub[2].user, request_id=uuid.uuid4(), idea=f"Idea {index}", telegram_updates=True
        )
        job = AgencyJob.objects.create(
            workspace=hub[0].workspace, conversation=conversation, kind="chat", status="done", requested_by=hub[2].user
        )
        message = Message.objects.create(
            id=uuid.UUID(int=index + 1),
            conversation=conversation,
            job=job,
            author_kind="agent",
            agent="account_manager",
            action="answer",
            body="Hidden",
        )
        job.result = {"message_id": str(message.pk)}
        job.save(update_fields=["result"])
        Message.objects.filter(conversation=conversation, action=customer_workflow.TELEGRAM_OPT_IN_ACTION).update(
            action_status="declined"
        )
    assert workflow_bridge.sweep_workflow_messages(limit=2) == 0
    assert workflow_bridge.sweep_workflow_messages(limit=2) == 1
    assert TaskHeartbeat.objects.filter(task_name="apps.telegram.workflow_cursor").exists()


def test_provider_result_after_pair_revocation_cannot_write_original_work(hub, monkeypatch):
    _, job = continued(hub)
    job.status = "working"
    job.save(update_fields=["status"])
    monkeypatch.setattr(chat_job.budget, "can_spend", lambda workspace: True)
    monkeypatch.setattr(chat_job, "ensure_profile", Mock())
    monkeypatch.setattr(chat_job, "_guided_context", lambda *args: None)
    before = hub[4].messages.count()

    def return_after_revocation(*args, **kwargs):
        TelegramUserLink.objects.filter(pk=hub[2].pk).update(is_active=False)
        return Mock(), SimpleNamespace(output=SimpleNamespace(action="answer", creative_brief=None))

    monkeypatch.setattr(engine, "call", return_after_revocation)
    end = Mock()
    monkeypatch.setattr(engine, "end", end)
    chat_job.answer(job)
    assert hub[4].messages.count() == before
    assert not StudioBrief.objects.filter(job__conversation=hub[4]).exists()
    assert end.call_args.kwargs["status"] == "skipped"


def test_current_bot_receipt_namespace_does_not_route_into_older_prompt(hub):
    old = sent(hub)
    connection = hub[0]
    connection.webhook_secret = "fresh-bot-receiver-secret"
    connection.save()
    source_job = AgencyJob.objects.create(
        workspace=connection.workspace, conversation=hub[4], requested_by=hub[2].user, kind="chat", status="done"
    )
    message = Message.objects.create(
        conversation=hub[4],
        job=source_job,
        author_kind="agent",
        agent="account_manager",
        action="new_post",
        body="Fresh question",
    )
    source_job.result = {
        "message_id": str(message.pk),
        "creative_brief": {"topic": "Fresh topic"},
        "awaiting_confirmation": False,
    }
    source_job.save(update_fields=["result"])
    assert workflow_bridge.queue_workflow_message(message.pk) == 1
    fresh = TelegramWorkflowPrompt.objects.get(source_message=message)
    # A replaced bot can legitimately reuse the native message counter.
    assert outbox.send_one(fresh.delivery_id) == "sent"
    assert process_one(incoming(hub).pk) == "processed"
    fresh.refresh_from_db()
    old.refresh_from_db()
    assert fresh.consumed_at is not None and old.consumed_at is None


@pytest.mark.parametrize("mutation", ["text", "reply_markup", "photo", "method"])
def test_reserved_prompt_cannot_be_mutated_into_other_content_or_transport(hub, mutation):
    prompt = queued(hub)
    payload = dict(prompt.delivery.payload)
    payload[mutation] = "PRIVATE cost/token quote"
    TelegramDelivery.objects.filter(pk=prompt.delivery_id).update(payload=payload)
    assert outbox.send_one(prompt.delivery_id) == "failed"
    hub[-1].call.assert_not_called()


def test_private_prompt_has_only_normal_authenticated_thread_link(hub, settings):
    settings.APP_URL = "https://example.test"
    prompt = queued(hub)
    assert f"https://example.test/workspace/{hub[0].workspace_id}" in prompt.delivery.payload["text"]
    assert f"?c={hub[4].pk}" in prompt.delivery.payload["text"]
    assert "token=" not in prompt.delivery.payload["text"]
