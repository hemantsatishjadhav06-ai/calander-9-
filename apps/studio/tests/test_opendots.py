"""Real PostgreSQL lifecycle and scope tests for the OpenDots adaptation.

Fixtures never contact a model provider, Telegram or the publisher.
"""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

import pytest
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections, connection, transaction
from django.urls import reverse

from apps.members.models import CustomRole, OrgMembership, WorkspaceMembership
from apps.studio import chat, engine, opendots
from apps.studio.jobtypes import chat as chat_job
from apps.studio.models import AgencyJob, AgencySettings, AgentRun, Conversation
from apps.workspaces.models import Workspace


@pytest.fixture
def assistant_job(world, monkeypatch):
    from apps.studio import jobs

    calls, queued = [], []

    def first(job):
        calls.append(("first", job.revision))
        engine.update_state(job, first_finished=True)
        return "second"

    def second(job):
        calls.append(("second", job.revision))
        engine.finish(job, result={"summary": "Saved work"})

    monkeypatch.setitem(
        jobs.JOB_TYPES,
        "report",
        engine.JobType(
            kind="report", stages=(engine.Stage("first", "reporter", first), engine.Stage("second", "reporter", second))
        ),
    )
    monkeypatch.setattr(engine, "enqueue", lambda job, stage: queued.append((str(job.pk), job.revision, stage)))
    job = engine.create(world.workspace, "report", requested_by=world.editor)
    job._test_calls, job._test_queued = calls, queued
    return job


def _control(world, job, action, **kwargs):
    return opendots.control_job(world.workspace, world.editor, job.pk, action, expected_revision=job.revision, **kwargs)


def _failed(job):
    job.status = AgencyJob.Status.FAILED
    job.error = "The team stopped part-way — the background worker restarted or isn't running."
    job.save(update_fields=["status", "error"])
    return opendots.task_record(job)


def test_source_status_honestly_reports_native_adaptation():
    status = opendots.integration_status()
    assert status["mode"] == "native_adaptation" and status["task_controls"]
    assert status["commit"] == "625452e06cde74cb25b0ce319e2c1be0488f5a5f"
    assert not status["copilotkit_runtime"] and not status["copilotkit_intelligence"] and not status["computer_tools"]


def test_control_notification_uses_committed_revision_and_is_failure_isolated(
    world, assistant_job, monkeypatch, django_capture_on_commit_callbacks
):
    from apps.telegram import workflow_bridge

    delivered = []

    def record(job_id, revision, action):
        saved = AgencyJob.objects.get(pk=job_id)
        assert saved.revision == revision and saved.status == AgencyJob.Status.CANCELLED
        delivered.append((job_id, revision, action))
        raise RuntimeError("Controlled notification failure")

    monkeypatch.setattr(workflow_bridge, "job_control_event", record)
    with django_capture_on_commit_callbacks(execute=True):
        paused = _control(world, assistant_job, "pause")
    paused.refresh_from_db()

    assert delivered == [(paused.pk, paused.revision, "pause")]
    assert opendots.task_record(paused)["status"] == "paused"


def test_pause_fences_already_queued_work_and_single_resume_retains_progress(world, assistant_job):
    job = assistant_job
    engine.run_step(str(job.pk), job.revision, "first")
    job.refresh_from_db()
    old_revision = job.revision
    paused = _control(world, job, "pause")
    assert opendots.task_record(paused)["status"] == "paused"
    engine.run_step(str(job.pk), old_revision, "second")
    assert job._test_calls == [("first", 1)]
    resumed = _control(world, paused, "resume")
    assert resumed.state == {"first_finished": True} and resumed.stage == "second"
    engine.run_step(str(resumed.pk), resumed.revision, "second")
    resumed.refresh_from_db()
    assert resumed.status == AgencyJob.Status.DONE
    assert job._test_calls == [("first", 1), ("second", 3)]


def test_running_pause_rejects_late_stage_write_and_requires_explicit_review(world, assistant_job):
    job = assistant_job
    AgencyJob.objects.filter(pk=job.pk).update(status=AgencyJob.Status.WORKING)
    job.refresh_from_db()
    paused = _control(world, job, "pause")
    with pytest.raises(engine.StaleJobError):
        engine.save(job, result={"late": "must not overwrite"})
    record = opendots.task_record(paused)
    assert record["needs_effect_review"]
    with pytest.raises(opendots.CoworkerControlError, match="confirm"):
        _control(world, paused, "resume", review_receipt=record["review_receipt"])
    resumed = _control(world, paused, "resume", review_receipt=record["review_receipt"], reviewed=True)
    assert resumed.status == AgencyJob.Status.QUEUED and resumed.result == {}


def test_duplicate_resume_does_not_enqueue_a_second_revision(world, assistant_job):
    job = assistant_job
    paused = _control(world, job, "pause")
    expected = paused.revision
    _control(world, paused, "resume")
    with pytest.raises(opendots.CoworkerControlError, match="another tab"):
        opendots.control_job(world.workspace, world.editor, job.pk, "resume", expected_revision=expected)
    assert job._test_queued == [(str(job.pk), 1, "first"), (str(job.pk), 3, "first")]


def test_retry_keeps_saved_state_and_requires_review_of_current_effects(world, assistant_job):
    job = assistant_job
    job.state = {"draft_source": "saved earlier"}
    job.save(update_fields=["state"])
    record = _failed(job)
    assert record["status"] == "interrupted"
    run = AgentRun.objects.create(job=job, revision=job.revision, agent="reporter", status="failed")
    with pytest.raises(opendots.CoworkerControlError, match="changed"):
        _control(world, job, "retry", review_receipt=record["review_receipt"], reviewed=True)
    record = opendots.task_record(job)
    run.output = {"provider_cost_usd": "0.08", "receipt": "finished after stop"}
    run.status = AgentRun.Status.SUCCEEDED
    run.save(update_fields=["output", "status"])
    with pytest.raises(opendots.CoworkerControlError, match="changed"):
        _control(world, job, "retry", review_receipt=record["review_receipt"], reviewed=True)
    record = opendots.task_record(job)
    resumed = _control(world, job, "retry", review_receipt=record["review_receipt"], reviewed=True)
    assert resumed.state == {"draft_source": "saved earlier"}
    run.refresh_from_db()
    assert run.output["receipt"] == "finished after stop"


@pytest.mark.parametrize("kind", ["tampered", "other_task", "expired"])
def test_review_cannot_be_tampered_reused_or_kept_indefinitely(world, assistant_job, monkeypatch, kind):
    job = assistant_job
    receipt = _failed(job)["review_receipt"]
    if kind == "tampered":
        receipt += "invalid"
    elif kind == "other_task":
        other = engine.create(world.workspace, "report", requested_by=world.editor)
        receipt = _failed(other)["review_receipt"]
    else:
        original = signing.time.time
        monkeypatch.setattr(signing.time, "time", lambda: original() + opendots.REVIEW_MAX_AGE + 10)
    with pytest.raises(opendots.CoworkerControlError):
        _control(world, job, "retry", review_receipt=receipt, reviewed=True)
    job.refresh_from_db()
    assert job.status == AgencyJob.Status.FAILED and job.revision == 1


@pytest.mark.parametrize("change", ["removed", "deactivated", "client", "custom_permission", "foreign_role", "no_org"])
def test_controls_recheck_current_actor_scope(world, assistant_job, change):
    membership = WorkspaceMembership.objects.get(workspace=world.workspace, user=world.editor)
    if change == "removed":
        membership.delete()
    elif change == "deactivated":
        world.editor.is_active = False
        world.editor.save(update_fields=["is_active"])
    elif change == "client":
        membership.workspace_role = "client"
        membership.save(update_fields=["workspace_role"])
    elif change in {"custom_permission", "foreign_role"}:
        from apps.organizations.models import Organization

        organization = world.org if change == "custom_permission" else Organization.objects.create(name="Other")
        membership.custom_role = CustomRole.objects.create(
            organization=organization, name="Changed role", permissions={"create_posts": change == "foreign_role"}
        )
        membership.save(update_fields=["custom_role"])
    else:
        OrgMembership.objects.filter(user=world.editor, organization=world.org).delete()
    with pytest.raises(PermissionDenied):
        _control(world, assistant_job, "pause")
    assistant_job.refresh_from_db()
    assert assistant_job.status == AgencyJob.Status.QUEUED and assistant_job.revision == 1


def test_control_cannot_use_foreign_or_private_job_identifiers(world, assistant_job):
    other = Workspace.objects.create(organization=world.org, name="Other")
    AgencyJob.objects.filter(pk=assistant_job.pk).update(workspace=other)
    with pytest.raises(PermissionDenied):
        _control(world, assistant_job, "pause")
    private = Conversation.objects.create(workspace=world.workspace, is_private=True, created_by=world.editor)
    job = engine.create(world.workspace, "report", requested_by=world.editor, conversation=private)
    with pytest.raises(PermissionDenied):
        _control(world, job, "pause")
    with pytest.raises(PermissionDenied):
        opendots.control_job(world.workspace, world.editor, uuid4(), "pause", expected_revision=1)


@pytest.mark.parametrize("blocker", ["archive", "deletion", "budget", "autopilot"])
def test_resume_never_bypasses_live_workspace_policy(world, assistant_job, blocker):
    paused = _control(world, assistant_job, "pause")
    if blocker == "archive":
        world.workspace.is_archived = True
        world.workspace.save(update_fields=["is_archived"])
    elif blocker == "deletion":
        from django.utils import timezone

        world.org.deletion_requested_at = timezone.now()
        world.org.save(update_fields=["deletion_requested_at"])
    elif blocker == "budget":
        AgencySettings.objects.create(workspace=world.workspace, monthly_budget_usd=Decimal("0"))
    else:
        paused.kind = AgencyJob.Kind.PLAN
        paused.input = {"week_id": str(uuid4())}
        paused.save(update_fields=["kind", "input"])
    with pytest.raises((PermissionDenied, opendots.CoworkerControlError)):
        _control(world, paused, "resume")
    paused.refresh_from_db()
    assert paused.status == AgencyJob.Status.CANCELLED and paused.revision == 2


def test_projection_is_read_only_and_does_not_expose_inputs_or_outputs(world, assistant_job):
    job = assistant_job
    job.input = {"private": "secret prompt"}
    job.result = {"private": "secret provider output"}
    job.save(update_fields=["input", "result"])
    record = _failed(job)
    assert "secret" not in json.dumps(record)
    job.refresh_from_db()
    assert job.revision == 1 and job.status == AgencyJob.Status.FAILED


def test_resume_missing_provider_keeps_saved_task_and_queues_no_paid_work(world, assistant_job, settings):
    paused = _control(world, assistant_job, "pause")
    settings.STUDIO_PROVIDER = "openrouter"
    settings.OPENROUTER_API_KEY = ""
    with pytest.raises(opendots.CoworkerControlError, match="OPENROUTER_API_KEY"):
        _control(world, paused, "resume")
    paused.refresh_from_db()
    assert paused.status == AgencyJob.Status.CANCELLED and paused.revision == 2
    assert assistant_job._test_queued == [(str(assistant_job.pk), 1, "first")]


def test_legacy_retry_view_cannot_bypass_human_effect_review(client, world, assistant_job):
    record = _failed(assistant_job)
    client.force_login(world.editor)
    url = reverse("studio:job_retry", kwargs={"workspace_id": world.workspace.pk, "job_id": assistant_job.pk})
    response = client.post(url, {"revision": assistant_job.revision})
    assert response.status_code == 302
    assistant_job.refresh_from_db()
    assert assistant_job.status == AgencyJob.Status.FAILED
    response = client.post(
        url, {"revision": assistant_job.revision, "review_receipt": record["review_receipt"], "reviewed": "1"}
    )
    assert response.status_code == 302
    assistant_job.refresh_from_db()
    assert assistant_job.status == AgencyJob.Status.QUEUED and assistant_job.revision == 2


@pytest.mark.django_db(transaction=True)
def test_native_web_result_and_pause_share_lock_order_and_fence_late_effects(world, assistant_job, monkeypatch):
    """Create real competing PostgreSQL transactions, not a mocked lock check."""
    conversation = chat.general_conversation(world.workspace)
    job = assistant_job
    job.kind, job.stage, job.status, job.conversation = "chat", "answer", "working", conversation
    job.save(update_fields=["kind", "stage", "status", "conversation"])
    actor_locked, release_pause, worker_entered = threading.Event(), threading.Event(), threading.Event()
    worker_pid = []
    real_current_member = opendots.current_member

    def hold_pause_actor(*args, **kwargs):
        member = real_current_member(*args, **kwargs)
        actor_locked.set()
        assert release_pause.wait(5), "test did not release the pause transaction"
        return member

    monkeypatch.setattr(opendots, "current_member", hold_pause_actor)

    def pause():
        close_old_connections()
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '3s'")
                return _control(world, job, "pause").status
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
                chat_job._current_membership(job, conversation, world.editor)
                engine.save(job, result={"late": "must not commit"})
                return "unexpected completed effect"
        except engine.StaleJobError:
            return "stale effect rejected"
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        paused_future = executor.submit(pause)
        assert actor_locked.wait(3)
        worker_future = executor.submit(returning_result)
        assert worker_entered.wait(3)
        blocked = False
        for _ in range(100):
            with connection.cursor() as cursor:
                cursor.execute("SELECT cardinality(pg_blocking_pids(%s)) > 0", [worker_pid[0]])
                blocked = cursor.fetchone()[0]
            if blocked:
                break
            time.sleep(0.01)
        release_pause.set()
        assert blocked, "the returning result never competed for the real workspace lock"
        assert paused_future.result(timeout=5) == AgencyJob.Status.CANCELLED
        assert worker_future.result(timeout=5) == "stale effect rejected"
    job.refresh_from_db()
    assert job.result == {} and job.revision == 2 and opendots.task_record(job)["status"] == "paused"
