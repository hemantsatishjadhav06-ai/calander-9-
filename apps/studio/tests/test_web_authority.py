"""Fresh web authority and real PostgreSQL send/result lock ordering.

Model calls are counted fakes. No provider, Telegram or publisher is contacted.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import close_old_connections, connection, transaction

from apps.members.models import CustomRole, OrgMembership, WorkspaceMembership
from apps.studio import chat, engine
from apps.studio.jobtypes import chat as chat_job
from apps.studio.models import AgencyJob, Message, StudioBrief
from apps.studio.roles import client as client_roles
from apps.studio.tests.test_chat import client_user as client_user_fixture
from apps.studio.tests.test_chat import manager_agent as manager_agent_fixture
from apps.studio.tests.test_guided_chat import source_collector as source_collector_fixture

client_user = client_user_fixture
manager_agent = manager_agent_fixture
source_collector = source_collector_fixture


@pytest.fixture(autouse=True)
def no_background_dispatch(monkeypatch):
    monkeypatch.setattr(engine, "enqueue", lambda job, stage: None)


def queued(world):
    conversation = chat.general_conversation(world.workspace, created_by=world.editor)
    posted = chat.post_message(conversation, world.editor, "Help with a saved idea")
    assert posted.job is not None
    return conversation, posted.job


def revoke(world, change):
    if change == "organization":
        OrgMembership.objects.filter(user=world.editor, organization=world.org).delete()
    elif change == "disabled":
        type(world.editor).objects.filter(pk=world.editor.pk).update(is_active=False)
    else:
        role = CustomRole.objects.create(
            organization=world.org,
            name="Client-facing role",
            permissions={"create_posts": True, "client_facing": True},
        )
        WorkspaceMembership.objects.filter(user=world.editor, workspace=world.workspace).update(custom_role=role)


def run(job):
    engine.run_step(str(job.pk), job.revision, job.stage)
    job.refresh_from_db()
    return job


def test_authorized_web_request_makes_one_model_call(world, manager_agent, source_collector):
    conversation, job = queued(world)
    run(job)
    assert len(manager_agent.calls) == 1
    assert job.status == AgencyJob.Status.DONE
    assert conversation.messages.filter(author_kind=Message.AuthorKind.AGENT).count() == 1


@pytest.mark.parametrize("change", ["organization", "client_facing", "disabled"])
def test_revoked_web_authority_prevents_provider_spend(world, manager_agent, source_collector, change):
    conversation, job = queued(world)
    revoke(world, change)
    run(job)
    assert manager_agent.calls == []
    assert "skipped" in job.result
    assert not conversation.messages.filter(author_kind=Message.AuthorKind.AGENT).exists()
    assert not StudioBrief.objects.filter(workspace=world.workspace).exists()


@pytest.mark.parametrize("change", ["organization", "client_facing"])
def test_source_reads_cannot_leave_stale_authority_for_model_spend(
    world, manager_agent, source_collector, monkeypatch, change
):
    conversation, job = queued(world)
    original = chat_job._guided_context

    def changed_after_source_read(*args, **kwargs):
        result = original(*args, **kwargs)
        revoke(world, change)
        return result

    monkeypatch.setattr(chat_job, "_guided_context", changed_after_source_read)
    run(job)
    assert manager_agent.calls == []
    assert "skipped" in job.result
    assert not conversation.messages.filter(author_kind=Message.AuthorKind.AGENT).exists()


@pytest.mark.parametrize("change", ["organization", "client_facing"])
def test_authority_revoked_during_model_call_rejects_late_effects(
    world, manager_agent, source_collector, monkeypatch, change
):
    conversation, job = queued(world)

    def returning_model(*args, **kwargs):
        result = manager_agent(*args, **kwargs)
        revoke(world, change)
        return result

    monkeypatch.setattr(client_roles, "account_manager", returning_model)
    run(job)
    assert len(manager_agent.calls) == 1
    assert "skipped" in job.result
    assert not conversation.messages.filter(author_kind=Message.AuthorKind.AGENT).exists()
    assert not StudioBrief.objects.filter(workspace=world.workspace).exists()
    assert job.runs.get().input_tokens > 0  # The completed request remains accounted for.


@pytest.mark.parametrize("custom_role", [False, True])
def test_legitimate_workspace_only_portal_clients_remain_client_authors(world, client_user, manager_agent, custom_role):
    if custom_role:
        role = CustomRole.objects.create(
            organization=world.org,
            name="Client review role",
            permissions={"client_facing": True, "create_posts": True},
        )
        WorkspaceMembership.objects.filter(user=client_user, workspace=world.workspace).update(custom_role=role)
    conversation = chat.general_conversation(world.workspace, audience="client", created_by=client_user)
    posted = chat.post_message(conversation, client_user, "Please answer my review question")
    assert posted.message.author_kind == Message.AuthorKind.CLIENT
    run(posted.job)
    assert len(manager_agent.calls) == 1 and manager_agent.calls[0]["speaker"] == "client"
    assert not manager_agent.calls[0].get("guided", False)
    with pytest.raises(chat.ChatError):
        chat.post_message(conversation, client_user, "Private team note", is_internal=True)
    with pytest.raises(chat.ChatError):
        chat.post_message(chat.general_conversation(world.workspace), client_user, "Internal work")


@pytest.mark.django_db(transaction=True)
def test_web_send_and_returning_result_share_real_postgresql_lock_order(world, monkeypatch):
    """A send holding Conversation must not deadlock with the result's Workspace lock.

    The old send touched Conversation before the deferred Workspace FK check
    for its new job. This creates an actual PostgreSQL cycle when a result
    already owns Workspace and waits for that Conversation. The fixed send
    owns Workspace first, so the result waits without owning conflicting locks.
    """
    conversation, job = queued(world)
    job.status = AgencyJob.Status.WORKING
    job.save(update_fields=["status"])
    touched, release_send, worker_entered = threading.Event(), threading.Event(), threading.Event()
    worker_pid = []
    original_touch = chat._touch

    def hold_touched_thread(*args, **kwargs):
        original_touch(*args, **kwargs)
        touched.set()
        assert release_send.wait(5), "test did not release the web send"

    monkeypatch.setattr(chat, "_touch", hold_touched_thread)

    def send():
        close_old_connections()
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '3s'")
                return chat.post_message(conversation, world.editor, "Another web message").job.pk
        finally:
            connection.close()

    def returning_result():
        close_old_connections()
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '3s'")
                    cursor.execute("SELECT pg_backend_pid()")
                    worker_pid.append(cursor.fetchone()[0])
                worker_entered.set()
                assert chat_job._current_membership(job, conversation, world.editor) is not None
                engine.save(job, result={"returned": True})
                return "result persisted"
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        send_future = pool.submit(send)
        assert touched.wait(3)
        worker_future = pool.submit(returning_result)
        try:
            assert worker_entered.wait(3)
            blocked = False
            for _ in range(100):
                with connection.cursor() as cursor:
                    cursor.execute("SELECT cardinality(pg_blocking_pids(%s)) > 0", [worker_pid[0]])
                    blocked = cursor.fetchone()[0]
                if blocked:
                    break
                time.sleep(0.01)
            assert blocked, "the returning result never competed for the real database lock"
        finally:
            release_send.set()
        assert send_future.result(timeout=5) != job.pk
        assert worker_future.result(timeout=5) == "result persisted"
    job.refresh_from_db()
    assert job.result == {"returned": True}
