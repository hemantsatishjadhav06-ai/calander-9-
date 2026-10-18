"""Durable success evidence and a real, isolated, unbillable worker rehearsal."""

import signal
from contextlib import ExitStack
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from background_task.models import CompletedTask, Task
from background_task.tasks import tasks
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from apps.common.background import (
    _heartbeat,
    keep_schedule,
    note_task_failure,
    register_recurring_task,
    task_health,
    worker_process_lock,
)
from apps.common.management.commands.live_verify import Command as LiveVerifyCommand
from apps.common.management.commands.release import Command as ReleaseCommand
from apps.common.management.commands.run_worker import Command as RunWorkerCommand
from apps.common.management.commands.run_worker import _LeaseCheckedTasks
from apps.common.models import TaskHeartbeat
from apps.publisher.tasks import confirm_pending_publishes, run_publish_cycle
from apps.studio.tasks import run_agency_cycle

PUBLISHER = "apps.publisher.tasks.run_publish_cycle"
AGENCY = "apps.studio.tasks.run_agency_cycle"
CONFIRMATION = "apps.publisher.tasks.confirm_pending_publishes"


class DeliveryHeartbeatTests(TestCase):
    def setUp(self):
        TaskHeartbeat.objects.all().delete()

    def test_successful_publisher_cycle_records_exact_durable_identity(self):
        with patch("apps.publisher.engine.PublishEngine.poll_and_publish", return_value=0):
            run_publish_cycle.task_function()
        row = TaskHeartbeat.objects.get(task_name=PUBLISHER)
        self.assertEqual(row.state, "ok")
        self.assertIsNotNone(row.last_started_at)
        self.assertIsNotNone(row.last_success_at)
        self.assertIsNone(row.last_failure_at)
        self.assertEqual(row.error, "")
        self.assertTrue(task_health()["publisher"]["healthy"])
        self.assertFalse(task_health()["agency"]["healthy"])

    def test_successful_agency_cycle_records_exact_durable_identity(self):
        with patch("apps.studio.autopilot.run_cycle", return_value={}):
            run_agency_cycle.task_function()
        self.assertEqual(TaskHeartbeat.objects.get(task_name=AGENCY).state, "ok")
        self.assertTrue(task_health()["agency"]["healthy"])
        self.assertFalse(task_health()["publisher"]["healthy"])

    def test_confirmation_has_its_own_success_evidence(self):
        with patch("apps.publisher.engine.PublishEngine.confirm_pending_publishes", return_value=0):
            confirm_pending_publishes.task_function()
        self.assertEqual(TaskHeartbeat.objects.get(task_name=CONFIRMATION).state, "ok")
        self.assertTrue(task_health()["confirmation"]["healthy"])
        self.assertFalse(task_health()["publisher"]["healthy"])

    def test_raised_publisher_failure_is_durable_and_schedule_wrapper_does_not_raise(self):
        with (
            patch("apps.publisher.engine.PublishEngine.poll_and_publish", side_effect=RuntimeError("sensitive detail")),
            self.assertLogs("apps.common.background", level="ERROR"),
        ):
            self.assertIsNone(run_publish_cycle.task_function())
        row = TaskHeartbeat.objects.get(task_name=PUBLISHER)
        self.assertEqual(row.state, "error")
        self.assertIsNotNone(row.last_failure_at)
        self.assertIsNone(row.last_success_at)
        self.assertNotIn("sensitive detail", row.error)
        self.assertFalse(task_health()["publisher"]["healthy"])

    def test_partial_caught_failure_does_not_become_green_success(self):
        def partial_failure():
            note_task_failure(RuntimeError("caught row failure"))
            return 1

        with patch("apps.publisher.engine.PublishEngine.poll_and_publish", side_effect=partial_failure):
            run_publish_cycle.task_function()
        row = TaskHeartbeat.objects.get(task_name=PUBLISHER)
        self.assertEqual(row.state, "error")
        self.assertIsNone(row.last_success_at)
        self.assertFalse(task_health()["publisher"]["healthy"])

    def test_failure_marker_is_reset_before_the_next_task(self):
        def failed_cycle():
            note_task_failure("handled failure")
            return 0

        with patch("apps.publisher.engine.PublishEngine.poll_and_publish", side_effect=failed_cycle):
            run_publish_cycle.task_function()
        with patch("apps.studio.autopilot.run_cycle", return_value={}):
            run_agency_cycle.task_function()
        self.assertFalse(task_health()["publisher"]["healthy"])
        self.assertTrue(task_health()["agency"]["healthy"])

    def test_failure_marker_outside_a_task_does_not_poison_the_next_cycle(self):
        note_task_failure(RuntimeError("unrelated operation"))
        with patch("apps.publisher.engine.PublishEngine.poll_and_publish", return_value=0):
            run_publish_cycle.task_function()
        self.assertTrue(task_health()["publisher"]["healthy"])

    def test_nested_task_failure_does_not_poison_a_successful_parent_context(self):
        @keep_schedule
        def nested_failure():
            note_task_failure("nested handled error")

        @keep_schedule
        def outer_success():
            nested_failure()

        outer_success()
        rows = {row.task_name.rsplit(".", 1)[-1]: row for row in TaskHeartbeat.objects.all()}
        self.assertEqual(rows["nested_failure"].state, "error")
        self.assertEqual(rows["outer_success"].state, "ok")

    def test_heartbeat_persistence_failure_does_not_retry_completed_work(self):
        completed = []

        @keep_schedule
        def committed_write():
            completed.append("one external write")
            return "done"

        with (
            patch.object(TaskHeartbeat.objects, "update_or_create", side_effect=RuntimeError("database unavailable")),
            self.assertLogs("apps.common.background", level="ERROR"),
        ):
            self.assertEqual(committed_write(), "done")
        self.assertEqual(completed, ["one external write"])

    def test_actual_heartbeat_database_failure_is_swallowed_without_leaking_error(self):
        with (
            patch.object(TaskHeartbeat.objects, "update_or_create", side_effect=RuntimeError("token-secret")),
            self.assertLogs("apps.common.background", level="ERROR") as logs,
        ):
            _heartbeat(PUBLISHER, "start", timezone.now())
        self.assertNotIn("token-secret", "\n".join(logs.output))

    def test_stale_finish_cannot_overwrite_a_newer_cycle(self):
        older = timezone.now() - timedelta(minutes=2)
        newer = timezone.now() - timedelta(minutes=1)
        _heartbeat(PUBLISHER, "start", older)
        _heartbeat(PUBLISHER, "start", newer)
        _heartbeat(PUBLISHER, "finish", newer)
        before = TaskHeartbeat.objects.get(task_name=PUBLISHER)
        _heartbeat(PUBLISHER, "finish", older, failed=True)
        row = TaskHeartbeat.objects.get(task_name=PUBLISHER)
        self.assertEqual(row.last_started_at, newer)
        self.assertEqual(row.last_success_at, before.last_success_at)
        self.assertIsNone(row.last_failure_at)
        self.assertEqual(row.state, "ok")

    def test_real_agency_partial_failure_is_unhealthy_but_remaining_parts_run(self):
        from apps.studio import autopilot

        with ExitStack() as stack:
            probes = {
                name: stack.enter_context(patch.object(autopilot, name, return_value=0)) for name in autopilot.PARTS
            }
            probes[autopilot.PARTS[0]].side_effect = RuntimeError("one broken agency sweep")
            with self.assertLogs("apps.studio.autopilot", level="ERROR"):
                run_agency_cycle.task_function()
        for probe in probes.values():
            probe.assert_called_once()
        self.assertEqual(TaskHeartbeat.objects.get(task_name=AGENCY).state, "error")
        self.assertFalse(task_health()["agency"]["healthy"])


class TaskHealthEvidenceTests(TestCase):
    def setUp(self):
        TaskHeartbeat.objects.all().delete()
        self.now = timezone.now()

    def row(self, *, success=None, failure=None, state="ok", name=PUBLISHER):
        return TaskHeartbeat.objects.create(
            task_name=name, state=state, last_success_at=success, last_failure_at=failure
        )

    def test_missing_evidence_is_unhealthy_for_each_required_task(self):
        health = task_health(now=self.now)
        self.assertEqual(set(health), {"publisher", "agency", "confirmation"})
        for evidence in health.values():
            self.assertFalse(evidence["healthy"])
            self.assertEqual(evidence["state"], "unknown")
            self.assertIsNone(evidence["last_success_at"])
            self.assertIsNone(evidence["age_seconds"])

    def test_started_task_is_not_success_evidence(self):
        TaskHeartbeat.objects.create(task_name=PUBLISHER, state="working", last_started_at=self.now)
        self.assertFalse(task_health(now=self.now)["publisher"]["healthy"])

    def test_recent_generic_completed_task_does_not_establish_publishing_health(self):
        task = Task.objects.create(
            task_name="apps.accounts.tasks.clear_expired_sessions",
            task_params="[[], {}]",
            task_hash="irrelevant completed task",
            run_at=self.now,
        )
        task.create_completed_task()
        self.assertTrue(CompletedTask.objects.filter(task_name=task.task_name).exists())
        self.assertFalse(task_health(now=self.now)["publisher"]["healthy"])
        command = LiveVerifyCommand(stdout=StringIO())
        command.results = []
        command.check_worker()
        self.assertIn("worker.success.publisher", [name for result, name, _ in command.results if result == "BLOCKED"])

    def test_unrelated_heartbeat_cannot_qualify_as_publisher_or_agency(self):
        self.row(name="apps.publisher.tasks.poll_and_publish", success=self.now)
        self.row(name="apps.studio.tasks.sweep_stuck_briefs", success=self.now)
        self.assertFalse(task_health(now=self.now)["publisher"]["healthy"])
        self.assertFalse(task_health(now=self.now)["agency"]["healthy"])

    @override_settings(PUBLISHER_HEARTBEAT_MAX_AGE=120)
    def test_success_age_at_limit_is_healthy_and_reports_elapsed_seconds(self):
        row = self.row(success=self.now - timedelta(seconds=120))
        health = task_health(now=self.now)["publisher"]
        self.assertTrue(health["healthy"])
        self.assertEqual(health["age_seconds"], 120)
        self.assertEqual(health["last_success_at"], row.last_success_at.isoformat())

    @override_settings(PUBLISHER_HEARTBEAT_MAX_AGE=120)
    def test_success_beyond_limit_is_unhealthy(self):
        self.row(success=self.now - timedelta(seconds=121))
        self.assertFalse(task_health(now=self.now)["publisher"]["healthy"])

    @override_settings(PUBLISHER_HEARTBEAT_MAX_AGE=120, AGENCY_HEARTBEAT_MAX_AGE=1800)
    def test_agency_cadence_does_not_make_stale_publishing_healthy(self):
        self.row(success=self.now - timedelta(minutes=5))
        self.row(name=AGENCY, success=self.now - timedelta(minutes=5))
        self.assertFalse(task_health(now=self.now)["publisher"]["healthy"])
        self.assertTrue(task_health(now=self.now)["agency"]["healthy"])

    def test_latest_failure_overrides_recent_success(self):
        self.row(success=self.now - timedelta(seconds=10), failure=self.now, state="error")
        evidence = task_health(now=self.now)["publisher"]
        self.assertFalse(evidence["healthy"])
        self.assertIn("latest cycle failed", evidence["message"])

    def test_equal_failure_and_success_are_conservatively_unhealthy(self):
        self.row(success=self.now, failure=self.now)
        self.assertFalse(task_health(now=self.now)["publisher"]["healthy"])

    def test_later_success_recovers_without_erasing_previous_failure(self):
        self.row(success=self.now, failure=self.now - timedelta(seconds=1))
        evidence = task_health(now=self.now)["publisher"]
        self.assertTrue(evidence["healthy"])
        self.assertIsNotNone(evidence["last_failure_at"])

    def test_future_success_does_not_establish_current_processing(self):
        self.row(success=self.now + timedelta(minutes=5))
        health = task_health(now=self.now)["publisher"]
        self.assertFalse(health["healthy"])
        self.assertIn("system clocks", health["message"])

    def test_small_clock_skew_does_not_invalidate_recent_success(self):
        self.row(success=self.now + timedelta(seconds=30))
        self.assertTrue(task_health(now=self.now)["publisher"]["healthy"])

    def test_clock_skew_beyond_tolerance_is_unhealthy(self):
        self.row(success=self.now + timedelta(seconds=31))
        self.assertFalse(task_health(now=self.now)["publisher"]["healthy"])

    def test_error_or_unknown_state_cannot_hide_behind_a_success_timestamp(self):
        for state in ("error", "unknown"):
            with self.subTest(state=state):
                TaskHeartbeat.objects.update_or_create(
                    task_name=PUBLISHER, defaults={"last_success_at": self.now, "state": state}
                )
                self.assertFalse(task_health(now=self.now)["publisher"]["healthy"])

    def test_in_progress_next_cycle_can_retain_current_previous_success(self):
        self.row(success=self.now - timedelta(seconds=5), state="working")
        self.assertTrue(task_health(now=self.now)["publisher"]["healthy"])

    def test_failure_without_any_success_is_unhealthy(self):
        self.row(failure=self.now, state="error")
        self.assertFalse(task_health(now=self.now)["publisher"]["healthy"])


class RecurringCadenceUpgradeTests(TestCase):
    def test_existing_schedule_cadence_updates_without_rescheduling_or_unlocking(self):
        due = timezone.now() - timedelta(minutes=5)
        locked_at = timezone.now() - timedelta(minutes=1)
        row = Task.objects.get(verbose_name="run_agency_cycle")
        Task.objects.filter(pk=row.pk).update(
            repeat=3600, run_at=due, locked_by="still-running-worker", locked_at=locked_at, attempts=2
        )
        with patch("apps.studio.tasks.run_agency_cycle") as schedule:
            register_recurring_task(schedule, repeat=900, verbose_name="run_agency_cycle")
        schedule.assert_not_called()
        row.refresh_from_db()
        self.assertEqual(
            (row.repeat, row.run_at, row.locked_by, row.locked_at, row.attempts),
            (900, due, "still-running-worker", locked_at, 2),
        )
        self.assertEqual(Task.objects.filter(verbose_name="run_agency_cycle").count(), 1)

    def test_same_cadence_registration_preserves_pending_run_time(self):
        row = Task.objects.get(verbose_name="run_publish_cycle")
        before = (row.pk, row.run_at, row.repeat)
        register_recurring_task(run_publish_cycle, repeat=15, verbose_name="run_publish_cycle")
        row.refresh_from_db()
        self.assertEqual((row.pk, row.run_at, row.repeat), before)


class StrictReleaseVerificationTests(SimpleTestCase):
    def test_strict_verify_implies_verification_and_propagates_the_gate_failure(self):
        calls = []

        def delegated(name, **options):
            calls.append((name, options))
            if name == "live_verify":
                raise CommandError("Worker has no recent successful processing")

        output = StringIO()
        with (
            patch("apps.common.management.commands.release.call_command", side_effect=delegated),
            self.assertRaisesMessage(CommandError, "no recent successful processing"),
        ):
            call_command("release", "--skip-backup", "--strict-verify", stdout=output)
        self.assertEqual([name for name, _ in calls], ["migrate", "live_verify"])
        self.assertTrue(calls[-1][1]["strict"])
        self.assertNotIn("Release steps complete", output.getvalue())

    def test_legacy_verify_remains_best_effort_when_no_strict_flag_is_selected(self):
        def delegated(name, **options):
            if name == "live_verify":
                raise CommandError("Legacy report failure")

        output = StringIO()
        with (
            patch("apps.common.management.commands.release.call_command", side_effect=delegated),
            self.assertLogs("apps.common.management.commands.release", level="ERROR"),
        ):
            call_command("release", "--skip-backup", "--verify", stdout=output)
        self.assertIn("live_verify: FAILED", output.getvalue())
        self.assertIn("Release steps complete", output.getvalue())

    def test_successful_strict_verification_allows_release_completion(self):
        output = StringIO()
        with patch("apps.common.management.commands.release.call_command") as delegated:
            call_command("release", "--skip-backup", "--strict-verify", stdout=output)
        self.assertEqual([call.args[0] for call in delegated.call_args_list], ["migrate", "live_verify"])
        self.assertIn("Release steps complete", output.getvalue())

    def test_plain_release_does_not_implicitly_start_account_or_storage_checks(self):
        with patch("apps.common.management.commands.release.call_command") as delegated:
            ReleaseCommand(stdout=StringIO()).handle(skip_backup=True)
        self.assertEqual([call.args[0] for call in delegated.call_args_list], ["migrate"])


class StrictLiveVerificationTests(SimpleTestCase):
    checks = (
        "check_config",
        "check_database",
        "check_storage",
        "check_worker",
        "check_brands",
        "check_credentials",
        "check_isolation_and_approval",
        "check_accounts",
        "check_blog",
        "check_agency",
        "check_launch_evidence",
    )

    def command(self, evidence):
        command = LiveVerifyCommand(stdout=StringIO())
        for name in self.checks:
            if name == "check_config":

                def emit(evidence=evidence):
                    for status, check in evidence:
                        command.record(status, check, "synthetic offline evidence")

                patcher = patch.object(command, name, side_effect=emit)
            else:
                patcher = patch.object(command, name)
            probe = patcher.start()
            probe.__name__ = name
            self.addCleanup(patcher.stop)
        return command

    def test_strict_fails_on_each_critical_failure_and_blocker(self):
        for status in ("FAIL", "BLOCKED"):
            for check in (
                "worker.success.publisher",
                "agency.provider",
                "accounts.brand.instagram",
                "launch.model_evidence.id",
            ):
                with self.subTest(status=status, check=check):
                    command = self.command([(status, check)])
                    with self.assertRaisesMessage(CommandError, check):
                        command.handle(strict=True)

    def test_optional_x_blog_and_other_optional_accounts_do_not_block_strict_gate(self):
        command = self.command(
            [
                ("BLOCKED", "credentials.x"),
                ("FAIL", "blog.sitemap"),
                ("FAIL", "accounts.brand.x"),
                ("BLOCKED", "accounts.brand.linkedin_company"),
                ("FAIL", "webhooks.meta"),
            ]
        )
        command.handle(strict=True)

    def test_skipped_identity_verification_blocks_strict_gate(self):
        command = self.command([])
        with self.assertRaisesMessage(CommandError, "launch.account_identity"):
            command.handle(strict=True, skip_accounts=True)

    def test_legacy_mode_prints_critical_failures_without_raising(self):
        command = self.command([("FAIL", "worker.success.agency")])
        command.handle(strict=False)
        self.assertIn("worker.success.agency", command.stdout._out.getvalue())

    def test_crashed_critical_check_is_failure_without_exposing_exception_detail(self):
        command = self.command([])
        command.check_worker.side_effect = RuntimeError("sensitive-token-value")
        with self.assertRaisesMessage(CommandError, "check_worker"):
            command.handle(strict=True)
        self.assertNotIn("sensitive-token-value", command.stdout._out.getvalue())


@override_settings(BACKGROUND_TASK_RUN_ASYNC=False)
class RealSingletonWorkerRehearsalTests(TransactionTestCase):
    """Actual queue polling, session lease, task body and PostgreSQL persistence."""

    def test_real_command_processes_required_cycles_through_lease_proxy_once(self):
        from apps.composer.models import Post
        from apps.studio.models import AgencyJob
        from apps.workspaces.models import Workspace

        self.assertFalse(Workspace.objects.exists(), "This rehearsal must have no billable agency work.")
        TaskHeartbeat.objects.all().delete()
        queue = "unbillable-neopolis-worker-rehearsal"
        for proxy in (run_publish_cycle, run_agency_cycle, confirm_pending_publishes):
            proxy(schedule=timezone.now() - timedelta(seconds=1), priority=10000, queue=queue, repeat=60)
        saved_signals = {
            sig: signal.getsignal(sig)
            for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGTSTP, signal.SIGUSR1, signal.SIGUSR2)
        }
        original_poll = _LeaseCheckedTasks.run_next_task
        poll_results = []

        def track_real_poll(lease_tasks, selected_queue=None):
            self.assertIs(lease_tasks.tasks, tasks)
            result = original_poll(lease_tasks, selected_queue)
            poll_results.append(result)
            return result

        command = RunWorkerCommand(stdout=StringIO())
        try:
            with (
                patch("background_task.utils.SignalManager.time_to_wait", [0.0, 0.0]),
                patch.object(_LeaseCheckedTasks, "run_next_task", autospec=True, side_effect=track_real_poll),
            ):
                command.handle(duration=1, sleep=0.01, queue=queue, dev=False, keep_locks=False)
        finally:
            for sig, handler in saved_signals.items():
                signal.signal(sig, handler)

        self.assertEqual(sum(bool(result) for result in poll_results), 3)
        self.assertTrue(all(evidence["healthy"] for evidence in task_health().values()))
        self.assertEqual(CompletedTask.objects.filter(queue=queue).count(), 3)
        remaining = list(Task.objects.filter(queue=queue))
        self.assertEqual(len(remaining), 3)
        self.assertTrue(all(task.attempts == 0 and task.locked_by is None for task in remaining))
        self.assertTrue(all(task.run_at > timezone.now() for task in remaining))
        self.assertFalse(AgencyJob.objects.exists())
        self.assertFalse(Post.objects.exists())
        self.assertIs(command._tasks, tasks, "The original runner must be restored after a successful loop.")
        with worker_process_lock() as check_lease:
            check_lease()
