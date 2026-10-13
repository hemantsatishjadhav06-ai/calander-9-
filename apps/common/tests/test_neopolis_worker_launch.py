"""Fault injection for Neopolis: overlapping tasks, stale callbacks and policy recovery."""

import json
import signal
import threading
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from background_task.models import Task
from django.core.management.base import CommandError
from django.db import connections
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.common.background import (
    WorkerAlreadyRunningError,
    WorkerLeaseLostError,
    check_worker_lease,
    worker_lease_checks,
    worker_process_lock,
)
from apps.common.management.commands.run_worker import Command, _LeaseCheckedTasks
from apps.organizations.models import Organization
from apps.studio import engine, jobs
from apps.studio.autopilot import AUTOPILOT_PAUSED, WORKSPACE_PAUSED
from apps.studio.models import AgencyJob, AgencySettings, AgentRun
from apps.workspaces.models import Workspace


class NeopolisWorkerLaunchTests(TransactionTestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Neopolis launch audit")
        self.workspace = Workspace.objects.create(organization=self.org, name="Neopolis", timezone="Asia/Kolkata")
        self.settings = AgencySettings.objects.create(workspace=self.workspace, autopilot_enabled=True)
        self.calls = []

        def complete(job):
            self.calls.append(job.pk)
            engine.finish(job, result={"prepared": True})
            return None

        probe = engine.JobType(kind="report", stages=(engine.Stage("prepare", "planner", complete),))
        plan = engine.JobType(kind="plan", stages=(engine.Stage("prepare", "planner", complete),))
        self.registry = patch.dict(jobs.JOB_TYPES, report=probe, plan=plan)
        self.registry.start()
        self.addCleanup(self.registry.stop)

    def job(self, *, kind="report", input=None):
        return engine.create(self.workspace, kind, input=input, start=False)

    def test_lost_lease_context_reaches_both_publisher_thread_pools(self):
        from apps.composer.models import PlatformPost, Post
        from apps.publisher.engine import PublishEngine
        from apps.social_accounts.models import SocialAccount
        from providers.types import PostType

        account = SocialAccount.objects.create(
            workspace=self.workspace, platform="facebook", account_platform_id="test-page", account_name="Test"
        )
        when = timezone.now() - timedelta(minutes=1)
        post = Post.objects.create(workspace=self.workspace, caption="Synthetic test", scheduled_at=when)
        row = PlatformPost.objects.create(post=post, social_account=account, status="scheduled", scheduled_at=when)
        provider = MagicMock()
        provider.supported_post_types = [PostType.TEXT]
        provider.needs_local_media = False

        def lost_lease():
            raise RuntimeError("worker session disappeared during preparation")

        with (
            patch("apps.publisher.engine._provider_and_access_token", return_value=(provider, "test-token")),
            worker_lease_checks(lost_lease),
            self.assertRaises(WorkerLeaseLostError),
        ):
            PublishEngine().poll_and_publish()
        provider.publish_post.assert_not_called()
        row.refresh_from_db()
        self.assertEqual(row.status, "publishing")

    def test_overlapping_deliveries_execute_one_stage(self):
        entered, release = threading.Event(), threading.Event()
        errors = []

        def blocked(job):
            self.calls.append(job.pk)
            entered.set()
            if not release.wait(timeout=10):
                raise AssertionError("probe was not released")
            engine.finish(job, result={"prepared": True})
            return None

        jobs.JOB_TYPES["report"] = engine.JobType(kind="report", stages=(engine.Stage("prepare", "planner", blocked),))
        job = self.job()

        def deliver():
            try:
                engine.run_step(str(job.pk), job.revision, job.stage)
            except Exception as exc:
                errors.append(exc)
            finally:
                connections.close_all()

        first = threading.Thread(target=deliver)
        second = threading.Thread(target=deliver)
        first.start()
        try:
            self.assertTrue(entered.wait(timeout=10))
            second.start()
            second.join(timeout=10)
            self.assertFalse(second.is_alive(), "duplicate must finish without waiting for the model")
            self.assertEqual(self.calls, [job.pk])
        finally:
            release.set()
            first.join(timeout=15)
            if second.ident is not None:
                second.join(timeout=15)
        self.assertEqual(errors, [])
        job.refresh_from_db()
        self.assertEqual(job.status, AgencyJob.Status.DONE)

    def test_failure_callback_cannot_overwrite_completed_job(self):
        job = self.job()
        engine.run_step(str(job.pk), job.revision, job.stage)
        engine.fail(job, "late callback")
        job.refresh_from_db()
        self.assertEqual(job.status, AgencyJob.Status.DONE)
        self.assertEqual(job.error, "")

    def test_superseded_run_cannot_close_current_revision_run(self):
        old = self.job()
        AgencyJob.objects.filter(pk=old.pk).update(status=AgencyJob.Status.WORKING)
        old.refresh_from_db()
        old_run = engine.begin(old, "planner")
        current = AgencyJob.objects.get(pk=old.pk)
        with patch.object(engine, "enqueue"):
            engine.restart(current)
        current_run = engine.begin(current, "planner")
        engine._close_running(old, "superseded", status=AgentRun.Status.SKIPPED)
        old_run.refresh_from_db()
        current_run.refresh_from_db()
        self.assertEqual(old_run.status, AgentRun.Status.SKIPPED)
        self.assertEqual(current_run.status, AgentRun.Status.RUNNING)

    def test_cancelled_job_cannot_reenter_paid_stage(self):
        job = self.job()
        engine.cancel(job)
        engine.run_step(str(job.pk), job.revision, job.stage)
        self.assertEqual(self.calls, [])

    def test_obsolete_revision_task_does_not_hide_stuck_current_job(self):
        job = self.job()
        AgencyJob.objects.filter(pk=job.pk).update(revision=2, updated_at=timezone.now() - timedelta(hours=2))
        Task.objects.create(
            task_name="apps.studio.tasks.run_agency_step",
            task_params=json.dumps([[str(job.pk), 1, job.stage], {}]),
            task_hash="obsolete",
            run_at=timezone.now(),
        )
        self.assertEqual(engine.sweep_stuck(), 1)
        job.refresh_from_db()
        self.assertEqual(job.status, AgencyJob.Status.FAILED)

    def test_invalid_task_payload_is_not_a_pending_stage(self):
        job = self.job()
        Task.objects.create(
            task_name="apps.studio.tasks.run_agency_step",
            task_params=f"broken-{job.pk}",
            task_hash="broken",
            run_at=timezone.now(),
        )
        self.assertFalse(engine._has_pending_task("apps.studio.tasks.run_agency_step", str(job.pk)))

    def test_disabled_automatic_plan_waits_without_paid_work_or_failure(self):
        job = self.job(kind="plan", input={"week_id": "week", "manual": False})
        AgencySettings.objects.filter(pk=self.settings.pk).update(autopilot_enabled=False)
        engine.run_step(str(job.pk), job.revision, job.stage)
        job.refresh_from_db()
        self.assertEqual((job.status, job.error), (AgencyJob.Status.QUEUED, AUTOPILOT_PAUSED))
        self.assertEqual(self.calls, [])
        AgencyJob.objects.filter(pk=job.pk).update(updated_at=timezone.now() - timedelta(hours=2))
        self.assertEqual(engine.sweep_stuck(), 0)

    def test_reenabled_plan_resumes_once_without_losing_progress(self):
        job = self.job(kind="plan", input={"week_id": "week"})
        AgencyJob.objects.filter(pk=job.pk).update(error=AUTOPILOT_PAUSED, state={"research": "saved"}, revision=3)
        with patch.object(engine, "enqueue") as enqueue:
            self.assertEqual(engine.resume_paused_plans(self.workspace), 1)
            self.assertEqual(engine.resume_paused_plans(self.workspace), 0)
        enqueue.assert_called_once()
        job.refresh_from_db()
        self.assertEqual((job.revision, job.state), (3, {"research": "saved"}))

    def test_explicit_manual_plan_can_run_with_recurring_autopilot_off(self):
        job = self.job(kind="plan", input={"week_id": "week", "manual": True})
        AgencySettings.objects.filter(pk=self.settings.pk).update(autopilot_enabled=False)
        engine.run_step(str(job.pk), job.revision, job.stage)
        self.assertEqual(self.calls, [job.pk])

    def test_string_manual_flag_cannot_bypass_disabled_autopilot(self):
        job = self.job(kind="plan", input={"week_id": "week", "manual": "true"})
        AgencySettings.objects.filter(pk=self.settings.pk).update(autopilot_enabled=False)
        engine.run_step(str(job.pk), job.revision, job.stage)
        self.assertEqual(self.calls, [])

    def test_archived_manual_job_stops_and_resumes_after_unarchive(self):
        job = self.job()
        Workspace.objects.filter(pk=self.workspace.pk).update(is_archived=True)
        engine.run_step(str(job.pk), job.revision, job.stage)
        job.refresh_from_db()
        self.assertEqual(job.error, WORKSPACE_PAUSED)
        with patch.object(engine, "enqueue") as enqueue:
            self.assertEqual(engine.resume_paused_jobs(), 0)
            Workspace.objects.filter(pk=self.workspace.pk).update(is_archived=False)
            self.assertEqual(engine.resume_paused_jobs(), 1)
            self.assertEqual(engine.resume_paused_jobs(), 0)
        enqueue.assert_called_once()

    def test_pending_organization_deletion_blocks_manual_plan(self):
        job = self.job(kind="plan", input={"week_id": "week", "manual": True})
        Organization.objects.filter(pk=self.org.pk).update(deletion_requested_at=timezone.now())
        engine.run_step(str(job.pk), job.revision, job.stage)
        self.assertEqual(self.calls, [])

    def test_resume_does_not_retry_failed_or_cancelled_jobs(self):
        failed = self.job()
        cancelled = self.job()
        AgencyJob.objects.filter(pk=failed.pk).update(status=AgencyJob.Status.FAILED, error=WORKSPACE_PAUSED)
        AgencyJob.objects.filter(pk=cancelled.pk).update(status=AgencyJob.Status.CANCELLED, error=WORKSPACE_PAUSED)
        with patch.object(engine, "enqueue") as enqueue:
            self.assertEqual(engine.resume_paused_jobs(), 0)
        enqueue.assert_not_called()

    def test_provider_charge_survives_end_output_and_stale_closure(self):
        job = self.job()
        result = SimpleNamespace(
            model="anthropic/claude-sonnet-4.5",
            input_tokens=10,
            output_tokens=2,
            cache_read_tokens=0,
            fallback_used=False,
            provider_cost_usd="0.037",
        )
        run, _ = engine.call(job, "planner", lambda: result)
        engine.end(run, summary="Draft prepared", output={"draft": True, "provider_cost_usd": "999"})
        run.refresh_from_db()
        self.assertEqual(run.output, {"draft": True, "provider_cost_usd": "0.037"})

    def test_failed_provider_charge_is_retained(self):
        job = self.job()
        run = engine.begin(job, "planner")
        error = RuntimeError("provider refusal")
        error.provider_cost_usd = "0.025"
        error.usage = ("anthropic/claude-sonnet-4.5", 100, 20, 0)
        engine.fail_run(run, error)
        run.refresh_from_db()
        self.assertEqual(run.output["provider_cost_usd"], "0.025")
        self.assertEqual(run.status, AgentRun.Status.FAILED)


class NeopolisWorkerLeaseTests(TestCase):
    def setUp(self):
        self.signals = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGTSTP)}

    def tearDown(self):
        for sig, handler in self.signals.items():
            signal.signal(sig, handler)

    def test_live_worker_blocks_duplicate_before_reclaim_or_loop(self):
        with (
            worker_process_lock() as check,
            patch.object(Command, "prepare") as prepare,
            patch.object(Command, "run") as run,
        ):
            check()
            with self.assertRaisesMessage(CommandError, "Another worker is still running"):
                Command().handle(dev=False, keep_locks=False)
        prepare.assert_not_called()
        run.assert_not_called()

    def test_singleton_connection_closes_after_normal_exit(self):
        with patch.object(Command, "prepare"), patch.object(Command, "run") as run:
            Command().handle(dev=False, keep_locks=False)
        run.assert_called_once()
        with worker_process_lock() as check:
            check()

    def test_singleton_connection_closes_after_run_loop_exception(self):
        with (
            patch.object(Command, "prepare"),
            patch.object(Command, "run", side_effect=RuntimeError("worker crashed")),
            self.assertRaisesMessage(RuntimeError, "worker crashed"),
        ):
            Command().handle(dev=False, keep_locks=False)
        with worker_process_lock() as check:
            check()

    def test_multiple_replicas_optout_does_not_steal_singleton(self):
        with worker_process_lock(), worker_process_lock(allow_concurrent=True) as check:
            check()
            with self.assertRaises(WorkerAlreadyRunningError), worker_process_lock():
                self.fail("another single-worker process unexpectedly acquired the lease")

    def test_missing_lease_stops_before_polling_a_task(self):
        tasks = MagicMock()
        check = MagicMock(side_effect=RuntimeError("database lease lost"))
        guarded = _LeaseCheckedTasks(tasks, check)
        with self.assertRaisesMessage(RuntimeError, "database lease lost"):
            guarded.run_next_task()
        tasks.run_next_task.assert_not_called()

    def test_lease_lost_inside_a_task_stops_before_its_next_external_write(self):
        check = MagicMock(side_effect=[None, RuntimeError("database restarted")])
        tasks = MagicMock()
        send = MagicMock()

        def task(_queue):
            check_worker_lease()
            send()

        tasks.run_next_task.side_effect = task
        with self.assertRaises(WorkerLeaseLostError):
            _LeaseCheckedTasks(tasks, check).run_next_task()
        send.assert_not_called()

    def test_lease_guard_context_is_restored_after_worker_failure(self):
        check = MagicMock(side_effect=RuntimeError("database restarted"))
        with worker_lease_checks(check), self.assertRaises(WorkerLeaseLostError):
            check_worker_lease()
        check_worker_lease()
        check.assert_called_once()

    def test_dev_reloader_requires_keep_locks_and_cannot_reclaim_by_default(self):
        with (
            patch.object(Command, "prepare") as prepare,
            patch.object(Command, "run") as run,
            self.assertRaisesMessage(CommandError, "--dev --keep-locks"),
        ):
            Command().handle(dev=True, keep_locks=False)
        prepare.assert_not_called()
        run.assert_not_called()
