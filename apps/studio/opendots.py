"""OpenDots task controls adapted to SM Bean's canonical, tenant-scoped jobs.

Derived from CopilotKit/OpenDots ``Store.action/invalidate`` and
``TaskActions`` at 625452e06cde74cb25b0ce319e2c1be0488f5a5f, MIT licensed.
Copyright (c) Atai Barkai. See third_party/opendots/LICENSE and provenance.

No second scheduler, conversation store, publisher or external service is
introduced. A paused task is a cancelled canonical job with a reserved
control marker; revision fencing prevents a queued or late stage from
continuing. Stopping future work cannot retract a request already sent to a
provider. Resuming such work requires a fresh, explicit review of its effects.
"""

from __future__ import annotations

import hashlib
import json
import logging
from functools import partial
from typing import Any

from django.core import signing
from django.core.exceptions import PermissionDenied
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone

from apps.telegram.permissions import current_member, internal_member

from . import budget, chat, engine, llm
from .models import AgencyJob

UPSTREAM_COMMIT = "625452e06cde74cb25b0ce319e2c1be0488f5a5f"
CONTROL_KEY = "_opendots_control"
REVIEW_SALT = "studio.opendots.completed-effects.v1"
REVIEW_MAX_AGE = 30 * 60
logger = logging.getLogger(__name__)


def _notify_control(job_id, revision, action):
    """Notification failures do not undo a successfully committed control."""
    try:
        from apps.telegram.workflow_bridge import job_control_event

        job_control_event(job_id, revision, action)
    except Exception:
        logger.warning("The task control update could not be queued for Telegram.")


class CoworkerControlError(ValueError):
    """The control cannot be applied to the exact task the person reviewed."""


def integration_status() -> dict[str, Any]:
    """Report the code actually running; never imply a configured SDK service."""
    return {
        "mode": "native_adaptation",
        "upstream": "CopilotKit/OpenDots",
        "commit": UPSTREAM_COMMIT,
        "license": "MIT",
        "task_controls": True,
        "storage": "canonical_agency_jobs",
        "scheduler": "leased_smbean_worker",
        "copilotkit_runtime": False,
        "copilotkit_intelligence": False,
        "computer_tools": False,
    }


def _control(job: AgencyJob) -> dict:
    state = job.state if isinstance(job.state, dict) else {}
    marker = state.get(CONTROL_KEY)
    return marker if isinstance(marker, dict) else {}


def _status(job: AgencyJob) -> str:
    """Port OpenDots' task states without adding competing persistence."""
    if job.status == AgencyJob.Status.CANCELLED and _control(job).get("paused") is True:
        return "paused"
    if job.status == AgencyJob.Status.FAILED and "background worker restarted" in job.error:
        return "interrupted"
    states: dict[str, str] = {
        AgencyJob.Status.QUEUED: "queued",
        AgencyJob.Status.WORKING: "running",
        AgencyJob.Status.DONE: "completed",
        AgencyJob.Status.FAILED: "failed",
        AgencyJob.Status.CANCELLED: "cancelled",
    }
    return states.get(job.status, "failed")


def _needs_review(job: AgencyJob) -> bool:
    return job.status == AgencyJob.Status.FAILED or (
        _status(job) == "paused" and _control(job).get("review_required") is True
    )


def _effect_digest(job: AgencyJob) -> str:
    """Bind the review to saved work, including late provider receipts.

    Only a digest is put in the signed receipt. Prompts, captions, provider
    results, people and credentials never become projection fields.
    """
    payload = {
        "job": str(job.pk),
        "workspace": str(job.workspace_id),
        "revision": job.revision,
        "status": job.status,
        "stage": job.stage,
        "state": job.state,
        "result": job.result,
        "error": job.error,
        "runs": list(
            job.runs.order_by("pk").values(
                "id", "revision", "status", "output", "summary", "error", "finished_at", "input_tokens", "output_tokens"
            )
        ),
        "briefs": list(
            job.briefs.order_by("pk").values(
                "id",
                "status",
                "revision",
                "post_id",
                "updated_at",
                "post_copy",
                "graphic_id",
                "post__caption",
                "post__updated_at",
            )
        ),
    }
    encoded = json.dumps(payload, cls=DjangoJSONEncoder, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _review_payload(job: AgencyJob) -> dict:
    return {"job": str(job.pk), "workspace": str(job.workspace_id), "effects": _effect_digest(job)}


def _waiting_on_policy(job: AgencyJob) -> bool:
    """A queued job the worker keeps skipping because autopilot (or the workspace) is paused."""
    from .autopilot import PAUSE_REASONS

    return job.status == AgencyJob.Status.QUEUED and job.error in PAUSE_REASONS


def task_record(job: AgencyJob) -> dict[str, Any]:
    """Read-only status/control projection for an already-authorized job.

    Callers must scope with chat.web_jobs and their authenticated workspace;
    the mutation service independently repeats that check under row locks.
    ``waiting_policy`` is a display state only: the control rules are those
    of the underlying queued job, so it can still be paused or stopped.
    """
    status = _status(job)
    active = status in ("queued", "running")  # OpenDots TaskActions.active
    needs_review = _needs_review(job)
    labels = {
        "queued": "Waiting to start",
        "waiting_policy": "Paused: autopilot is off",
        "running": "Your team is working",
        "paused": "Paused by you",
        "completed": "Finished",
        "failed": "Needs your attention",
        "interrupted": "Interrupted — review before retrying",
        "cancelled": "Stopped",
    }
    shown = "waiting_policy" if status == "queued" and _waiting_on_policy(job) else status
    policy_url = ""
    if shown == "waiting_policy":
        from django.urls import NoReverseMatch, reverse

        try:
            policy_url = reverse("studio:autopilot", kwargs={"workspace_id": job.workspace_id})
        except NoReverseMatch:
            policy_url = ""
    return {
        "id": str(job.pk),
        "status": shown,
        "label": labels[shown],
        "policy_url": policy_url,
        "revision": job.revision,
        "stage": job.stage,
        "needs_effect_review": needs_review,
        "review_receipt": signing.dumps(_review_payload(job), salt=REVIEW_SALT) if needs_review else "",
        "can_pause": active,
        "can_resume": status == "paused",
        "can_retry": status in ("failed", "interrupted"),
        "can_cancel": active or status == "paused",
    }


def _require_review(job: AgencyJob, receipt: str, reviewed: bool) -> None:
    if not _needs_review(job):
        return
    if reviewed is not True:
        raise CoworkerControlError("Review the saved work and confirm before continuing this task.")
    try:
        reviewed_payload = signing.loads(receipt, salt=REVIEW_SALT, max_age=REVIEW_MAX_AGE)
    except (signing.BadSignature, TypeError, ValueError):
        raise CoworkerControlError("Your review expired. Reload and review the saved work again.") from None
    if reviewed_payload != _review_payload(job):
        raise CoworkerControlError("The saved work changed after your review. Reload and review it again.")


def control_job(
    workspace,
    user,
    job_id,
    action: str,
    *,
    expected_revision: int,
    review_receipt: str = "",
    reviewed: bool = False,
) -> AgencyJob:
    """Apply a scoped OpenDots control once, preserving existing worker fences.

    Only explicit resume/retry can queue a stopped task. The expected
    revision fences duplicate form submissions and stale browser tabs.
    Existing model budget, live workspace policy, private Telegram history
    and current membership rules apply before a stage is enqueued.
    """
    if action not in {"pause", "resume", "retry", "cancel"}:
        raise CoworkerControlError("Choose Pause, Resume, Retry after review, or Stop.")
    if type(expected_revision) is not int or expected_revision < 1:
        raise CoworkerControlError("Reload this task before changing it.")
    with transaction.atomic():
        member = current_member(workspace, user, locked=True)
        if not internal_member(member) or member.effective_permissions.get("create_posts") is not True:
            raise PermissionDenied("Your current workspace role cannot control the team's tasks.")
        job = (
            chat.web_jobs(AgencyJob.objects.select_for_update(of=("self",)))
            .filter(pk=job_id, workspace_id=member.workspace_id)
            .first()
        )
        if job is None:
            raise PermissionDenied("This task is unavailable in your workspace.")
        job.workspace = member.workspace
        if job.revision != expected_revision:
            raise CoworkerControlError("This task changed in another tab. Reload before continuing.")
        record = task_record(job)
        capability = {"pause": "can_pause", "resume": "can_resume", "retry": "can_retry", "cancel": "can_cancel"}
        if not record[capability[action]]:
            raise CoworkerControlError("This task has already moved on. Reload to see its current progress.")
        if action in {"resume", "retry"}:
            _require_review(job, review_receipt, reviewed)
            from .autopilot import automatic_work_blocker

            blocker = automatic_work_blocker(job.workspace, job=job)
            if blocker:
                raise CoworkerControlError(blocker)
            setup_error = llm.configuration_error()
            if setup_error:
                raise CoworkerControlError(setup_error)
            if not budget.can_spend(job.workspace):
                raise CoworkerControlError(budget.over_budget_message(job.workspace))
            try:
                resumable = engine.job_type(job.kind).stage(job.stage) is not None
            except KeyError:
                resumable = False
            if not resumable:
                raise CoworkerControlError(
                    "This task's unfinished step changed. Ask your agency to review it before retrying."
                )
            state = dict(job.state or {})
            state.pop(CONTROL_KEY, None)
            job.state = state
            job.save(update_fields=["state", "updated_at"])
            engine.restart(job)  # increments revision; queues once after commit
        else:
            old_status = job.status
            prior_review = _control(job).get("review_required") is True
            engine.cancel(job)  # closes current timeline entries; late results remain fenced
            state = dict(job.state or {})
            state[CONTROL_KEY] = {
                "paused": action == "pause",
                "review_required": prior_review or old_status == AgencyJob.Status.WORKING,
                "stopped_at": timezone.now().isoformat(),
            }
            job.state = state
            job.revision += 1
            job.status = AgencyJob.Status.CANCELLED
            job.finished_at = timezone.now()
            job.save(update_fields=["state", "revision", "status", "finished_at", "updated_at"])
        transaction.on_commit(partial(_notify_control, job.pk, job.revision, action))
        return job
