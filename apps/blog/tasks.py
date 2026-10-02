"""Background tasks for publishing blog posts.

``publish_blog_post`` and ``poll_blog_deploy`` are one-shot tasks queued by
``services.start_publish`` and by each other. They run as the system actor:
they may write to GitHub only because ``start_publish``'s claim proved the
post is an approved, matching revision, and the publisher re-checks that
before its first write. Neither raises — every outcome is recorded on the post
— so django-background-tasks never retries them behind our back.

``sweep_stuck_blog_publishes`` is recurring (registered in ``apps.blog.apps``)
and settles a post left in ``publishing`` when the worker died mid-way.
"""

import logging

from background_task import background

from apps.common.background import keep_schedule

logger = logging.getLogger(__name__)

STUCK_SWEEP_INTERVAL_SECONDS = 600


@background(schedule=0)
def publish_blog_post(post_id, attempt):
    from .publisher import run_publish

    try:
        run_publish(post_id, attempt)
    except Exception:
        # run_publish records its own failures; this is the last line so a bug
        # cannot turn into silent retries that re-dispatch the deploy.
        logger.exception("Blog publish task crashed for %s", post_id)


@background(schedule=0)
def poll_blog_deploy(post_id, attempt, verify_tries=0):
    from .publisher import run_poll

    try:
        run_poll(post_id, attempt, verify_tries)
    except Exception:
        logger.exception("Blog deploy poll crashed for %s", post_id)


@background(schedule=0)
@keep_schedule
def sweep_stuck_blog_publishes():
    from .publisher import sweep_stuck

    settled = sweep_stuck()
    if settled:
        logger.warning("Settled %d blog post(s) stuck in publishing", settled)
