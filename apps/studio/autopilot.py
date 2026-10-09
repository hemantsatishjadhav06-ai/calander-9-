"""The agency's heartbeat (``tasks.run_agency_cycle``, every 15 minutes).

Each part only reads the database and queues one-shot tasks, so the whole
cycle stays quick at the recurring tasks' priority; an error in one part is
logged and never stops the others:

1. ``plan_due_workspaces`` — autopilot plans next week where it is due;
2. ``feed_planned_briefs`` — planned briefs are handed to the team a few at a time;
3. ``refresh_memory_due`` — creative memory is refreshed after new analytics;
4. ``draft_inbox_replies_due`` — new comments and reviews get reply drafts.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def plan_due_workspaces() -> int:
    """Not built yet."""
    return 0


def feed_planned_briefs() -> int:
    """Not built yet."""
    return 0


def refresh_memory_due() -> int:
    """Not built yet."""
    return 0


def draft_inbox_replies_due() -> int:
    from . import inbox_team

    return inbox_team.draft_due()


PARTS = ("plan_due_workspaces", "feed_planned_briefs", "refresh_memory_due", "draft_inbox_replies_due")


def run_cycle() -> dict[str, int]:
    done: dict[str, int] = {}
    for name in PARTS:
        try:
            done[name] = int(globals()[name]() or 0)
        except Exception:
            logger.exception("Agency cycle: %s failed", name)
            done[name] = -1
    return done
