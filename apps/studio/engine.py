"""The agency's job runner: weekly plans, articles, thread replies, inbox drafts, reports, learning.

A post goes through ``apps.studio.pipeline``. Everything else the team does is
an :class:`~apps.studio.models.AgencyJob`, and this module runs it with the
same rules the post pipeline keeps:

* one stage per worker task, queued after the current transaction commits, at a
  priority below publishing (people waiting on a reply go first, learning last);
* a stage re-checks, under a row lock, that the job is still on the same
  revision and stage and still active before it starts, and every write it
  makes is conditional on that revision (:func:`save`), so a person who cancels
  or asks again mid-run is never overwritten by a stale stage;
* a stage never raises out of its task: an error marks the job failed with a
  sentence for people, and Retry resumes at the failed stage;
* a sweep fails jobs whose worker died, but leaves alone jobs that are only
  waiting their turn in the queue.

The stages of each kind are declared in ``apps.studio.jobs`` (``JOB_TYPES``).
A stage function takes the job and returns the next stage's name, or None when
the job is finished (it then calls :func:`finish`). Nothing here approves,
schedules or publishes anything.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from . import guards, llm
from .models import AgencyJob, AgentRun

logger = logging.getLogger(__name__)

#: django-background-tasks runs higher numbers first; publishing uses 0 and
#: post briefs -10.
PRIORITY_CHAT = -8
PRIORITY_DEFAULT = -15
PRIORITY_BACKGROUND = -30

JobError = llm.StudioAgentError


class StaleJobError(Exception):
    """The job moved on (new revision, cancelled) while a stage was running."""


@dataclass(frozen=True)
class Stage:
    name: str
    agent: str
    run: Callable[[AgencyJob], str | None]


@dataclass(frozen=True)
class JobType:
    kind: str
    stages: tuple[Stage, ...]
    priority: int = PRIORITY_DEFAULT
    stuck_after: timedelta = timedelta(minutes=30)
    labels: dict[str, str] = field(default_factory=dict)

    @property
    def first(self) -> str:
        return self.stages[0].name

    def stage(self, name: str) -> Stage | None:
        return next((s for s in self.stages if s.name == name), None)


def job_type(kind: str) -> JobType:
    from .jobs import JOB_TYPES

    return JOB_TYPES[kind]


# ---------------------------------------------------------------------------
# Queueing
# ---------------------------------------------------------------------------


def enqueue(job: AgencyJob, stage: str) -> None:
    """Queue ``stage`` of ``job`` once the current transaction commits."""
    from .tasks import run_agency_step

    job_id, revision, priority = str(job.pk), job.revision, job_type(job.kind).priority
    transaction.on_commit(lambda: run_agency_step(job_id, revision, stage, priority=priority))


def create(
    workspace,
    kind: str,
    *,
    title: str = "",
    input: dict[str, Any] | None = None,
    requested_by=None,
    parent: AgencyJob | None = None,
    brief=None,
    blog_post=None,
    conversation=None,
    start: bool = True,
) -> AgencyJob:
    """Create a job of ``kind`` and (by default) queue its first stage."""
    jt = job_type(kind)
    job = AgencyJob.objects.create(
        workspace=workspace,
        kind=kind,
        title=title[:200],
        input=input or {},
        requested_by=requested_by,
        parent=parent,
        brief=brief,
        blog_post=blog_post,
        conversation=conversation,
        stage=jt.first,
    )
    if start:
        enqueue(job, jt.first)
    return job


def restart(job: AgencyJob, stage: str | None = None) -> None:
    """Start ``job`` again from ``stage`` (default: where it stopped) on a new revision."""
    jt = job_type(job.kind)
    stage = stage if stage and jt.stage(stage) else (job.stage if jt.stage(job.stage) else jt.first)
    job.revision += 1
    job.status = AgencyJob.Status.QUEUED
    job.stage = stage
    job.error = ""
    job.finished_at = None
    job.save(update_fields=["revision", "status", "stage", "error", "finished_at", "updated_at"])
    enqueue(job, stage)


def cancel(job: AgencyJob) -> None:
    AgencyJob.objects.filter(pk=job.pk, status__in=AgencyJob.ACTIVE_STATUSES).update(
        status=AgencyJob.Status.CANCELLED, updated_at=timezone.now(), finished_at=timezone.now()
    )
    _close_running(job, "Cancelled.")


# ---------------------------------------------------------------------------
# Running a stage
# ---------------------------------------------------------------------------


def save(job: AgencyJob, **fields: Any) -> None:
    """Write stage results, but only while the job is still on the stage's revision."""
    fields["updated_at"] = timezone.now()
    updated = AgencyJob.objects.filter(pk=job.pk, revision=job.revision, status=AgencyJob.Status.WORKING).update(
        **fields
    )
    if not updated:
        raise StaleJobError
    for name, value in fields.items():
        setattr(job, name, value)


def update_state(job: AgencyJob, **changes: Any) -> None:
    """Merge ``changes`` into ``job.state`` (revision-guarded)."""
    save(job, state={**(job.state or {}), **changes})


def finish(job: AgencyJob, *, result: dict[str, Any] | None = None) -> None:
    """Mark the job done (revision-guarded)."""
    save(
        job,
        status=AgencyJob.Status.DONE,
        stage="done",
        result={**(job.result or {}), **(result or {})},
        finished_at=timezone.now(),
    )


def run_step(job_id: str, revision: int, stage_name: str) -> None:
    """Run one stage of one job, then queue the next. Never raises."""
    with transaction.atomic():
        job = (
            AgencyJob.objects.select_for_update(of=("self",))
            .select_related("workspace", "workspace__organization", "requested_by")
            .filter(pk=job_id)
            .first()
        )
        if job is None or job.revision != revision or job.stage != stage_name or not job.is_active:
            logger.info("Agency: skipping stale stage %s of job %s (r%s)", stage_name, job_id, revision)
            return
        job.status = AgencyJob.Status.WORKING
        job.started_at = job.started_at or timezone.now()
        job.save(update_fields=["status", "started_at", "updated_at"])

    jt = job_type(job.kind)
    stage = jt.stage(stage_name)
    if stage is None:
        fail(job, "This job reached a step that no longer exists. Start it again.")
        return
    try:
        with guards.agent_work(f"{job.kind} job {job_id} {stage_name}"):
            next_stage = stage.run(job)
    except StaleJobError:
        logger.info("Agency: job %s moved on during %s; stopping this run", job_id, stage_name)
        _close_running(job, "Superseded by a newer request.", status=AgentRun.Status.SKIPPED)
        return
    except JobError as exc:
        fail(job, str(exc))
        return
    except Exception:
        logger.exception("Agency: stage %s of job %s crashed", stage_name, job_id)
        from . import team

        fail(job, f"The {team.name(stage.agent).lower()} hit an unexpected error. Press Retry.")
        return

    if next_stage is None:
        return
    with transaction.atomic():
        moved = AgencyJob.objects.filter(pk=job.pk, revision=revision, status=AgencyJob.Status.WORKING).update(
            stage=next_stage, updated_at=timezone.now()
        )
        if moved:
            job.stage = next_stage
            enqueue(job, next_stage)


def fail(job: AgencyJob, message: str) -> None:
    AgencyJob.objects.filter(pk=job.pk, revision=job.revision).exclude(status=AgencyJob.Status.CANCELLED).update(
        status=AgencyJob.Status.FAILED, error=message[:2000], updated_at=timezone.now()
    )
    _close_running(job, message)
    _after_failure(job, message)


def _close_running(job: AgencyJob, message: str, *, status: str = AgentRun.Status.FAILED) -> None:
    AgentRun.objects.filter(job=job, status=AgentRun.Status.RUNNING).update(
        status=status, error=message[:2000], finished_at=timezone.now()
    )


def _after_failure(job: AgencyJob, message: str) -> None:
    """Tell the person waiting in a thread that their request failed."""
    if job.kind != AgencyJob.Kind.CHAT or job.conversation_id is None:
        return
    try:
        from .chat import post_failure_note

        post_failure_note(job, message)
    except Exception:
        logger.exception("Agency: could not post the failure note for job %s", job.pk)


# ---------------------------------------------------------------------------
# The timeline (AgentRun rows for jobs)
# ---------------------------------------------------------------------------


def begin(job: AgencyJob, agent: str, *, stage: str = "", effort: str = "") -> AgentRun:
    return AgentRun.objects.create(
        job=job,
        workspace_id=job.workspace_id,
        revision=job.revision,
        agent=agent,
        stage=stage or job.stage,
        effort=effort,
        model=llm.model_id() if _is_model_agent(agent) else "",
    )


def end(
    run: AgentRun,
    *,
    summary: str,
    output: dict[str, Any] | None = None,
    result: llm.AgentResult | None = None,
    status: str = AgentRun.Status.SUCCEEDED,
) -> None:
    run.status = status
    run.summary = summary[:500]
    run.output = output or {}
    run.finished_at = timezone.now()
    run.duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)
    fields = ["status", "summary", "output", "finished_at", "duration_ms"]
    if result is not None:
        run.model = result.model
        run.input_tokens = result.input_tokens
        run.output_tokens = result.output_tokens
        run.cache_read_tokens = result.cache_read_tokens
        run.fallback_used = result.fallback_used
        fields += ["model", "input_tokens", "output_tokens", "cache_read_tokens", "fallback_used"]
    run.save(update_fields=fields)


def fail_run(run: AgentRun, error: str | Exception) -> None:
    """Close ``run`` as failed, recording what a failed Claude call still cost."""
    run.status = AgentRun.Status.FAILED
    run.error = str(error)[:2000]
    run.finished_at = timezone.now()
    run.duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)
    fields = ["status", "error", "finished_at", "duration_ms"]
    usage = getattr(error, "usage", None)
    if usage:
        run.model, run.input_tokens, run.output_tokens, run.cache_read_tokens = usage
        fields += ["model", "input_tokens", "output_tokens", "cache_read_tokens"]
    run.save(update_fields=fields)


def call(
    job: AgencyJob, agent: str, fn: Callable[[], llm.AgentResult], *, stage: str = "", effort: str = ""
) -> tuple[AgentRun, llm.AgentResult]:
    """Run one Claude agent turn for ``job`` with its own timeline row: ``(run, result)``.

    The row is failed (and the error re-raised) when the turn fails; the caller
    closes it with :func:`end` once it has used the answer.
    """
    run = begin(job, agent, stage=stage, effort=effort)
    try:
        result = fn()
    except JobError as exc:
        fail_run(run, exc)
        raise
    return run, result


def _is_model_agent(agent: str) -> bool:
    from . import team

    return team.get(agent).is_model


# ---------------------------------------------------------------------------
# Sweeping jobs whose worker died
# ---------------------------------------------------------------------------


def _has_pending_task(task_name: str, object_id: str) -> bool:
    """True when the background queue still holds a task for ``object_id`` (it is only waiting)."""
    from background_task.models import Task

    return Task.objects.filter(task_name=task_name, task_params__contains=object_id, failed_at__isnull=True).exists()


def sweep_stuck() -> int:
    """Fail jobs whose worker died between or during stages, so they can be retried."""
    now = timezone.now()
    failed = 0
    for job in AgencyJob.objects.filter(status__in=AgencyJob.ACTIVE_STATUSES).only(
        "pk", "kind", "status", "revision", "updated_at", "workspace_id", "conversation_id"
    ):
        try:
            limit = job_type(job.kind).stuck_after
        except KeyError:
            limit = timedelta(minutes=30)
        if job.updated_at >= now - limit:
            continue
        if job.status == AgencyJob.Status.QUEUED and _has_pending_task(
            "apps.studio.tasks.run_agency_step", str(job.pk)
        ):
            continue
        fail(
            job,
            "The team stopped part-way — the background worker restarted or isn't running. "
            "Press Retry to continue from where it stopped.",
        )
        failed += 1
    return failed
