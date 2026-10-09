"""The agency's pages: the home, the team roster, a job's timeline, and who may see them."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.members.models import WorkspaceMembership
from apps.studio import engine, team
from apps.studio.models import AgencyJob, StudioBrief
from apps.studio.tests.conftest import make_brief, run_all


def _url(name, world, **kwargs):
    return reverse(name, kwargs={"workspace_id": world.workspace.id, **kwargs})


def test_the_home_shows_what_is_waiting_with_one_click_approval(client, world, fake_team):
    from apps.calendar.services import create_default_queue_and_slots

    create_default_queue_and_slots(world.linkedin)
    brief = run_all(make_brief(world))
    client.force_login(world.owner)

    html = client.get(_url("studio:index", world)).content.decode()

    assert "Waiting for your approval" in html and brief.title in html
    assert 'name="mode" value="proposed"' in html
    assert "Team at work" in html and "The next seven days" in html
    assert "Meet the team" in html


def test_approve_at_the_proposed_time_schedules_it_there(client, world, fake_team):
    from apps.calendar.services import create_default_queue_and_slots

    create_default_queue_and_slots(world.linkedin)
    brief = run_all(make_brief(world))
    client.force_login(world.owner)

    client.post(_url("studio:approve", world, brief_id=brief.id), {"mode": "proposed"})

    brief.refresh_from_db()
    pp = brief.post.platform_posts.get()
    assert brief.status == StudioBrief.Status.APPROVED
    assert pp.status == "scheduled" and pp.scheduled_at == brief.proposed_publish_at


def test_a_passed_proposed_time_is_not_used(client, world, fake_team):
    brief = run_all(make_brief(world))
    StudioBrief.objects.filter(pk=brief.pk).update(proposed_publish_at=timezone.now() - timedelta(hours=1))
    client.force_login(world.owner)

    client.post(_url("studio:approve", world, brief_id=brief.id), {"mode": "proposed"})

    brief.refresh_from_db()
    assert brief.status == StudioBrief.Status.READY
    assert brief.post.platform_posts.get().status == "pending_review"


def test_the_team_roster_lists_every_agent_by_department(client, world):
    client.force_login(world.viewer)
    html = client.get(_url("studio:team", world)).content.decode()

    for agent in team.AGENTS:
        assert agent.name in html
    for department in team.DEPARTMENTS:
        assert department.name.replace("&", "&amp;") in html
    assert len(team.AGENTS) >= 25


def test_a_client_is_sent_to_the_portal_not_the_agency(client, world, fake_team):
    brief = run_all(make_brief(world))
    client_user = world.viewer.__class__.objects.create_user(
        email="client@example.com", password="pw-12345678", name="Client", tos_accepted_at=timezone.now()
    )
    WorkspaceMembership.objects.create(user=client_user, workspace=world.workspace, workspace_role="client")
    client.force_login(client_user)

    assert client.get(_url("studio:index", world)).status_code == 403
    assert client.get(_url("studio:detail", world, brief_id=brief.id)).status_code == 403
    response = client.post(_url("studio:approve", world, brief_id=brief.id), {"mode": "approve"})
    assert response.status_code == 403
    brief.refresh_from_db()
    assert brief.status == StudioBrief.Status.READY


@pytest.fixture
def report_job(world, monkeypatch):
    from apps.studio import jobs

    def first(job):
        run = engine.begin(job, "reporter")
        engine.end(run, summary="Wrote the weekly report.")
        engine.finish(job, result={"summary": "Twelve posts went out."})

    monkeypatch.setitem(
        jobs.JOB_TYPES, "report", engine.JobType(kind="report", stages=(engine.Stage("write", "reporter", first),))
    )
    monkeypatch.setattr(engine, "enqueue", lambda job, stage: None)
    return engine.create(world.workspace, "report", title="Weekly report", requested_by=world.owner)


def test_a_jobs_timeline_and_result(client, world, report_job):
    engine.run_step(str(report_job.pk), 1, "write")
    client.force_login(world.editor)

    html = client.get(_url("studio:job", world, job_id=report_job.id)).content.decode()

    assert "Client reporter" in html and "Wrote the weekly report." in html
    assert "Twelve posts went out." in html
    progress = client.get(_url("studio:job_progress", world, job_id=report_job.id))
    assert progress["HX-Refresh"] == "true"


def test_a_failed_job_can_be_retried_by_staff(client, world, report_job):
    AgencyJob.objects.filter(pk=report_job.pk).update(status=AgencyJob.Status.FAILED, error="Boom.")
    client.force_login(world.viewer)
    assert client.post(_url("studio:job_retry", world, job_id=report_job.id)).status_code == 403

    client.force_login(world.editor)
    client.post(_url("studio:job_retry", world, job_id=report_job.id))
    report_job.refresh_from_db()
    assert report_job.status == AgencyJob.Status.QUEUED and report_job.revision == 2


def test_jobs_of_another_workspace_are_not_found(client, world, report_job):
    from apps.workspaces.models import Workspace

    other = Workspace.objects.create(organization=world.org, name="Other")
    AgencyJob.objects.filter(pk=report_job.pk).update(workspace=other)
    client.force_login(world.owner)
    assert client.get(_url("studio:job", world, job_id=report_job.id)).status_code == 404
