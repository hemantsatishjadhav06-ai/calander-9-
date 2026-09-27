"""Shared helpers for the recurring django-background-tasks jobs.

Three things live here, all in service of one property: the recurring jobs
(publishing, inbox sync, retries, reminders, cleanups) keep running after any
single failure, deploy or crash.

- :func:`register_recurring_task` schedules a ``@background`` task to repeat,
  exactly once, under a database lock so two processes migrating at the same
  moment cannot both insert it.
- :func:`connect_recurring_tasks` wires an app's registrar to ``post_migrate``
  *and* to the worker's start-up, so a schedule that django-background-tasks
  deleted (it drops a task after ``MAX_ATTEMPTS`` failures) comes back on the
  next worker boot rather than on the next release.
- :func:`keep_schedule` wraps a recurring task's body so an exception is
  logged instead of raised: a raising task is backed off ``attempts ** 4 + 5``
  seconds and eventually deleted, which turns "every 15 seconds" into "never".
"""

import functools
import hashlib
import logging
from collections.abc import Callable

from django.db import OperationalError, ProgrammingError, connection, transaction
from django.db.models.signals import post_migrate

logger = logging.getLogger(__name__)

# Registrars to re-run when the worker starts (see ``connect_recurring_tasks``).
_REGISTRARS: list[Callable[..., None]] = []


def _advisory_lock_key(verbose_name: str) -> int:
    """A stable signed 64-bit key for ``pg_advisory_xact_lock``."""
    digest = hashlib.sha1(f"recurring-task:{verbose_name}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def register_recurring_task(task_func, *, repeat, verbose_name):
    """Idempotently schedule a ``@background`` task to repeat every ``repeat`` seconds.

    Safe to call from a ``post_migrate`` handler and from the worker's start-up.
    The exists-check and insert run in one transaction under a Postgres
    transaction-scoped advisory lock keyed on ``verbose_name``, so concurrent
    callers (two containers running ``migrate`` during a deploy, the web
    service's start-up migrate racing the worker's boot) serialise and the
    second one sees the first one's row. Other databases skip the lock.

    A fresh DB without the background-task tables raises a DB error, which we
    swallow quietly (the next ``migrate`` re-runs registration). Any OTHER
    failure is logged at ``exception`` rather than swallowed silently — the
    worker is the only thing that runs these, so a missed registration means
    the task never runs, and that must be visible (production logs the ``apps``
    logger at INFO).
    """
    from background_task.models import Task

    try:
        with transaction.atomic():
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_advisory_lock_key(verbose_name)])
            if not Task.objects.filter(verbose_name=verbose_name).exists():
                task_func(repeat=repeat, verbose_name=verbose_name)
                logger.info("Registered recurring task %s (every %ds)", verbose_name, repeat)
    except (OperationalError, ProgrammingError):
        # Fresh DB: the background-task tables don't exist yet. The next migrate
        # re-runs this registration, so skip quietly.
        logger.debug("Skipping %s registration (database not ready)", verbose_name)
    except Exception:
        logger.exception("Failed to register recurring task %s", verbose_name)


def connect_recurring_tasks(app_config, registrar: Callable[..., None]) -> None:
    """Run ``registrar`` after ``app_config`` migrates and whenever the worker starts.

    ``registrar`` takes the ``post_migrate`` signature (``sender, **kwargs``) and
    calls :func:`register_recurring_task` for each of the app's recurring jobs.
    Call this from ``AppConfig.ready``.
    """
    post_migrate.connect(registrar, sender=app_config)
    if registrar not in _REGISTRARS:
        _REGISTRARS.append(registrar)


def ensure_recurring_tasks() -> None:
    """Re-run every registrar: whatever schedule is missing is put back.

    The worker calls this on boot. Registration is idempotent, so on a healthy
    database this is a handful of ``SELECT``\\s; it only inserts when
    django-background-tasks has deleted a schedule (after ``MAX_ATTEMPTS``
    failures) or a database was restored from a backup taken before a task
    existed. Without it, the only thing that would bring a deleted schedule
    back is the next release's ``migrate``.
    """
    for registrar in list(_REGISTRARS):
        registrar(sender=None)


def reclaim_stale_locks() -> int:
    """Release every task lock left behind by a worker that is no longer running.

    django-background-tasks locks a task row with the worker's PID while it
    runs and only ``MAX_RUN_TIME`` (an hour) later treats the lock as expired.
    A worker killed mid-task — a deploy, an OOM kill, a platform restart —
    therefore leaves that task, ``run_publish_cycle`` included, untouchable
    for the next hour, and with a single worker that is an hour with no
    publishing at all.

    This assumes one worker process per database, which is how every shipped
    deploy target runs (``Procfile``, ``railway.toml``, ``render.yaml``,
    ``docker-compose.yml``). With several worker replicas pass
    ``--keep-locks`` to ``run_worker`` and rely on ``MAX_RUN_TIME`` instead.

    Returns the number of locks released.
    """
    from background_task.models import Task

    released = Task.objects.filter(locked_by__isnull=False).update(locked_by=None, locked_at=None)
    if released:
        logger.warning("Released %d task lock(s) left by a previous worker", released)
    return released


def keep_schedule(func):
    """Log and swallow, so a raising run keeps the recurring schedule.

    Apply *under* ``@background`` (closest to the function). django-background-
    tasks reacts to a raising task by backing off ``attempts ** 4 + 5`` seconds
    and, after ``MAX_ATTEMPTS`` (25) failures, deleting the task outright with
    no repetition — so a single bad row in a sweep turns "every minute" into
    "every few hours" and then into "never", silently. Logging at ``exception``
    keeps the failure visible (and reaches Sentry when configured) without
    losing the schedule.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception:
            logger.exception("Recurring task %s failed; its schedule is kept", func.__name__)
            return None

    return wrapper
