"""Tell the lead and backup when the team's unprompted work fails.

A failed chat reply already tells the people in its thread (``chat.post_failure_note``).
Every other kind of job, and a week the planner could not finish, used to fail
silently in a list nobody opened. These alerts go in-app and by email to the
lead and backup (``EventType.AGENCY_ALERT``) and to their paired Telegram
chats through the manager inbox. Nothing here retries, approves or publishes;
every link lands on the page where a person decides.
"""

from __future__ import annotations

import hashlib
import logging

from django.urls import reverse

from . import chat
from .models import AgencyJob, AgencySettings, AutopilotWeek

logger = logging.getLogger(__name__)


def recipients(workspace) -> list:
    """The lead and backup when they are current internal approvers, else every internal approver."""
    from apps.approvals.actor import is_internal_approver

    from .autopilot import _approvers

    row = AgencySettings.objects.filter(workspace=workspace).select_related("lead", "backup").first()
    people = []
    for person in (row.lead, row.backup) if row else ():
        if person is not None and person not in people and is_internal_approver(person, workspace):
            people.append(person)
    return people or _approvers(workspace)


def _told(key: str) -> bool:
    from apps.notifications.models import EventType, Notification

    return Notification.objects.filter(event_type=EventType.AGENCY_ALERT, data__alert_key=key).exists()


def _send(workspace, people, *, key, title, body, path, telegram_text, only_user=None) -> int:
    from apps.notifications.engine import notify
    from apps.notifications.models import EventType
    from apps.telegram import inbox
    from apps.telegram.outbox import link_button, link_keyboard

    url = chat.absolute_url(path) if path else ""
    told = 0
    for person in people:
        try:
            notify(
                user=person,
                event_type=EventType.AGENCY_ALERT,
                title=title[:255],
                body=body,
                data={"workspace_id": str(workspace.pk), "alert_key": key, "action_url": url},
            )
            told += 1
        except Exception:
            logger.exception("Agency alert could not be recorded for user %s", person.pk)
    try:
        inbox.tell(
            workspace,
            telegram_text,
            source_key=f"alert:{key}",
            event="agency_alert",
            reply_markup=link_keyboard(link_button("Open it", path)) if path else None,
            only_user_id=only_user.pk if only_user is not None else None,
        )
    except Exception:
        logger.exception("Agency alert could not be queued to Telegram for workspace %s", workspace.pk)
    return told


def job_failed(job: AgencyJob) -> int:
    """Alert once per failed job revision. Chat replies are handled in their thread. Never raises."""
    try:
        if job.kind == AgencyJob.Kind.CHAT:
            return 0
        # The engine marks the row with a queryset update; read the saved error and status back.
        job = (
            AgencyJob.objects.select_related("workspace", "conversation", "requested_by").filter(pk=job.pk).first()
            or job
        )
        if job.status != AgencyJob.Status.FAILED:
            return 0
        key = f"job:{job.pk}:{job.revision}"
        if _told(key):
            return 0
        workspace = job.workspace
        private = job.conversation_id is not None and chat.is_private_conversation(job.conversation)
        # Work that started in someone's private Telegram chat stays theirs:
        # only that person hears about it, and only in that chat.
        people = [job.requested_by] if private and job.requested_by is not None else recipients(workspace)
        if private and not people:
            return 0
        label = job.title or job.get_kind_display()
        reason = (job.error or "").strip()
        path = "" if private else reverse("studio:job", kwargs={"workspace_id": workspace.pk, "job_id": job.pk})
        return _send(
            workspace,
            people,
            key=key,
            title=f"The team needs you: {label}"[:255],
            body=(f"{job.get_kind_display()} stopped. {reason} " if reason else f"{job.get_kind_display()} stopped. ")
            + "Open it to see what happened and retry.",
            path=path,
            telegram_text=f"The team stopped on “{label[:120]}”. Open it to see why and retry.",
            only_user=job.requested_by if private else None,
        )
    except Exception:
        logger.exception("Agency alert for job %s could not be sent", job.pk)
        return 0


def week_failed(week: AutopilotWeek) -> int:
    """Alert once per failed week and reason; a retry that fails the same way stays quiet. Never raises."""
    try:
        current = AutopilotWeek.objects.select_related("workspace").filter(pk=week.pk).first()
        if current is None or current.status != AutopilotWeek.Status.FAILED:
            return 0
        note = (current.note or "The plan failed.").strip()
        key = f"week:{current.pk}:{hashlib.sha256(note.encode()).hexdigest()[:12]}"
        if _told(key):
            return 0
        workspace = current.workspace
        when = current.week_start.strftime("%d %b")
        return _send(
            workspace,
            recipients(workspace),
            key=key,
            title=f"The team needs you: the week of {when}",
            body=f"{note} Open Autopilot to retry or plan it by hand.",
            path=reverse("studio:autopilot", kwargs={"workspace_id": workspace.pk}),
            telegram_text=f"The plan for the week of {when} stopped: {note[:200]}",
        )
    except Exception:
        logger.exception("Agency alert for week %s could not be sent", week.pk)
        return 0
