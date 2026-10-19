"""Private transport history cannot leak through shared job and dashboard pages."""

from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.blog.models import BlogPost, BlogSite
from apps.studio import chat, dashboard, engine
from apps.studio.models import AgencyJob, AgentRun, AutopilotWeek, Conversation, StudioBrief
from apps.studio.views_autopilot import last_run
from apps.telegram.models import TelegramChat, TelegramConnection

PRIVATE_TITLE = "PRIVATE worker campaign negotiation"
PRIVATE_SUMMARY = "PRIVATE transcript contains an undisclosed customer offer"
SHARED_SUMMARY = "The agency prepared the shared campaign overview."


@pytest.fixture(params=["durable", "inactive_binding", "former_binding"])
def private_job(world, request):
    mode = request.param
    conversation = Conversation.objects.create(
        workspace=world.workspace,
        audience="internal",
        is_private=mode != "inactive_binding",
        title="Telegram private conversation",
        created_by=world.editor,
    )
    if mode != "durable":
        connection = TelegramConnection.objects.create(
            workspace=world.workspace,
            bot_id=432198,
            bot_username="synthetic_privacy_bot",
            token="local-only-placeholder",
            webhook_secret="local-only-placeholder",
        )
        if mode == "former_binding":
            # The stable private chat now owns a different conversation. The
            # previous transcript must retain its own durable private marker.
            bound = Conversation.objects.create(
                workspace=world.workspace, audience="client", is_private=True, created_by=world.editor
            )
        else:
            bound = conversation
        TelegramChat.objects.create(
            connection=connection,
            chat_id=87654,
            chat_type="private",
            audience="private",
            private_user=world.editor,
            conversation=bound,
            is_active=False,
        )
    job = AgencyJob.objects.create(
        workspace=world.workspace,
        conversation=conversation,
        kind="chat",
        requested_by=world.editor,
        status="failed",
        title=PRIVATE_TITLE,
        input={"message": PRIVATE_SUMMARY},
        result={"summary": PRIVATE_SUMMARY, "learned": [PRIVATE_SUMMARY]},
        error=PRIVATE_SUMMARY,
        finished_at=timezone.now(),
    )
    AgentRun.objects.create(
        job=job,
        workspace=world.workspace,
        agent="account_manager",
        stage="answer",
        status="succeeded",
        summary=PRIVATE_SUMMARY,
        output={"reply": PRIVATE_SUMMARY},
        finished_at=timezone.now(),
    )
    return job


def _url(world, name, **kwargs):
    return reverse(f"studio:{name}", kwargs={"workspace_id": world.workspace.pk, **kwargs})


@pytest.mark.parametrize("who", ["owner", "editor"])
@pytest.mark.parametrize(
    "endpoint,method", [("job", "get"), ("job_progress", "get"), ("job_retry", "post"), ("job_cancel", "post")]
)
def test_private_job_ids_are_not_readable_or_mutable_through_shared_web_pages(
    client, world, private_job, monkeypatch, who, endpoint, method
):
    # Even its paired owner uses Telegram for private history, rather than a
    # generic workspace page that permits other staff to open the same ID.
    client.force_login(getattr(world, who))
    monkeypatch.setattr(engine, "restart", lambda job: pytest.fail("Private job was retried through the web"))
    monkeypatch.setattr(engine, "cancel", lambda job: pytest.fail("Private job was cancelled through the web"))
    response = getattr(client, method)(_url(world, endpoint, job_id=private_job.pk))
    assert response.status_code == 404
    assert PRIVATE_SUMMARY not in response.content.decode() and PRIVATE_TITLE not in response.content.decode()
    private_job.refresh_from_db()
    assert private_job.status == "failed" and private_job.revision == 1


def test_shared_job_timeline_remains_available_without_private_roster_summaries(client, world, private_job):
    public = AgencyJob.objects.create(
        workspace=world.workspace,
        kind="report",
        status="done",
        title="Shared report",
        result={"summary": SHARED_SUMMARY},
        finished_at=timezone.now(),
    )
    AgentRun.objects.create(
        job=public,
        workspace=world.workspace,
        agent="account_manager",
        stage="write",
        status="succeeded",
        summary=SHARED_SUMMARY,
    )
    client.force_login(world.owner)
    # The team page shows the shared run's summary; Home's Today card lists the shared job as done
    # since yesterday. The private job (failed) never reaches either, nor Home's "Needs your review".
    for endpoint, shared in (("team", SHARED_SUMMARY), ("index", "Shared report")):
        response = client.get(_url(world, endpoint))
        assert response.status_code == 200
        assert shared in response.content.decode()
        assert PRIVATE_SUMMARY not in response.content.decode() and PRIVATE_TITLE not in response.content.decode()
    response = client.get(_url(world, "job", job_id=public.pk))
    assert response.status_code == 200 and SHARED_SUMMARY in response.content.decode()


def test_private_active_titles_and_completed_learning_do_not_enter_shared_dashboard(world, private_job):
    private_job.status = "working"
    private_job.save(update_fields=["status"])
    assert not dashboard.at_work(world.workspace)
    private_job.status, private_job.kind = "done", "plan"
    private_job.save(update_fields=["status", "kind"])
    assert not dashboard.learned(world.workspace)
    public = AgencyJob.objects.create(
        workspace=world.workspace,
        kind="plan",
        status="done",
        result={"learned": [SHARED_SUMMARY]},
        finished_at=timezone.now() - timedelta(days=1),
    )
    assert dashboard.learned(world.workspace) == [SHARED_SUMMARY]
    assert chat.web_jobs(AgencyJob.objects.all()).filter(pk=public.pk).exists()


def test_latest_private_week_plan_cannot_expose_agent_notes_or_job_in_autopilot(client, world, private_job):
    private_job.kind = "plan"
    private_job.save(update_fields=["kind"])
    AutopilotWeek.objects.create(workspace=world.workspace, week_start=date(2026, 10, 26), job=private_job)
    assert last_run(world.workspace) is None
    public = AgencyJob.objects.create(workspace=world.workspace, kind="plan", status="done", title="Shared week plan")
    public_week = AutopilotWeek.objects.create(workspace=world.workspace, week_start=date(2026, 10, 19), job=public)
    AgentRun.objects.create(
        job=public,
        workspace=world.workspace,
        agent="performance_analyst",
        stage="listen",
        status="succeeded",
        summary=SHARED_SUMMARY,
    )
    assert last_run(world.workspace)["week"] == public_week
    client.force_login(world.owner)
    response = client.get(_url(world, "autopilot"))
    assert response.status_code == 200
    assert SHARED_SUMMARY in response.content.decode()
    assert PRIVATE_SUMMARY not in response.content.decode() and str(private_job.pk) not in response.content.decode()


def test_explicitly_prepared_agency_drafts_remain_shared_without_exposing_parent_private_job(
    client, world, private_job
):
    brief = StudioBrief.objects.create(
        workspace=world.workspace,
        author=world.editor,
        requested_by=world.editor,
        job=private_job,
        idea="Shared draft explicitly prepared by the paired worker",
        status="ready",
    )
    # Production has been explicitly requested. Its agency draft is shared;
    # the preceding brainstorming transcript/job never becomes a shared view.
    assert any(row.get("brief") == brief for row in dashboard.waiting(world.workspace))
    client.force_login(world.owner)
    response = client.get(_url(world, "detail", brief_id=brief.pk))
    assert response.status_code == 200
    assert PRIVATE_SUMMARY not in response.content.decode()
    assert client.get(_url(world, "job", job_id=private_job.pk)).status_code == 404


def test_private_article_jobs_cannot_bypass_privacy_through_blog_pages(client, world, private_job, monkeypatch):
    site = BlogSite.objects.create(
        workspace=world.workspace,
        name="Shared brand website",
        kind="neopolis_static",
        site_url="https://brand.example.test",
        repo="synthetic/brand",
    )
    post = BlogPost.objects.create(workspace=world.workspace, site=site, title="Shared article", slug="shared-article")
    private_job.kind, private_job.blog_post = "blog", post
    private_job.save(update_fields=["kind", "blog_post"])
    client.force_login(world.owner)
    job_url = reverse("blog:team_job", kwargs={"workspace_id": world.workspace.pk, "job_id": private_job.pk})
    assert client.get(job_url).status_code == 404
    assert client.get(job_url, HTTP_HX_REQUEST="true").status_code == 404
    monkeypatch.setattr(engine, "restart", lambda job: pytest.fail("Private blog work was retried through web"))
    retry_url = reverse("blog:team_retry", kwargs={"workspace_id": world.workspace.pk, "job_id": private_job.pk})
    assert client.post(retry_url).status_code == 404
    write_url = reverse("blog:write", kwargs={"workspace_id": world.workspace.pk})
    panel_url = reverse("blog:team_panel", kwargs={"workspace_id": world.workspace.pk, "post_id": post.pk})
    for url in (write_url, panel_url):
        response = client.get(url)
        assert response.status_code == 200
        assert PRIVATE_TITLE not in response.content.decode() and PRIVATE_SUMMARY not in response.content.decode()
    private_job.status = "working"
    private_job.save(update_fields=["status"])
    assert str(private_job.pk) not in client.get(panel_url).content.decode()


def test_explicit_shared_article_child_is_visible_without_private_parent_history(client, world, private_job):
    shared = AgencyJob.objects.create(
        workspace=world.workspace,
        parent=private_job,
        kind="blog",
        status="done",
        title="Explicit shared production",
        result={"summary": SHARED_SUMMARY},
    )
    client.force_login(world.owner)
    response = client.get(reverse("blog:team_job", kwargs={"workspace_id": world.workspace.pk, "job_id": shared.pk}))
    assert response.status_code == 200
    assert SHARED_SUMMARY in response.content.decode()
    assert PRIVATE_SUMMARY not in response.content.decode() and PRIVATE_TITLE not in response.content.decode()
