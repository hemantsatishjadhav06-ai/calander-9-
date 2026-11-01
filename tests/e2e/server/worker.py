"""The worker, in a thread of the e2e server process.

It mirrors ``apps/common/management/commands/run_worker.py``: the PostgreSQL session lease
(``worker_process_lock``), the release of locks a previous worker left, the recurring schedules put
back, and ``run_next_task`` under the lease checks. It runs in the server's process because the
fakes are module attributes the request threads and the worker must share.

One difference, on purpose: the platform polls (inbox sync, analytics sync, account health checks)
are taken off the schedule. With no network they could only reach the mock's refusal, which would
fill the ``refused_network`` probe with platform hosts no browser path asked for. The paths that
need a comment post the signed webhook instead.

:func:`hold` stops the loop between tasks, and :func:`resume` lets it go on: the visual specs hold it
while the server's clock is frozen (``steps/visual.py``), so it never acts on a moment that is not now.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
from typing import Any

logger = logging.getLogger("tests.e2e.worker")

#: Recurring schedules (``verbose_name``) the e2e worker does not run.
PLATFORM_POLLS = ("run_inbox_sync_cycle", "sync_all_account_analytics", "schedule_all_health_checks")

_lock = threading.Lock()
_status: dict[str, Any] = {
    "alive": False,
    "ran": 0,
    "idle_polls": 0,
    "last_poll": 0.0,
    "error": "",
    "dropped": [],
    "holding": False,
}
_paused = threading.Event()
#: How long :func:`hold` waits for a task in flight to finish (a slowed fake turn takes up to 60 s).
HOLD_TIMEOUT_SECONDS = 90.0


def status() -> dict[str, Any]:
    with _lock:
        return {**_status, "dropped": list(_status["dropped"]), "paused": _paused.is_set()}


def _update(**fields: Any) -> None:
    with _lock:
        _status.update(fields)


def pause() -> None:
    _paused.set()


def resume() -> None:
    _paused.clear()


def hold(timeout: float = HOLD_TIMEOUT_SECONDS) -> bool:
    """Pause the worker and wait until its loop is between tasks and staying there.

    Returns whether a running worker is held (False when none runs: ``--no-worker``, or pytest). Raises
    ``TimeoutError`` when a task in flight does not finish within ``timeout`` seconds; the worker
    stays paused, so it starts nothing new.
    """
    _paused.set()
    deadline = time.monotonic() + timeout
    while True:
        with _lock:
            alive, holding = _status["alive"], _status["holding"]
        if not alive:
            return False
        if holding:
            return True
        if time.monotonic() > deadline:
            raise TimeoutError(f"The e2e worker did not finish its task within {timeout:g} seconds.")
        time.sleep(0.05)


def drop_platform_polls() -> list[str]:
    from background_task.models import Task

    dropped = sorted(set(Task.objects.filter(verbose_name__in=PLATFORM_POLLS).values_list("verbose_name", flat=True)))
    Task.objects.filter(verbose_name__in=PLATFORM_POLLS).delete()
    return dropped


def run_forever(stop: threading.Event | None = None) -> None:
    """The worker loop; returns when ``stop`` is set. Never raises: the error lands in :func:`status`."""
    from background_task.tasks import autodiscover, tasks
    from django.db import close_old_connections, connections

    from apps.common.background import (
        ensure_recurring_tasks,
        reclaim_stale_locks,
        worker_lease_checks,
        worker_process_lock,
    )

    stop = stop or threading.Event()
    _update(alive=False, ran=0, idle_polls=0, error="", holding=False)
    try:
        autodiscover()
        with worker_process_lock() as check_lease:
            check_lease()
            reclaim_stale_locks()
            ensure_recurring_tasks()
            _update(alive=True, dropped=drop_platform_polls())
            logger.info("e2e worker ready")
            while not stop.is_set():
                # Deciding to hold and saying so are one step under the lock, so hold() never reads
                # "holding" from an earlier pause while this pass goes on to run a task.
                with _lock:
                    _status["last_poll"] = time.time()
                    held = _paused.is_set()
                    _status["holding"] = held
                if held:
                    close_old_connections()
                    stop.wait(0.3)
                    continue
                check_lease()
                with worker_lease_checks(check_lease):
                    ran = tasks.run_next_task(None)
                if ran:
                    with _lock:
                        _status["ran"] += 1
                    stop.wait(0.05)
                else:
                    with _lock:
                        _status["idle_polls"] += 1
                    close_old_connections()
                    stop.wait(0.5)
    except BaseException as exc:  # a stopped worker is reported, never raised into the server
        _update(error="".join(traceback.format_exception(exc))[-3000:])
        logger.error("e2e worker stopped: %s", exc)
    finally:
        _update(alive=False, holding=False)
        connections.close_all()


def start() -> threading.Thread:
    thread = threading.Thread(target=run_forever, name="e2e-worker", daemon=True)
    thread.start()
    return thread
