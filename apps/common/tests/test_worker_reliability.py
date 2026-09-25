"""The worker survives what a platform does to it: deploys, kills and bad rows.

- A recurring task that raises keeps its schedule instead of backing off
  towards deletion.
- ``run_worker`` stops on SIGTERM (what every deploy target sends), releases
  the locks a killed worker left behind, and puts back any schedule that
  django-background-tasks deleted.
- Two processes registering the same schedule at once insert it once.
"""

import signal
import threading
from datetime import timedelta
from unittest.mock import patch

from background_task import background
from background_task.models import Task
from background_task.tasks import tasks
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.common.background import keep_schedule, register_recurring_task
from apps.common.management.commands.run_worker import Command


@background(schedule=0)
@keep_schedule
def _guarded_probe():
    raise RuntimeError("one bad row")


@background(schedule=0)
def _unguarded_probe():
    raise RuntimeError("one bad row")


def _row(verbose_name):
    return Task.objects.get(verbose_name=verbose_name)


class KeepScheduleTests(TestCase):
    def test_a_raising_guarded_task_is_repeated_on_time(self):
        _guarded_probe(repeat=60, verbose_name="probe_guarded")
        before = _row("probe_guarded")

        with self.assertLogs("apps.common.background", level="ERROR") as logs:
            tasks.run_task(before)

        after = _row("probe_guarded")
        self.assertNotEqual(after.pk, before.pk, "the run should have created the next repetition")
        self.assertEqual(after.attempts, 0)
        self.assertEqual(after.last_error, "")
        self.assertAlmostEqual(after.run_at, before.run_at + timedelta(seconds=60), delta=timedelta(seconds=5))
        self.assertIn("one bad row", "\n".join(logs.output))

    def test_the_library_would_otherwise_back_off(self):
        """Documents the failure mode the guard exists for."""
        _unguarded_probe(repeat=60, verbose_name="probe_unguarded")
        before = _row("probe_unguarded")

        tasks.run_task(before)

        after = _row("probe_unguarded")
        self.assertEqual(after.pk, before.pk)
        self.assertEqual(after.attempts, 1)
        self.assertIn("one bad row", after.last_error)
        # It is now on the attempts ** 4 + 5 backoff and, at MAX_ATTEMPTS, deleted.

    def test_every_shipped_recurring_task_is_guarded(self):
        from apps.accounts import tasks as accounts
        from apps.approvals import tasks as approvals
        from apps.inbox import tasks as inbox
        from apps.media_library import tasks as media
        from apps.notifications import tasks as notifications
        from apps.publisher import tasks as publisher

        for proxy in (
            publisher.run_publish_cycle,
            publisher.confirm_pending_publishes,
            inbox.run_inbox_sync_cycle,
            approvals.run_approval_reminders_cycle,
            notifications.retry_failed_deliveries,
            media.sweep_pending_uploads,
            media.run_orphaned_media_sweep,
            accounts.clear_expired_sessions,
        ):
            with self.subTest(task=proxy.name):
                # keep_schedule wraps with functools.wraps, which leaves __wrapped__.
                self.assertTrue(hasattr(proxy.task_function, "__wrapped__"), f"{proxy.name} is unguarded")


class RunWorkerCommandTests(TestCase):
    def setUp(self):
        self._term = signal.getsignal(signal.SIGTERM)
        self._int = signal.getsignal(signal.SIGINT)
        self._tstp = signal.getsignal(signal.SIGTSTP)

    def tearDown(self):
        signal.signal(signal.SIGTERM, self._term)
        signal.signal(signal.SIGINT, self._int)
        signal.signal(signal.SIGTSTP, self._tstp)

    def test_sigterm_stops_the_loop_after_the_task_in_flight(self):
        command = Command()
        with patch.object(Command, "run") as run:
            command.handle(duration=0, sleep=0.01, dev=False, keep_locks=True)
        run.assert_called_once()

        signal.raise_signal(signal.SIGTERM)
        self.assertTrue(command.sig_manager.kill_now)

        # The loop consults kill_now before polling, so nothing else runs.
        with patch.object(tasks, "run_next_task") as poll:
            command.run(duration=0, sleep=0.01)
        poll.assert_not_called()

    def test_boot_releases_locks_a_dead_worker_left(self):
        stale = Task.objects.get(verbose_name="run_publish_cycle")
        Task.objects.filter(pk=stale.pk).update(locked_by="4242", locked_at=timezone.now())

        Command.prepare()

        stale.refresh_from_db()
        self.assertIsNone(stale.locked_by)
        self.assertIsNone(stale.locked_at)

    def test_keep_locks_leaves_other_replicas_alone(self):
        stale = Task.objects.get(verbose_name="run_publish_cycle")
        Task.objects.filter(pk=stale.pk).update(locked_by="4242", locked_at=timezone.now())

        Command.prepare(keep_locks=True)

        stale.refresh_from_db()
        self.assertEqual(stale.locked_by, "4242")

    def test_boot_puts_back_a_schedule_the_library_deleted(self):
        Task.objects.filter(verbose_name__in=["run_publish_cycle", "run_inbox_sync_cycle"]).delete()

        Command.prepare(keep_locks=True)

        self.assertEqual(Task.objects.filter(verbose_name="run_publish_cycle").count(), 1)
        self.assertEqual(Task.objects.filter(verbose_name="run_inbox_sync_cycle").count(), 1)

    def test_boot_is_idempotent_on_a_healthy_database(self):
        before = set(Task.objects.values_list("verbose_name", "pk"))
        Command.prepare(keep_locks=True)
        self.assertEqual(set(Task.objects.values_list("verbose_name", "pk")), before)


class ConcurrentRegistrationTests(TransactionTestCase):
    def test_parallel_registrations_insert_one_row(self):
        """Web and worker containers both run registration during a deploy."""
        workers = 6
        barrier = threading.Barrier(workers)
        errors = []

        def register():
            try:
                barrier.wait(timeout=10)
                register_recurring_task(_guarded_probe, repeat=60, verbose_name="probe_parallel")
            except Exception as exc:  # pragma: no cover - surfaced by the assertion below
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=register) for _ in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertEqual(errors, [])
        self.assertEqual(Task.objects.filter(verbose_name="probe_parallel").count(), 1)
