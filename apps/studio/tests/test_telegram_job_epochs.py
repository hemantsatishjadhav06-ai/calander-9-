"""A repaired Telegram identity cannot revive an already queued paid request."""

import json
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.members.models import WorkspaceMembership
from apps.studio import engine, opendots
from apps.studio.jobtypes import chat as chat_job
from apps.studio.models import AgencyJob, Message, StudioBrief
from apps.studio.roles import client as client_roles
from apps.studio.tests.test_chat import manager_agent as manager_agent_fixture
from apps.telegram import provisioning
from apps.telegram.models import TelegramChat, TelegramConnection, TelegramUserLink
from apps.telegram.tests.test_conversations import hub as hub_fixture
from apps.telegram.tests.test_conversations import send

hub = hub_fixture
manager_agent = manager_agent_fixture


def queued(hub, text="Old paid request"):
    result = send(hub, "/brief " + text, bound=hub.team_chat)
    return AgencyJob.objects.get(pk=result["job_id"])


def run(job):
    engine.run_step(str(job.pk), job.revision, job.stage)
    job.refresh_from_db()
    return job


def change_epoch(hub, field):
    later = timezone.now() + timedelta(seconds=1)
    if field == "link":
        TelegramUserLink.objects.filter(pk=hub.links["editor"].pk).update(updated_at=later)
    elif field == "chat":
        TelegramChat.objects.filter(pk=hub.team_chat.pk).update(updated_at=later)
    elif field == "connection":
        TelegramConnection.objects.filter(pk=hub.connection.pk).update(updated_at=later)
    elif field == "token":
        TelegramConnection.objects.filter(pk=hub.connection.pk).update(token="a-different-synthetic-token")
    elif field == "secret":
        TelegramConnection.objects.filter(pk=hub.connection.pk).update(webhook_secret="a-different-synthetic-secret")
    else:
        WorkspaceMembership.objects.filter(workspace=hub.ws, user=hub.users["editor"]).update(workspace_role="manager")


def test_same_id_unpair_repair_holds_old_group_job_and_accepts_new_request(hub, manager_agent):
    old = queued(hub)
    old_link_id, old_conversation = hub.links["editor"].pk, hub.team_chat.conversation_id
    assert "binding" in old.input["telegram_context"]
    assert hub.connection.token not in json.dumps(old.input)
    assert hub.connection.webhook_secret not in json.dumps(old.input)
    provisioning.unpair(hub.connection, hub.users["editor"])
    _, nonce = provisioning.issue_pairing(hub.connection, hub.users["editor"])
    repaired = provisioning.consume_user_pairing(hub.connection, nonce, hub.links["editor"].telegram_user_id)
    hub.team_chat.refresh_from_db()
    assert repaired.pk == old_link_id and hub.team_chat.conversation_id == old_conversation
    run(old)
    assert manager_agent.calls == []
    assert "send" in old.result["skipped"] and "again" in old.result["skipped"]
    assert not Message.objects.filter(author_kind="agent").exists()
    assert not StudioBrief.objects.exists()
    fresh = queued(hub, "Fresh consent after pairing")
    run(fresh)
    assert len(manager_agent.calls) == 1
    assert "Fresh consent after pairing" in manager_agent.calls[0]["request"]
    assert "Old paid request" not in manager_agent.calls[0]["request"]


@pytest.mark.parametrize("field", ["link", "chat", "connection", "token", "secret", "role"])
def test_queued_request_cannot_adopt_changed_consent_epochs(hub, manager_agent, field):
    job = queued(hub)
    change_epoch(hub, field)
    run(job)
    assert manager_agent.calls == []
    assert "skipped" in job.result
    assert not Message.objects.filter(author_kind="agent").exists()
    assert not StudioBrief.objects.exists()


def test_legacy_bare_id_job_is_held_instead_of_backfilling_current_consent(hub, manager_agent):
    job = queued(hub)
    context = job.input["telegram_context"]
    job.input["telegram_context"] = {key: context[key] for key in ("chat_id", "user_link_id")}
    job.save(update_fields=["input"])
    run(job)
    assert manager_agent.calls == []
    assert "pairing proof" in job.result["skipped"] and "send it again" in job.result["skipped"]
    assert "binding" not in job.input["telegram_context"]


def test_epoch_revoked_during_source_reads_prevents_paid_model_call(hub, manager_agent, monkeypatch):
    job = queued(hub)
    original = chat_job._guided_context

    def returning_sources(*args, **kwargs):
        result = original(*args, **kwargs)
        change_epoch(hub, "link")
        return result

    monkeypatch.setattr(chat_job, "_guided_context", returning_sources)
    run(job)
    assert manager_agent.calls == [] and "skipped" in job.result


def test_pause_during_source_reads_fences_the_next_paid_call(hub, manager_agent, monkeypatch):
    job = queued(hub)
    original = chat_job._guided_context

    def returning_sources(*args, **kwargs):
        result = original(*args, **kwargs)
        opendots.control_job(hub.ws, hub.users["editor"], job.pk, "pause", expected_revision=job.revision)
        return result

    monkeypatch.setattr(chat_job, "_guided_context", returning_sources)
    run(job)
    assert manager_agent.calls == []
    assert job.status == AgencyJob.Status.CANCELLED and job.revision == 2
    assert not Message.objects.filter(author_kind="agent").exists()


def test_pairing_epoch_changed_after_model_return_preserves_bill_without_effects(hub, manager_agent, monkeypatch):
    job = queued(hub)

    def returning_model(*args, **kwargs):
        result = manager_agent(*args, **kwargs)
        change_epoch(hub, "link")
        return result

    monkeypatch.setattr(client_roles, "account_manager", returning_model)
    run(job)
    assert len(manager_agent.calls) == 1 and "skipped" in job.result
    assert not Message.objects.filter(author_kind="agent").exists()
    assert not StudioBrief.objects.exists()
    assert job.runs.get().input_tokens > 0
