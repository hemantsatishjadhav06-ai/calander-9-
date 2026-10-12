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

import contextvars
import functools
import hashlib
import logging
from collections.abc import Callable
from contextlib import contextmanager
from datetime import timedelta

import psycopg
from django.db import OperationalError, ProgrammingError, connection, transaction
from django.db.models.signals import post_migrate
from django.utils import timezone

logger = logging.getLogger(__name__)

# Registrars to re-run when the worker starts (see ``connect_recurring_tasks``).
_REGISTRARS: list[Callable[..., None]] = []
_TASK_FAILURES: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar(
    "recurring_task_failures", default=None
)


def note_task_failure(error: Exception | str) -> None:
    """Mark a caught partial failure without losing a recurring task's schedule."""
    failures = _TASK_FAILURES.get()
    if failures is not None:
        failures.append(type(error).__name__ if isinstance(error, Exception) else "PartialFailure")


def _heartbeat(task_name: str, phase: str, started, *, failed: bool = False) -> None:
    from .models import TaskHeartbeat

    try:
        if phase == "start":
            TaskHeartbeat.objects.update_or_create(
                task_name=task_name, defaults={"last_started_at": started, "state": "working"}
            )
        else:
            fields = {"state": "error" if failed else "ok", "updated_at": timezone.now()}
            if failed:
                fields.update(
                    last_failure_at=timezone.now(), error="This recurring task did not complete successfully."
                )
            else:
                fields.update(last_success_at=timezone.now(), error="")
            TaskHeartbeat.objects.filter(task_name=task_name, last_started_at=started).update(**fields)
    except Exception:
        # Missing/stale evidence stays unhealthy. Heartbeat persistence must
        # not turn a completed publishing write into a second attempt.
        logger.error("Could not record recurring task heartbeat for %s", task_name)


def task_health(*, now=None) -> dict:
    """Task-specific durable success evidence; queue registration is separate."""
    from django.conf import settings

    from .models import TaskHeartbeat

    now = now or timezone.now()
    wanted = {
        "publisher": ("apps.publisher.tasks.run_publish_cycle", getattr(settings, "PUBLISHER_HEARTBEAT_MAX_AGE", 120)),
        "agency": ("apps.studio.tasks.run_agency_cycle", getattr(settings, "AGENCY_HEARTBEAT_MAX_AGE", 1800)),
        "confirmation": ("apps.publisher.tasks.confirm_pending_publishes", 300),
    }
    rows = {
        row.task_name: row for row in TaskHeartbeat.objects.filter(task_name__in=[item[0] for item in wanted.values()])
    }
    result = {}
    for key, (name, max_age) in wanted.items():
        row = rows.get(name)
        last_success = row.last_success_at if row else None
        last_failure = row.last_failure_at if row else None
        age = max(0, int((now - last_success).total_seconds())) if last_success else None
        healthy = bool(
            last_success
            and row is not None
            and row.state in {"ok", "working"}
            and last_success <= now + timedelta(seconds=30)
            and age is not None
            and age <= max(30, int(max_age))
            and (last_failure is None or last_failure < last_success)
        )
        message = (
            "Successful processing is current." if healthy else "No recent successful processing; inspect the worker."
        )
        if last_success and last_success > now + timedelta(seconds=30):
            message = "Worker success evidence has a future timestamp; check the system clocks."
        if row and last_failure and (last_success is None or last_failure >= last_success):
            message = "The latest cycle failed; inspect the worker logs and blocked work."
        result[key] = {
            "task_name": name,
            "state": row.state if row else "unknown",
            "healthy": healthy,
            "last_success_at": last_success.isoformat() if last_success else None,
            "last_failure_at": last_failure.isoformat() if last_failure else None,
            "last_started_at": row.last_started_at.isoformat() if row and row.last_started_at else None,
            "age_seconds": age,
            "message": message,
        }
    return result


class WorkerAlreadyRunningError(RuntimeError):
    """Another single-worker process owns the database's worker lease."""


@contextmanager
def worker_process_lock(*, allow_concurrent: bool = False):
    """Keep boot-time lock reclamation away from a live single-worker process.

    A dedicated PostgreSQL connection owns this session advisory lock for the
    worker lifetime. Using Django's normal connection would lose the lock when
    media/model work releases its idle connection. This costs one database
    connection; ``--keep-locks`` explicitly opts out for multiple replicas.
    """
    if allow_concurrent:
        yield lambda: None
        return
    if connection.vendor != "postgresql":
        raise RuntimeError("Single-worker boot locking requires PostgreSQL.")
    lock_connection = psycopg.connect(**connection.get_connection_params())
    try:
        lock_connection.autocommit = True
        with lock_connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [_advisory_lock_key("worker-process-singleton")])
            row = cursor.fetchone()
            acquired = bool(row and row[0])
        if not acquired:
            raise WorkerAlreadyRunningError(
                "Another worker is still running for this database. Stop it before starting this single-worker service."
            )

        def check_lease():
            # A database restart drops every session lease. Exit the old loop
            # instead of letting its ordinary Django connection reconnect and
            # compete with a newly started worker that now owns the lock.
            with lock_connection.cursor() as cursor:
                cursor.execute("SELECT 1")

        yield check_lease
    finally:
        # Session locks vanish on close, including after a crashed run loop.
        lock_connection.close()


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
            existing = Task.objects.filter(verbose_name=verbose_name)
            if not existing.exists():
                task_func(repeat=repeat, verbose_name=verbose_name)
                logger.info("Registered recurring task %s (every %ds)", verbose_name, repeat)
            else:
                # Persist cadence changes across upgrades without resetting
                # pending work or stealing a live worker's task lock.
                existing.exclude(repeat=repeat).update(repeat=repeat)
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

    Production ``run_worker`` holds :func:`worker_process_lock` before calling
    this and throughout its loop, so a second worker cannot clear live locks.
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
        started = timezone.now()
        task_name = f"{func.__module__}.{func.__name__}"
        failures: list[str] = []
        token = _TASK_FAILURES.set(failures)
        _heartbeat(task_name, "start", started)
        try:
            result = func(*args, **kwargs)
            _heartbeat(task_name, "finish", started, failed=bool(failures))
            return result
        except Exception as exc:
            note_task_failure(exc)
            _heartbeat(task_name, "finish", started, failed=True)
            logger.exception("Recurring task %s failed; its schedule is kept", func.__name__)
            return None
        finally:
            _TASK_FAILURES.reset(token)

    return wrapper
