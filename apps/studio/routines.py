"""Routines: standing instructions in plain words that run on their own.

"Every weekday at 8:30 tell me what's waiting" or "every Monday at 9:00 draft a
market update" becomes a :class:`~apps.studio.models.Routine`. A worker tick
(``tasks.run_routine_tick``, every minute) does two things:

1. :func:`settle_running` closes routines whose run has ended: the job is done
   (idle, with the reply as the run's summary), failed or cancelled (failed),
   or its 45-minute lease ran out while the job is still active (interrupted,
   never retried on its own — a person checks what it did and runs it again);
2. :func:`run_due` starts routines whose time has come, under a row lock that
   a second tick skips, after the same gates every other automatic action
   passes (eligible workspace, provider configured, budget, the author still
   on the team). An *instruction* routine posts its words in the team thread
   as the author's message with ``kind="routine"``, so the manager treats it
   as a standing instruction; a *briefing* routine sends the code-built daily
   briefing (``apps.studio.briefing``, built separately).

Times are workspace-local and :func:`next_run` is DST-safe: the next wall-clock
time is computed in the workspace's zone and then converted. Nothing here
approves, schedules or publishes: a routine only starts the same work a
person could start by typing, and that work ends in Approvals as always.
"""

from __future__ import annotations

import datetime as dt
import importlib
import logging
import zoneinfo
from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import AgencyJob, Conversation, Message, Routine, RoutineRun

logger = logging.getLogger(__name__)

#: A run that hasn't ended by then while its job is still active is interrupted.
LEASE = dt.timedelta(minutes=45)
#: Routines started per tick, so one minute's work stays short.
DUE_PER_TICK = 10
#: The reply's first characters become the run's summary.
SUMMARY_CHARS = 200
MAX_INSTRUCTION = 2000
MAX_TITLE = 120

INTERRUPTED = "The worker stopped during this run. Check what it did, then run it again."
BRIEFING_UNAVAILABLE = "Briefing is not available yet"
BRIEFING_FAILED = "The briefing could not be sent. Run it again."
SETUP_NEEDED = "Your team isn't connected yet. Open Set up to connect it."
AUTHOR_GONE = "The person who wrote this routine is no longer on your team. Delete it, or write it again."
WORKSPACE_PAUSED = "This workspace is paused, so the routine waited."
ALREADY_RUNNING = "This routine is already running."
BUSY = "This routine is busy right now. Try again in a moment."
STARTED = "Started. The result appears in the team thread."
BRIEFING_SENT = "Briefing sent."

WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

#: One-tap suggestions on the Routines page, by key.
SUGGESTIONS: dict[str, dict[str, Any]] = {
    "morning": {
        "title": "Morning briefing",
        "blurb": "Weekdays at 08:30: what's waiting for you, what goes out today, anything that needs a look.",
        "kind": Routine.Kind.BRIEFING,
        "instruction": "",
        "cadence": Routine.Cadence.WEEKDAYS,
        "weekday": None,
        "time": dt.time(8, 30),
    },
    "monday": {
        "title": "Monday plan",
        "blurb": "Mondays at 09:00: the week's posts are planned from your pillars and drafted for your approval.",
        "kind": Routine.Kind.INSTRUCTION,
        "instruction": (
            "Plan this week's posts from our pillars and create the briefs; the team drafts them for my approval."
        ),
        "cadence": Routine.Cadence.WEEKLY,
        "weekday": 0,
        "time": dt.time(9, 0),
    },
    "replies": {
        "title": "Draft replies to new comments",
        "blurb": "Weekdays at 17:00: a reply is drafted for every new comment, for you to send or change.",
        "kind": Routine.Kind.INSTRUCTION,
        "instruction": "Draft replies to new comments and messages from today, for a person to read and send.",
        "cadence": Routine.Cadence.WEEKDAYS,
        "weekday": None,
        "time": dt.time(17, 0),
    },
}


class RoutineError(ValueError):
    """The routine can't be made like that. The text is for the person."""


@dataclass(frozen=True)
class Outcome:
    started: bool
    message: str


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


def zone_of(workspace) -> zoneinfo.ZoneInfo:
    try:
        return zoneinfo.ZoneInfo(workspace.effective_timezone or "UTC")
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return zoneinfo.ZoneInfo("UTC")


def _runs_on(routine: Routine, day: dt.date) -> bool:
    if routine.cadence == Routine.Cadence.DAILY:
        return True
    if routine.cadence == Routine.Cadence.WEEKDAYS:
        return day.weekday() < 5
    return day.weekday() == (routine.weekday if routine.weekday is not None else 0)


def next_run(routine: Routine, after: dt.datetime | None = None) -> dt.datetime:
    """The first run strictly after ``after`` (default now), as an aware UTC datetime.

    The routine's time is a wall-clock time in the workspace's zone: the next
    matching local date is combined with it and only then converted, so a
    routine at 08:30 runs at 08:30 on both sides of a clock change.
    """
    zone = zone_of(routine.workspace)
    after = after or timezone.now()
    local = after.astimezone(zone)
    for offset in range(0, 8):
        day = local.date() + dt.timedelta(days=offset)
        if not _runs_on(routine, day):
            continue
        when = dt.datetime.combine(day, routine.time).replace(tzinfo=zone)
        if when > after:
            return when.astimezone(dt.UTC)
    raise AssertionError("every cadence has a run within a week")


def cadence_words(routine: Routine) -> str:
    """The schedule in words: "Weekdays at 08:30", "Mondays at 09:00"."""
    at = routine.time.strftime("%H:%M")
    if routine.cadence == Routine.Cadence.DAILY:
        return f"Every day at {at}"
    if routine.cadence == Routine.Cadence.WEEKDAYS:
        return f"Weekdays at {at}"
    return f"{WEEKDAY_NAMES[routine.weekday if routine.weekday is not None else 0]}s at {at}"


def _local(when: dt.datetime | None, workspace) -> dt.datetime | None:
    return when.astimezone(zone_of(workspace)) if when else None


def _when_words(when: dt.datetime | None, workspace) -> str:
    local = _local(when, workspace)
    return f"{local:%a %-d %b, %H:%M}" if local else ""


# ---------------------------------------------------------------------------
# Making and changing routines
# ---------------------------------------------------------------------------


def _clean(
    *, kind: str, instruction: str, cadence: str, weekday: int | None, time: dt.time | None, title: str
) -> dict[str, Any]:
    instruction = (instruction or "").strip()
    title = (title or "").strip()
    if kind not in Routine.Kind.values:
        raise RoutineError("Choose what the routine does.")
    if kind == Routine.Kind.INSTRUCTION and not instruction:
        raise RoutineError("Write what the team should do, in plain words.")
    if len(instruction) > MAX_INSTRUCTION:
        raise RoutineError(f"Keep the instruction under {MAX_INSTRUCTION:,} characters.")
    if len(title) > MAX_TITLE:
        raise RoutineError(f"Keep the title under {MAX_TITLE} characters.")
    if cadence not in Routine.Cadence.values:
        raise RoutineError("Choose how often it runs.")
    if cadence == Routine.Cadence.WEEKLY:
        if weekday is None or not 0 <= int(weekday) <= 6:
            raise RoutineError("Choose the day of the week.")
        weekday = int(weekday)
    else:
        weekday = None
    if not isinstance(time, dt.time):
        raise RoutineError("Choose the time of day.")
    return {
        "kind": kind,
        "instruction": instruction,
        "cadence": cadence,
        "weekday": weekday,
        "time": time.replace(second=0, microsecond=0, tzinfo=None),
        "title": title,
    }


def create(
    workspace,
    user,
    *,
    instruction: str,
    cadence: str,
    weekday: int | None,
    time: dt.time | None,
    title: str = "",
    kind: str = Routine.Kind.INSTRUCTION,
    enabled: bool = True,
    conversation: Conversation | None = None,
) -> Routine:
    """Make a routine for ``workspace`` written by ``user``. Raises :class:`RoutineError`."""
    fields = _clean(kind=kind, instruction=instruction, cadence=cadence, weekday=weekday, time=time, title=title)
    if conversation is not None and (
        conversation.workspace_id != workspace.id or conversation.audience != Conversation.Audience.INTERNAL
    ):
        raise RoutineError("A routine runs in one of this workspace's team threads.")
    routine = Routine(workspace=workspace, created_by=user, conversation=conversation, enabled=enabled, **fields)
    routine.next_run_at = next_run(routine)
    routine.save()
    return routine


def propose(
    workspace,
    user,
    *,
    instruction: str,
    cadence: str,
    weekday: int | None,
    time: dt.time | None,
    title: str = "",
    conversation: Conversation | None = None,
) -> Routine:
    """A routine the manager proposed in chat: saved switched off until the person turns it on."""
    return create(
        workspace,
        user,
        instruction=instruction,
        cadence=cadence,
        weekday=weekday,
        time=time,
        title=title,
        enabled=False,
        conversation=conversation,
    )


def suggestion(workspace, user, key: str) -> Routine:
    """One of the Routines page's one-tap suggestions, switched on."""
    if key not in SUGGESTIONS:
        raise RoutineError("That suggestion doesn't exist.")
    preset = SUGGESTIONS[key]
    return create(
        workspace,
        user,
        kind=preset["kind"],
        instruction=preset["instruction"],
        cadence=preset["cadence"],
        weekday=preset["weekday"],
        time=preset["time"],
        title=preset["title"],
    )


def set_enabled(routine: Routine, enabled: bool, now: dt.datetime | None = None) -> Routine:
    """Pause or resume. Resuming schedules the next run from now; nothing runs early."""
    routine.enabled = enabled
    fields = ["enabled", "updated_at"]
    if enabled:
        routine.next_run_at = next_run(routine, now)
        fields.append("next_run_at")
    routine.save(update_fields=fields)
    return routine


def can_change(routine: Routine, user, perms: dict | None) -> bool:
    """Pause, resume or delete: the person who wrote it, or someone who manages the workspace's settings."""
    return bool(
        user is not None
        and (routine.created_by_id == user.pk or (perms or {}).get("manage_workspace_settings") is True)
    )


# ---------------------------------------------------------------------------
# For pages
# ---------------------------------------------------------------------------


def last_result(routine: Routine, run: RoutineRun | None) -> str:
    """One line on how the routine last went, for lists."""
    workspace = routine.workspace
    if routine.status == Routine.Status.RUNNING:
        return "Running now"
    if routine.status == Routine.Status.INTERRUPTED:
        return routine.last_error or INTERRUPTED
    if routine.status == Routine.Status.FAILED:
        return f"Failed: {routine.last_error}" if routine.last_error else "Failed last time"
    if run is None:
        return "Hasn't run yet"
    when = _when_words(run.finished_at or run.started_at, workspace)
    if run.status == RoutineRun.Status.SKIPPED:
        return f"Skipped {when}: {run.summary}" if run.summary else f"Skipped {when}"
    return f"Last run {when}: {run.summary}" if run.summary else f"Last run {when}"


def rows(workspace, limit: int | None = None) -> list[dict[str, Any]]:
    """The workspace's routines for a page: on first, soonest first, then paused ones."""
    routines = list(
        Routine.objects.filter(workspace=workspace)
        .select_related("created_by", "workspace")
        .order_by("-enabled", "next_run_at", "created_at")[: limit or None]
    )
    latest: dict[Any, RoutineRun] = {}
    for run in (
        RoutineRun.objects.filter(routine__in=[r.pk for r in routines])
        .order_by("routine_id", "-started_at")
        .distinct("routine_id")
    ):
        latest[run.routine_id] = run
    out = []
    for routine in routines:
        run = latest.get(routine.pk)
        out.append(
            {
                "id": str(routine.pk),
                "routine": routine,
                "title": routine.display_title,
                "instruction": routine.instruction,
                "kind": routine.kind,
                "is_briefing": routine.kind == Routine.Kind.BRIEFING,
                "cadence_words": cadence_words(routine),
                "next_run": _local(routine.next_run_at, workspace),
                "next_run_words": _when_words(routine.next_run_at, workspace) if routine.enabled else "",
                "enabled": routine.enabled,
                "status": routine.status,
                "running": routine.status == Routine.Status.RUNNING,
                "needs_attention": routine.status in (Routine.Status.INTERRUPTED, Routine.Status.FAILED),
                "last_result": last_result(routine, run),
                "last_job_id": str(run.job_id) if run is not None and run.job_id else "",
                "created_by_id": routine.created_by_id,
                "created_by_name": routine.created_by.name if routine.created_by else "",
            }
        )
    return out


# ---------------------------------------------------------------------------
# The tick
# ---------------------------------------------------------------------------


def _reply_summary(job: AgencyJob) -> str:
    message_id = (job.result or {}).get("message_id")
    if message_id:
        body = Message.objects.filter(pk=message_id, conversation__workspace_id=job.workspace_id).values_list(
            "body", flat=True
        ).first()
        if body:
            return " ".join(body.split())[:SUMMARY_CHARS]
    skipped = (job.result or {}).get("skipped")
    return str(skipped)[:SUMMARY_CHARS] if skipped else "Done."


def _close_run(run: RoutineRun | None, status: str, summary: str, now: dt.datetime) -> None:
    if run is None:
        return
    RoutineRun.objects.filter(pk=run.pk, status=RoutineRun.Status.RUNNING).update(
        status=status, summary=summary[:500], finished_at=now
    )


def _set(routine: Routine, now: dt.datetime, **fields: Any) -> None:
    fields["updated_at"] = now
    Routine.objects.filter(pk=routine.pk).update(**fields)
    for name, value in fields.items():
        setattr(routine, name, value)


def _settle_one(routine: Routine, now: dt.datetime) -> bool:
    run = routine.runs.filter(status=RoutineRun.Status.RUNNING).select_related("job").order_by("-started_at").first()
    job = run.job if run is not None else None
    expired = routine.lease_until is not None and routine.lease_until < now
    if job is None:
        if not expired:
            return False
        _set(routine, now, status=Routine.Status.INTERRUPTED, lease_until=None, last_error=INTERRUPTED)
        _close_run(run, RoutineRun.Status.INTERRUPTED, INTERRUPTED, now)
        _notify_creator(routine, run, INTERRUPTED)
        return True
    if job.status == AgencyJob.Status.DONE:
        summary = _reply_summary(job)
        _set(routine, now, status=Routine.Status.IDLE, lease_until=None, last_error="")
        _close_run(run, RoutineRun.Status.FINISHED, summary, now)
        return True
    if job.status in (AgencyJob.Status.FAILED, AgencyJob.Status.CANCELLED):
        error = (job.error or "").strip() if job.status == AgencyJob.Status.FAILED else "The run was stopped."
        error = error or "The run failed."
        _set(routine, now, status=Routine.Status.FAILED, lease_until=None, last_error=error[:500])
        _close_run(run, RoutineRun.Status.FAILED, error, now)
        _notify_creator(routine, run, error)
        return True
    if expired:
        # The job is still queued or working past the lease: the worker most
        # likely died with it. Leave the job as it is for a person to look at;
        # the routine is not started again until someone says so.
        _set(routine, now, status=Routine.Status.INTERRUPTED, lease_until=None, last_error=INTERRUPTED)
        _close_run(run, RoutineRun.Status.INTERRUPTED, INTERRUPTED, now)
        _notify_creator(routine, run, INTERRUPTED)
        return True
    return False


def settle_running(now: dt.datetime | None = None) -> int:
    """Close the runs that have ended (see the module docstring). Returns routines settled."""
    now = now or timezone.now()
    settled = 0
    for pk in list(Routine.objects.filter(status=Routine.Status.RUNNING).values_list("pk", flat=True)):
        try:
            with transaction.atomic():
                routine = (
                    Routine.objects.select_for_update(of=("self",), skip_locked=True)
                    .select_related("workspace", "created_by")
                    .filter(pk=pk, status=Routine.Status.RUNNING)
                    .first()
                )
                if routine is not None and _settle_one(routine, now):
                    settled += 1
        except Exception as exc:
            from apps.common.background import note_task_failure

            note_task_failure(exc)
            logger.exception("Routines: could not settle routine %s", pk)
    return settled


def _blocker(routine: Routine) -> str:
    """Why this routine can't start now, in a sentence for the person; "" when it can."""
    from . import autopilot, budget, chat, llm

    workspace = routine.workspace
    if not autopilot.eligible_workspaces().filter(pk=workspace.pk).exists():
        return WORKSPACE_PAUSED
    author = routine.created_by
    if author is None or not author.is_active or not chat.is_staff(author, workspace):
        return AUTHOR_GONE
    if routine.kind == Routine.Kind.INSTRUCTION:
        if not llm.is_configured():
            return SETUP_NEEDED
        if not budget.can_spend(workspace):
            return budget.over_budget_message(workspace)
    return ""


def _skip(routine: Routine, now: dt.datetime, reason: str) -> None:
    """Record why the run didn't happen and move on to the next time."""
    reason = reason[:500]
    RoutineRun.objects.create(
        routine=routine, status=RoutineRun.Status.SKIPPED, summary=reason, started_at=now, finished_at=now
    )
    _set(routine, now, last_error=reason, next_run_at=next_run(routine, now))


def _thread(routine: Routine) -> Conversation:
    from . import chat

    workspace = routine.workspace
    if routine.conversation_id is not None:
        found = (
            chat.web_conversations(workspace)
            .filter(pk=routine.conversation_id, audience=Conversation.Audience.INTERNAL)
            .select_related("workspace")
            .first()
        )
        if found is not None:
            return found
    return chat.general_conversation(workspace, created_by=routine.created_by)


def _start(routine: Routine, now: dt.datetime) -> bool:
    """Start one run of ``routine`` (the caller holds its row lock). True when it started."""
    from . import chat

    reason = _blocker(routine)
    if reason:
        _skip(routine, now, reason)
        return False
    if routine.kind == Routine.Kind.BRIEFING:
        try:
            send_daily = importlib.import_module("apps.studio.briefing").send_daily
        except (ImportError, AttributeError):
            _skip(routine, now, BRIEFING_UNAVAILABLE)
            _set(routine, now, status=Routine.Status.IDLE)
            return False
        run = RoutineRun.objects.create(routine=routine, started_at=now)
        try:
            send_daily(routine.workspace, routine=routine)
        except Exception:
            logger.exception("Routines: the briefing for routine %s failed", routine.pk)
            _set(
                routine,
                now,
                status=Routine.Status.FAILED,
                last_run_at=now,
                last_error=BRIEFING_FAILED,
                next_run_at=next_run(routine, now),
            )
            _close_run(run, RoutineRun.Status.FAILED, BRIEFING_FAILED, now)
            _notify_creator(routine, run, BRIEFING_FAILED)
            return False
        _set(
            routine,
            now,
            status=Routine.Status.IDLE,
            last_run_at=now,
            last_error="",
            lease_until=None,
            next_run_at=next_run(routine, now),
        )
        _close_run(run, RoutineRun.Status.FINISHED, BRIEFING_SENT, now)
        return True
    conversation = _thread(routine)
    try:
        posted = chat.post_message(conversation, routine.created_by, routine.instruction, kind="routine")
    except chat.ChatError as exc:
        _skip(routine, now, str(exc))
        return False
    if posted.job is None:
        _skip(routine, now, posted.note or "The team couldn't take this now.")
        return False
    RoutineRun.objects.create(routine=routine, job=posted.job, started_at=now)
    _set(
        routine,
        now,
        status=Routine.Status.RUNNING,
        lease_until=now + LEASE,
        last_run_at=now,
        last_error="",
        next_run_at=next_run(routine, now),
    )
    return True


def run_due(limit: int = DUE_PER_TICK, now: dt.datetime | None = None) -> int:
    """Start the routines whose time has come, a few per tick. Returns runs started.

    The due rows are locked with ``skip_locked``, so two ticks (two workers,
    or a tick and "Run now") never start the same routine twice; a routine
    that can't start is skipped with a sentence and moved to its next time.
    """
    now = now or timezone.now()
    started = 0
    with transaction.atomic():
        due = (
            Routine.objects.select_for_update(of=("self",), skip_locked=True)
            .select_related("workspace", "workspace__organization", "created_by")
            .filter(enabled=True, next_run_at__lte=now)
            .exclude(status=Routine.Status.RUNNING)
            .order_by("next_run_at", "created_at")[: max(0, limit)]
        )
        for routine in due:
            try:
                with transaction.atomic():
                    started += _start(routine, now)
            except Exception as exc:
                from apps.common.background import note_task_failure

                note_task_failure(exc)
                logger.exception("Routines: could not start routine %s", routine.pk)
                try:
                    _skip(routine, now, "Something went wrong starting this routine. Run it again.")
                except Exception:
                    logger.exception("Routines: could not record the skip for routine %s", routine.pk)
    return started


def run_now(routine: Routine, now: dt.datetime | None = None) -> Outcome:
    """Start ``routine`` right away (a person pressed Run now): the same path as the tick."""
    now = now or timezone.now()
    with transaction.atomic():
        locked = (
            Routine.objects.select_for_update(of=("self",), skip_locked=True)
            .select_related("workspace", "workspace__organization", "created_by")
            .filter(pk=routine.pk)
            .first()
        )
        if locked is None:
            return Outcome(False, BUSY)
        if locked.status == Routine.Status.RUNNING:
            return Outcome(False, ALREADY_RUNNING)
        if _start(locked, now):
            return Outcome(True, BRIEFING_SENT if locked.kind == Routine.Kind.BRIEFING else STARTED)
        return Outcome(False, locked.last_error or "The routine couldn't start.")


def tick(now: dt.datetime | None = None) -> dict[str, int]:
    """One tick: settle, then start. What ``tasks.run_routine_tick`` calls."""
    now = now or timezone.now()
    return {"settled": settle_running(now), "started": run_due(DUE_PER_TICK, now)}


# ---------------------------------------------------------------------------
# Telling the person
# ---------------------------------------------------------------------------


def _notify_creator(routine: Routine, run: RoutineRun | None, body: str) -> bool:
    """One in-app notice to the routine's author per run (Telegram delivery is wired elsewhere)."""
    from apps.notifications.engine import notify
    from apps.notifications.models import EventType, Notification

    from . import chat

    user = routine.created_by
    if user is None or not user.is_active:
        return False
    run_id = str(run.pk) if run is not None else ""
    if run_id and Notification.objects.filter(user=user, event_type=EventType.TEAM_MESSAGE, data__run_id=run_id).exists():
        return False
    try:
        path = reverse("studio:routines", kwargs={"workspace_id": routine.workspace_id})
        notify(
            user=user,
            event_type=EventType.TEAM_MESSAGE,
            title=f"A routine needs you: {routine.display_title}"[:255],
            body=body[:500],
            data={
                "workspace_id": str(routine.workspace_id),
                "routine_id": str(routine.pk),
                "run_id": run_id,
                "kind": "routine",
                "action_url": chat.absolute_url(path),
            },
        )
    except Exception:
        logger.exception("Routines: could not notify the author of routine %s", routine.pk)
        return False
    return True
