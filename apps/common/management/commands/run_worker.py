"""``process_tasks`` as a deploy target actually runs it.

django-background-tasks' own command has three gaps once it is a service that a
platform starts, stops and restarts on its own:

- It stops gracefully on **SIGTSTP**, not SIGTERM. Every deploy target sends
  SIGTERM (then SIGKILL a few seconds later), so a deploy or a scale-down
  killed the worker mid-task instead of letting it finish the one in flight.
- A killed worker leaves its task rows locked for ``MAX_RUN_TIME`` (an hour),
  and ``run_publish_cycle`` is one of those rows: an hour with no publishing
  after every deploy, with nothing in the logs.
- A schedule django-background-tasks deleted (after ``MAX_ATTEMPTS``
  failures) only came back with the next release's ``migrate``.

This command is ``process_tasks`` with those fixed: it maps SIGTERM and SIGINT
to the same graceful stop (the task in flight finishes; the loop then exits 0),
releases every lock a previous worker left behind, and re-registers the
recurring schedules before the first poll. All of ``process_tasks``' options
(``--duration``, ``--sleep``, ``--queue``, ``--log-std``) still apply.
"""

import logging
import signal

from background_task.management.commands.process_tasks import Command as ProcessTasksCommand
from background_task.utils import SignalManager

from apps.common.background import ensure_recurring_tasks, reclaim_stale_locks

logger = logging.getLogger(__name__)


class Command(ProcessTasksCommand):
    help = "Run the background worker: process_tasks that stops on SIGTERM and repairs its own schedule"

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--keep-locks",
            action="store_true",
            dest="keep_locks",
            help=(
                "Do not release task locks left by other workers on start-up. "
                "Pass this when more than one worker replica shares the database."
            ),
        )

    def handle(self, *args, **options):
        self.sig_manager = SignalManager()
        # SignalManager binds SIGTSTP; platforms send SIGTERM. Same graceful path:
        # kill_now is checked at the top of the run loop, so the task in flight
        # always completes before the process exits.
        signal.signal(signal.SIGTERM, self.sig_manager.exit_gracefully)
        signal.signal(signal.SIGINT, self.sig_manager.exit_gracefully)

        self.prepare(keep_locks=options.get("keep_locks", False))

        if options.get("dev"):
            # Keep --dev working, but the reloader re-imports this module in a
            # child process, so the signal handlers above are re-bound there.
            return super().handle(*args, **options)
        self.run(*args, **options)

    @staticmethod
    def prepare(*, keep_locks: bool = False) -> None:
        """Boot-time repair, separated so tests can exercise it without the loop."""
        if not keep_locks:
            reclaim_stale_locks()
        ensure_recurring_tasks()
        logger.info("Worker ready: recurring schedules verified")
