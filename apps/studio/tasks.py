"""Background tasks for the agency.

``run_studio_step`` is one stage of one post brief and ``run_agency_step`` one
stage of one agency job (a plan, an article, a reply in the thread...): one
agent's turn each, queued at a lower priority than publishing, so the single
worker always publishes due posts before it starts the next agent. Neither
ever raises: every outcome is recorded on the brief or job, so
django-background-tasks never retries a step (and re-bills an agent call)
behind our back.

The recurring ones (registered in ``apps.studio.apps``):

* ``sweep_stuck_briefs`` fails briefs and jobs whose worker died mid-way, so a
  person can press Retry;
* ``run_agency_cycle`` is the hourly heartbeat: it plans the week for
  workspaces whose autopilot is due, feeds planned briefs to the team a few at
  a time, refreshes creative memory and drafts inbox replies where those are on.
"""

import logging

from background_task import background

from apps.common.background import keep_schedule

logger = logging.getLogger(__name__)

STUCK_SWEEP_INTERVAL_SECONDS = 600
AGENCY_CYCLE_INTERVAL_SECONDS = 900


@background(schedule=0)
def run_studio_step(brief_id, revision, stage):
    from .pipeline import run_step

    try:
        run_step(brief_id, revision, stage)
    except Exception:
        logger.exception("Studio step %s crashed for brief %s", stage, brief_id)


@background(schedule=0)
def run_agency_step(job_id, revision, stage):
    from .engine import run_step

    try:
        run_step(job_id, revision, stage)
    except Exception:
        logger.exception("Agency stage %s crashed for job %s", stage, job_id)


@background(schedule=0)
@keep_schedule
def sweep_stuck_briefs():
    from . import engine, pipeline

    failed = pipeline.sweep_stuck() + engine.sweep_stuck()
    if failed:
        logger.warning("Marked %d AI Studio brief(s) or job(s) as stuck", failed)


@background(schedule=0)
@keep_schedule
def run_agency_cycle():
    from .autopilot import run_cycle

    run_cycle()
