"""Background tasks for publishing blog posts.

``publish_blog_post`` and ``poll_blog_deploy`` are one-shot tasks queued by
``services.start_publish`` and by each other. They run as the system actor:
they may write to GitHub only because ``start_publish``'s claim proved the
post is an approved, matching revision, and the publisher re-checks that
before its first write. Neither raises — every outcome is recorded on the post
— so django-background-tasks never retries them behind our back.

``sweep_stuck_blog_publishes`` is recurring (registered in ``apps.blog.apps``)
and settles a post left in ``publishing`` when the worker died mid-way.

SEO (all below publishing's priority, and none ever raises):

* ``queue_search_console_syncs`` (recurring) queues one
  ``sync_search_console_site`` per connected website whose numbers are a day
  old — the network calls run in that one-shot task, not in the tick;
* ``queue_seo_checkups`` (recurring) starts the agency's SEO monitor (an
  ``AgencyJob`` of kind ``seo``) once a week for every workspace with live
  articles;
* ``ping_indexnow_task`` tells IndexNow about a post once it is verified live.
"""

import datetime as dt
import logging

from background_task import background

from apps.common.background import keep_schedule

logger = logging.getLogger(__name__)

STUCK_SWEEP_INTERVAL_SECONDS = 600
#: How often the SEO ticks look for due work (each syncs a site at most daily).
SEARCH_CONSOLE_TICK_SECONDS = 6 * 3600
SEO_CHECKUP_TICK_SECONDS = 6 * 3600
#: A workspace gets an automatic SEO check-up this often.
SEO_CHECKUP_EVERY = dt.timedelta(days=7)
#: Background work: below publishing (0), post briefs (-10) and agency jobs (-15).
PRIORITY_SEO = -30


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


# ---------------------------------------------------------------------------
# SEO
# ---------------------------------------------------------------------------


@background(schedule=0)
def sync_search_console_site(connection_id):
    """Copy one website's latest Google Search numbers. Records failures on the connection."""
    from .search_console import run_sync

    try:
        run_sync(connection_id)
    except Exception:
        logger.exception("Search Console sync task crashed for %s", connection_id)


@background(schedule=0)
@keep_schedule
def queue_search_console_syncs():
    """The daily sync: queue each connected website whose last sync is a day old."""
    from .search_console import due_connections

    due = due_connections()
    for connection in due:
        sync_search_console_site(str(connection.pk), priority=PRIORITY_SEO)
    if due:
        logger.info("Queued %d Search Console sync(s)", len(due))


def due_checkup_workspaces(now=None):
    """Workspaces with live articles and no SEO check-up in the last week (still in use, not being deleted)."""
    from django.utils import timezone

    from apps.studio.models import AgencyJob
    from apps.workspaces.models import Workspace

    from .models import BlogPost

    now = now or timezone.now()
    with_articles = BlogPost.objects.filter(status=BlogPost.Status.PUBLISHED).values("workspace_id")
    recent = AgencyJob.objects.filter(kind=AgencyJob.Kind.SEO, created_at__gte=now - SEO_CHECKUP_EVERY).values(
        "workspace_id"
    )
    return Workspace.objects.filter(
        pk__in=with_articles,
        is_archived=False,
        organization__deletion_requested_at__isnull=True,
    ).exclude(pk__in=recent)


@background(schedule=0)
@keep_schedule
def queue_seo_checkups():
    """The weekly SEO check-up: the SEO monitor scores live articles and reads their rankings."""
    from apps.studio import engine
    from apps.studio.models import AgencyJob

    started = 0
    for workspace in due_checkup_workspaces():
        engine.create(workspace, AgencyJob.Kind.SEO, title="Weekly SEO check-up")
        started += 1
    if started:
        logger.info("Started %d weekly SEO check-up(s)", started)


@background(schedule=0)
def ping_indexnow_task(post_id):
    from .publisher import ping_indexnow

    try:
        ping_indexnow(post_id)
    except Exception:
        logger.exception("IndexNow ping crashed for %s", post_id)
