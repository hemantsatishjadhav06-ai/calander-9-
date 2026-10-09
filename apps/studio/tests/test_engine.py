"""The agency job engine, and the rule that agency work never approves or schedules.

A tiny job type is registered for these tests, so the engine's guarantees are
pinned independently of any real job: stage chaining, revision guarding,
failures that become sentences, the sweep, and the agent-work guard.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.approvals import services as approval_services
from apps.composer.models import PlatformPost, Post
from apps.studio import engine, guards, llm
from apps.studio.models import AgencyJob, AgentRun

calls = []


def _first(job):
    calls.append(("first", job.revision))
    run = engine.begin(job, "planner")
    engine.update_state(job, seen=True)
    engine.end(run, summary="Planned.", output={"ok": True})
    return "second"


def _second(job):
    calls.append(("second", job.revision))
    engine.finish(job, result={"done": True})
    return None


def _fails(job):
    raise llm.StudioAgentError("Claude is rate-limiting this account right now.")


def _crashes(job):
    raise RuntimeError("boom")


TEST_TYPE = engine.JobType(
    kind="report", stages=(engine.Stage("first", "planner", _first), engine.Stage("second", "planner", _second))
)


@pytest.fixture
def queue(monkeypatch):
    from apps.studio import jobs

    calls.clear()
    monkeypatch.setitem(jobs.JOB_TYPES, "report", TEST_TYPE)
    queued = []
    monkeypatch.setattr(engine, "enqueue", lambda job, stage: queued.append((job.pk, job.revision, stage)))
    return queued


def _drive(job, limit=10):
    for _ in range(limit):
        job.refresh_from_db()
        if not job.is_active:
            return job
        engine.run_step(str(job.pk), job.revision, job.stage)
    raise AssertionError("did not finish")


def test_a_job_runs_its_stages_in_order_and_finishes(world, queue):
    job = engine.create(world.workspace, "report", title="Weekly report", requested_by=world.owner)
    assert queue == [(job.pk, 1, "first")]

    job = _drive(job)

    assert job.status == AgencyJob.Status.DONE and job.stage == "done"
    assert job.state == {"seen": True} and job.result == {"done": True}
    assert calls == [("first", 1), ("second", 1)]
    run = AgentRun.objects.get(job=job)
    assert run.workspace_id == world.workspace.id and run.agent == "planner" and run.status == "succeeded"
    assert run.brief_id is None and run.agent_name == "Content planner"


def test_a_stale_stage_is_skipped(world, queue):
    job = engine.create(world.workspace, "report")
    engine.restart(job, "first")  # a person asked again: revision 2

    engine.run_step(str(job.pk), 1, "first")

    assert calls == []
    job.refresh_from_db()
    assert job.revision == 2 and job.status == AgencyJob.Status.QUEUED


def test_a_failure_is_a_sentence_and_retry_resumes(world, queue, monkeypatch):
    monkeypatch.setitem(
        __import__("apps.studio.jobs", fromlist=["JOB_TYPES"]).JOB_TYPES,
        "report",
        engine.JobType(kind="report", stages=(engine.Stage("first", "planner", _fails),)),
    )
    job = _drive(engine.create(world.workspace, "report"))
    assert job.status == AgencyJob.Status.FAILED and "rate-limiting" in job.error

    monkeypatch.setitem(
        __import__("apps.studio.jobs", fromlist=["JOB_TYPES"]).JOB_TYPES,
        "report",
        engine.JobType(kind="report", stages=(engine.Stage("first", "planner", _crashes),)),
    )
    engine.restart(job)
    job = _drive(job)
    assert job.status == AgencyJob.Status.FAILED and "content planner hit an unexpected error" in job.error


def test_the_sweep_fails_dead_jobs_but_not_waiting_ones(world, queue):
    dead = engine.create(world.workspace, "report")
    AgencyJob.objects.filter(pk=dead.pk).update(
        status=AgencyJob.Status.WORKING, updated_at=timezone.now() - timedelta(hours=2)
    )
    waiting = engine.create(world.workspace, "report")
    AgencyJob.objects.filter(pk=waiting.pk).update(updated_at=timezone.now() - timedelta(hours=2))
    from background_task.models import Task

    Task.objects.create(
        task_name="apps.studio.tasks.run_agency_step",
        task_params=f'[["{waiting.pk}", 1, "first"], {{}}]',
        task_hash="x",
        run_at=timezone.now(),
    )

    assert engine.sweep_stuck() == 1
    dead.refresh_from_db()
    waiting.refresh_from_db()
    assert dead.status == AgencyJob.Status.FAILED and "Retry" in dead.error
    assert waiting.status == AgencyJob.Status.QUEUED


def test_failed_calls_still_count_their_tokens(world, queue):
    job = engine.create(world.workspace, "report")
    AgencyJob.objects.filter(pk=job.pk).update(status=AgencyJob.Status.WORKING)
    job.refresh_from_db()

    def refusal():
        raise llm.StudioAgentError("declined", usage=("claude-opus-5-5", 1200, 300, 0))

    with pytest.raises(llm.StudioAgentError):
        engine.call(job, "planner", refusal)

    run = AgentRun.objects.get(job=job)
    assert (run.status, run.input_tokens, run.output_tokens, run.model) == ("failed", 1200, 300, "claude-opus-5-5")
    assert llm.estimate_cost([run]) == pytest.approx((1200 * 4 + 300 * 20) / 1e6)


class TestAgentsNeverApprove:
    """Even where the workspace doesn't require dashboard approval, agency work can't approve or schedule."""

    @pytest.fixture
    def pending(self, world):
        assert not world.workspace.require_dashboard_approval
        post = Post.objects.create(workspace=world.workspace, author=world.owner, caption="Hello")
        pp = PlatformPost.objects.create(post=post, social_account=world.linkedin, status="pending_review")
        return post, pp

    def test_approve_is_refused_inside_agent_work(self, world, pending):
        post, pp = pending
        with guards.agent_work("test"), pytest.raises(guards.AgentMayNotApproveError):
            approval_services.approve_post(post, world.owner, world.workspace)
        pp.refresh_from_db()
        assert pp.status == "pending_review"

    def test_scheduling_is_refused_inside_agent_work(self, world):
        from apps.composer.services import transition_platform_post

        # Without the gate a draft may go straight to scheduled — but not from agency work.
        post = Post.objects.create(workspace=world.workspace, author=world.owner, caption="Hello")
        pp = PlatformPost.objects.create(post=post, social_account=world.linkedin, status="draft")
        with guards.agent_work("test"), pytest.raises(guards.AgentMayNotApproveError):
            transition_platform_post(pp, "scheduled", scheduled_at=timezone.now() + timedelta(days=1))
        pp.refresh_from_db()
        assert pp.status == "draft"

    def test_a_direct_status_write_is_refused_too(self, world, pending):
        _post, pp = pending
        pp.status = "scheduled"
        with guards.agent_work("test"), pytest.raises(guards.AgentMayNotApproveError):
            pp.save()

    def test_submitting_for_review_is_allowed(self, world):
        post = Post.objects.create(workspace=world.workspace, author=world.owner, caption="Hello")
        pp = PlatformPost.objects.create(post=post, social_account=world.linkedin, status="draft")
        with guards.agent_work("test"):
            approval_services.submit_for_review(post, world.owner, world.workspace)
        pp.refresh_from_db()
        assert pp.status == "pending_review"

    def test_people_still_approve_outside_agent_work(self, world, pending):
        post, pp = pending
        approval_services.approve_post(post, world.owner, world.workspace)
        pp.refresh_from_db()
        assert pp.status == "approved"

    def test_a_step_that_tries_is_failed_not_published(self, world, queue, monkeypatch, pending):
        post, pp = pending

        def sneaky(job):
            approval_services.approve_post(post, world.owner, world.workspace)
            return None

        from apps.studio import jobs

        monkeypatch.setitem(
            jobs.JOB_TYPES, "report", engine.JobType(kind="report", stages=(engine.Stage("first", "planner", sneaky),))
        )
        job = _drive(engine.create(world.workspace, "report"))

        assert job.status == AgencyJob.Status.FAILED
        pp.refresh_from_db()
        assert pp.status == "pending_review"
