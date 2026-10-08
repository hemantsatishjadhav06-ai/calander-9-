"""Background tasks for the AI Studio.

``run_studio_step`` is one stage of one brief — one agent's turn — queued by
``apps.studio.pipeline`` at a lower priority than publishing, so the single
worker always publishes due posts before it starts the next agent. It never
raises: every outcome is recorded on the brief, so django-background-tasks
never retries a step (and re-bills an agent call) behind our back.

``sweep_stuck_briefs`` is recurring (registered in ``apps.studio.apps``) and
fails a brief whose worker died mid-way, so the person can press Retry.
"""

import logging

from background_task import background

from apps.common.background import keep_schedule

logger = logging.getLogger(__name__)

STUCK_SWEEP_INTERVAL_SECONDS = 600


@background(schedule=0)
def run_studio_step(brief_id, revision, stage):
    from .pipeline import run_step

    try:
        run_step(brief_id, revision, stage)
    except Exception:
        logger.exception("Studio step %s crashed for brief %s", stage, brief_id)


@background(schedule=0)
@keep_schedule
def sweep_stuck_briefs():
    from .pipeline import sweep_stuck

    failed = sweep_stuck()
    if failed:
        logger.warning("Marked %d AI Studio brief(s) as stuck", failed)
