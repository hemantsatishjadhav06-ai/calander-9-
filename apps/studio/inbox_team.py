"""Reply drafts for new comments, messages and reviews: which messages, and when.

The agency's community manager and reviews manager (``apps.studio.jobtypes.inbox``)
draft replies a person sends from the inbox; nothing here sends anything. This
module picks the messages and queues the ``inbox`` job:

* :func:`draft_due` — the heartbeat (``autopilot.run_cycle``), for workspaces
  that switched inbox drafts on in their agency settings;
* :func:`candidates` + :func:`queue` — also behind the inbox's "Draft replies
  with the team" button.

A message is picked once: unread, no reply yet (a person's or the team's), not
already in a recent inbox job (so a message the agents chose to skip, like
spam, isn't sent to them again every cycle), and — for direct messages — less
than a day old, because most networks only let a business answer a direct
message within 24 hours. At most :data:`MAX_PER_JOB` messages go in one job
and a workspace has one inbox job at a time.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from .models import AgencyJob

logger = logging.getLogger(__name__)

MAX_PER_JOB = 20
#: Messages older than this aren't drafted automatically.
LOOKBACK = timedelta(days=7)
#: Most networks close the window for a business's reply to a direct message after a day.
DM_WINDOW = timedelta(hours=24)


def _kinds():
    from apps.inbox.models import InboxMessage

    kinds = InboxMessage.MessageType
    return (kinds.COMMENT, kinds.MENTION, kinds.DM, kinds.REVIEW)


def _recently_queued_ids(workspace) -> set[str]:
    since = timezone.now() - LOOKBACK
    ids: set[str] = set()
    for data in AgencyJob.objects.filter(
        workspace=workspace, kind=AgencyJob.Kind.INBOX, created_at__gte=since
    ).values_list("input", flat=True):
        ids.update(str(i) for i in (data or {}).get("message_ids", []) or [])
    return ids


def candidates(workspace, *, ids=None, manual: bool = False, limit: int = MAX_PER_JOB) -> list:
    """Messages of ``workspace`` the team should draft a reply for, newest first.

    ``ids`` narrows to the messages a person picked (only those of this
    workspace count). ``manual`` is a person asking: a message a past job
    skipped may then be tried again, and the age limit is the DM window only.
    """
    from apps.inbox.models import InboxMessage

    now = timezone.now()
    kinds = InboxMessage.MessageType
    rows = (
        InboxMessage.objects.filter(workspace=workspace, message_type__in=_kinds())
        .exclude(status__in=(InboxMessage.Status.RESOLVED, InboxMessage.Status.ARCHIVED))
        .filter(replies__isnull=True)
        .exclude(Q(message_type=kinds.DM) & Q(received_at__lt=now - DM_WINDOW))
        .exclude(body="")
        .select_related("social_account")
    )
    if ids is not None:
        clean = []
        for value in ids:
            try:
                clean.append(uuid.UUID(str(value)))
            except ValueError:
                continue
        rows = rows.filter(pk__in=clean)
    else:
        rows = rows.filter(received_at__gte=now - LOOKBACK)
        if not manual:
            rows = rows.filter(status=InboxMessage.Status.UNREAD)
    picked = []
    skip = set() if manual else _recently_queued_ids(workspace)
    for message in rows.order_by("-received_at").distinct()[: limit * 3]:
        if str(message.pk) in skip:
            continue
        handle = (message.social_account.account_handle or "").lstrip("@").lower()
        if handle and (message.sender_handle or "").lstrip("@").lower() == handle:
            continue  # the brand's own reply, synced back
        picked.append(message)
        if len(picked) >= limit:
            break
    return picked


def active_job(workspace) -> AgencyJob | None:
    return (
        AgencyJob.objects.filter(workspace=workspace, kind=AgencyJob.Kind.INBOX, status__in=AgencyJob.ACTIVE_STATUSES)
        .order_by("-created_at")
        .first()
    )


def queue(workspace, messages, *, requested_by=None, source: str = "auto") -> AgencyJob | None:
    """Queue an ``inbox`` job for ``messages``; None when one is already running here."""
    from . import engine

    if not messages or active_job(workspace) is not None:
        return None
    count = len(messages)
    return engine.create(
        workspace,
        AgencyJob.Kind.INBOX,
        title=f"Draft replies to {count} message{'' if count == 1 else 's'}",
        input={"message_ids": [str(m.pk) for m in messages], "source": source},
        requested_by=requested_by,
    )


def _due_workspaces():
    from .models import AgencySettings

    return (
        AgencySettings.objects.filter(
            inbox_drafts_enabled=True,
            workspace__is_archived=False,
            workspace__organization__deletion_requested_at__isnull=True,
        )
        .select_related("workspace")
        .order_by("workspace_id")
    )


def draft_due() -> int:
    """Queue reply drafts where inbox drafts are on and something new came in. Returns jobs queued."""
    from . import budget

    queued = 0
    for row in _due_workspaces():
        workspace = row.workspace
        try:
            if active_job(workspace) is not None or not budget.can_spend(workspace):
                continue
            messages = candidates(workspace)
            if messages and queue(workspace, messages) is not None:
                queued += 1
        except Exception:
            logger.exception("Inbox drafts: could not queue for workspace %s", workspace.pk)
    return queued
