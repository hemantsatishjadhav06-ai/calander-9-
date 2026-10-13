"""The SEO monitor (agency job kind "seo"): the weekly check-up, its suggestions, and that it only reads."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from background_task.models import Task
from django.utils import timezone

from apps.blog import seo
from apps.blog.models import BlogPost, SearchConsoleConnection, SearchPerformance
from apps.blog.tests.conftest import approved_post, make_post
from apps.studio import budget, engine, guards
from apps.studio.models import AgencyJob, AgencySettings, AgentRun

Status = BlogPost.Status


@pytest.fixture
def queue(monkeypatch):
    queued = []
    monkeypatch.setattr(engine, "enqueue", lambda job, stage: queued.append((job.pk, job.revision, stage)))
    return queued


def _drive(job, limit=5):
    for _ in range(limit):
        job.refresh_from_db()
        if not job.is_active:
            return job
        engine.run_step(str(job.pk), job.revision, job.stage)
    raise AssertionError("the job did not finish")


def _live(world, **overrides):
    post = approved_post(world, **overrides)
    BlogPost.objects.filter(pk=post.pk).update(
        status=Status.PUBLISHED, published_url=post.expected_url, published_at=timezone.now()
    )
    return BlogPost.objects.get(pk=post.pk)


def test_the_check_up_scores_live_articles_and_reads_their_rankings(world, queue):
    strong = _live(
        world,
        slug="land-title-verification",
        title="Land title verification",
        focus_keyword="land title verification",
        meta_description="x" * 130,
    )
    weak = _live(world, slug="thin", title="Thin", body="Short.")
    draft = make_post(world, slug="draft-only")  # not live: not checked
    SearchConsoleConnection.objects.create(
        site=world.neopolis, property_url="sc-domain:neopolisinfra.com", refresh_token="t"
    )
    today = timezone.localdate()
    page = strong.expected_url
    SearchPerformance.objects.create(
        site=world.neopolis,
        date=today - dt.timedelta(days=3),
        page=page,
        query="encumbrance certificate",
        clicks=0,
        impressions=80,
        ctr=0,
        position=14.2,
    )
    SearchPerformance.objects.create(
        site=world.neopolis,
        date=today - dt.timedelta(days=40),
        page=page,
        query="encumbrance certificate",
        clicks=1,
        impressions=80,
        ctr=0.0125,
        position=9.0,
    )

    job = engine.create(world.workspace, AgencyJob.Kind.SEO, title="SEO check-up", requested_by=world.owner)
    assert queue == [(job.pk, 1, "check")]
    job = _drive(job)

    assert job.status == AgencyJob.Status.DONE
    pages = {p["post_id"]: p for p in job.result["pages"]}
    assert set(pages) == {str(strong.pk), str(weak.pk)} and str(draft.pk) not in pages
    checked = pages[str(strong.pk)]
    assert checked["position"] == 14.2 and checked["position_change"] == pytest.approx(-5.2)
    assert checked["clicks"] == 0
    assert checked["suggestion"].startswith("Stuck on page 2 for “encumbrance certificate”")
    assert job.result["pages"][0]["post_id"] == str(strong.pk)  # slipping first
    assert (
        pages[str(weak.pk)]["suggestion"]
        == "No Google impressions yet — link to it from two of your other articles so Google finds it."
    )
    assert "Checked 2 published articles" in job.result["summary"]
    run = AgentRun.objects.get(job=job)
    assert run.agent == "seo_monitor" and run.status == AgentRun.Status.SUCCEEDED
    assert run.model == "" and run.input_tokens == 0 and run.workspace_id == world.workspace.id


def test_without_search_console_the_score_speaks(world, queue):
    weak = _live(world, slug="thin", title="Thin", body="Short.")
    job = _drive(engine.create(world.workspace, AgencyJob.Kind.SEO))
    page = job.result["pages"][0]
    report = seo.score_post(weak)
    assert page["position"] is None and page["clicks"] is None
    assert page["suggestion"].startswith(f"Score {report.score} — fix:")


def test_the_check_up_changes_nothing_and_runs_as_agent_work(world, queue, monkeypatch):
    live = _live(world, slug="live")
    approved = approved_post(world, slug="approved")
    pending = make_post(world, slug="pending")
    from apps.blog import services

    services.submit_for_review(pending, world.editor)
    snapshot = {p.pk: (p.status, p.revision, p.approved_fingerprint) for p in BlogPost.objects.all()}
    labels = []
    real = seo.suggestion

    def spy(report, perf):
        labels.append(guards.in_agent_work())
        return real(report, perf)

    monkeypatch.setattr(seo, "suggestion", spy)
    _drive(engine.create(world.workspace, AgencyJob.Kind.SEO))

    assert {p.pk: (p.status, p.revision, p.approved_fingerprint) for p in BlogPost.objects.all()} == snapshot
    assert labels and all(label and "seo job" in label for label in labels)
    assert {live.pk, approved.pk, pending.pk} <= set(snapshot)
    assert not Task.objects.filter(task_name="apps.blog.tasks.publish_blog_post").exists()


def test_the_check_up_costs_nothing_so_it_runs_over_budget(client, world, queue):
    AgencySettings.objects.create(workspace=world.workspace, monthly_budget_usd=Decimal("0"))
    assert not budget.can_spend(world.workspace)
    _live(world)
    client.force_login(world.editor)
    client.post(f"/workspace/{world.workspace.id}/blog/seo-checkup/")
    job = _drive(AgencyJob.objects.get(kind="seo"))
    assert job.status == AgencyJob.Status.DONE
    assert budget.month_spend(world.workspace) == Decimal("0")


def test_a_crash_is_a_failed_job_not_an_exception(world, queue, monkeypatch):
    from apps.studio.jobtypes import seo as seo_job

    def boom(workspace, **kwargs):
        raise RuntimeError("bug")

    monkeypatch.setattr(seo_job, "check_workspace", boom)
    job = _drive(engine.create(world.workspace, AgencyJob.Kind.SEO))
    assert job.status == AgencyJob.Status.FAILED and "seo monitor" in job.error.lower()


def test_the_job_type_is_background_work_for_the_seo_monitor():
    from apps.studio.jobs import JOB_TYPES

    job_type = JOB_TYPES["seo"]
    assert job_type.priority == engine.PRIORITY_BACKGROUND
    assert [(s.name, s.agent) for s in job_type.stages] == [("check", "seo_monitor")]


# ---------------------------------------------------------------------------
# The weekly hook
# ---------------------------------------------------------------------------


def test_the_weekly_hook_starts_one_check_up_per_workspace_with_live_articles(world, queue):
    from apps.blog.tasks import due_checkup_workspaces, queue_seo_checkups
    from apps.workspaces.models import Workspace

    quiet = Workspace.objects.create(organization=world.org, name="No articles")
    assert list(due_checkup_workspaces()) == []
    _live(world)
    assert list(due_checkup_workspaces()) == [world.workspace]

    queue_seo_checkups.now()
    job = AgencyJob.objects.get(kind="seo")
    assert job.workspace == world.workspace and job.requested_by is None
    queue_seo_checkups.now()  # within the week: nothing new
    assert AgencyJob.objects.filter(kind="seo").count() == 1
    assert not AgencyJob.objects.filter(workspace=quiet).exists()

    AgencyJob.objects.filter(pk=job.pk).update(created_at=timezone.now() - dt.timedelta(days=8))
    assert list(due_checkup_workspaces()) == [world.workspace]
    world.workspace.is_archived = True
    world.workspace.save(update_fields=["is_archived"])
    assert list(due_checkup_workspaces()) == []


def test_the_recurring_seo_tasks_are_registered_and_keep_their_schedule(db):
    from apps.blog import tasks
    from apps.blog.apps import BlogConfig

    BlogConfig._register_tasks(sender=None)
    names = set(Task.objects.filter(repeat__gt=0).values_list("verbose_name", flat=True))
    assert {"queue_search_console_syncs", "queue_seo_checkups", "sweep_stuck_blog_publishes"} <= names
    for proxy in (tasks.queue_search_console_syncs, tasks.queue_seo_checkups):
        assert hasattr(proxy.task_function, "__wrapped__"), f"{proxy.name} is not guarded by keep_schedule"
