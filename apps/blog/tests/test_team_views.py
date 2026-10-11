"""Writing with the SEO team from the blog pages: who may start work, what it queues, what people see.

No agent runs here: the views only queue jobs (``engine.enqueue`` is recorded,
not run), and the job's own behaviour is tested in
``apps/studio/tests/test_blog_job.py``.
"""

import pytest
from django.urls import reverse

from apps.blog import views_team
from apps.blog.models import BlogPost, BlogSite
from apps.blog.tests.conftest import make_post
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.studio import engine
from apps.studio.jobtypes import blog as blog_job
from apps.studio.models import AgencyJob, AgencySettings, AgentRun
from apps.workspaces.models import Workspace


@pytest.fixture
def queued(settings, monkeypatch):
    settings.ANTHROPIC_API_KEY = "sk-ant-test"
    calls = []
    monkeypatch.setattr(engine, "enqueue", lambda job, stage: calls.append((job.pk, stage)))
    return calls


def _url(name, world, **kwargs):
    return reverse(f"blog:{name}", kwargs={"workspace_id": world.workspace.id, **kwargs})


def _linkedin(world):
    return SocialAccount.objects.create(
        workspace=world.workspace,
        platform="linkedin_company",
        account_platform_id="98765",
        account_name="Neopolis Infra",
        oauth_access_token="li-token",
    )


# ---------------------------------------------------------------------------
# Write with the team
# ---------------------------------------------------------------------------


def test_the_write_page_shows_the_form_and_the_team(client, world, queued):
    client.force_login(world.editor)

    response = client.get(_url("write", world))

    html = response.content.decode()
    assert response.status_code == 200
    assert "Write with the SEO team" in html and 'name="topic"' in html
    assert "Neopolis Infra website" in html and "More Space website" in html
    assert "SEO strategist" in html and "Editor-in-chief" in html and "Producer" in html


@pytest.mark.parametrize("role", ["client", "viewer"])
def test_clients_and_viewers_can_t_brief_the_team(client, world, queued, role):
    client.force_login(getattr(world, role))

    assert client.get(_url("write", world)).status_code == 403
    response = client.post(_url("write", world), {"topic": "x", "site": world.neopolis.pk})

    assert response.status_code == 403 and not AgencyJob.objects.exists()


def test_an_outsider_can_t_reach_the_page(client, world, queued):
    client.force_login(world.outsider)

    assert client.get(_url("write", world)).status_code in (403, 404)


def test_briefing_the_team_queues_an_article_job(client, world, queued):
    client.force_login(world.editor)

    response = client.post(
        _url("write", world),
        {
            "topic": "How to check a land title",
            "site": str(world.morespace.pk),
            "focus_keyword": "land title verification",
            "notes": "Mention the free title check.",
        },
    )

    job = AgencyJob.objects.get()
    assert response.status_code == 302 and response["Location"] == _url("team_job", world, job_id=job.pk)
    assert job.kind == "blog" and job.workspace == world.workspace and job.requested_by == world.editor
    assert job.input == {
        "topic": "How to check a land title",
        "site_id": str(world.morespace.pk),
        "focus_keyword": "land title verification",
        "notes": "Mention the free title check.",
        "category": "",
    }
    assert queued == [(job.pk, "research")]


def test_another_workspace_s_site_is_refused(client, world, queued):
    other = Workspace.objects.create(organization=Organization.objects.create(name="Other"), name="Other")
    theirs = BlogSite.objects.create(
        workspace=other, name="Theirs", kind="morespace_static", site_url="https://theirs.example", repo="o/t"
    )
    client.force_login(world.editor)

    response = client.post(_url("write", world), {"topic": "Hello", "site": str(theirs.pk)})

    assert response.status_code == 400 and not AgencyJob.objects.exists()


def test_over_budget_nothing_is_queued(client, world, queued):
    AgencySettings.objects.create(workspace=world.workspace, monthly_budget_usd=0)
    client.force_login(world.editor)

    response = client.post(_url("write", world), {"topic": "Hello", "site": str(world.neopolis.pk)})

    assert response.status_code == 409 and "AI budget" in response.content.decode()
    assert not AgencyJob.objects.exists() and not queued


def test_without_claude_nothing_is_queued(client, world, queued, settings):
    settings.ANTHROPIC_API_KEY = ""
    client.force_login(world.editor)

    response = client.post(_url("write", world), {"topic": "Hello", "site": str(world.neopolis.pk)})

    assert response.status_code == 409 and "set up yet" in response.content.decode()
    assert not AgencyJob.objects.exists()


def test_the_team_writes_at_most_three_articles_at_once(client, world, queued):
    for n in range(views_team.MAX_ACTIVE_ARTICLES):
        blog_job.start_article(world.workspace, topic=f"Topic {n}", site=world.neopolis, requested_by=world.editor)
    client.force_login(world.editor)

    response = client.post(_url("write", world), {"topic": "One more", "site": str(world.neopolis.pk)})

    assert response.status_code == 409 and "already working on 3 articles" in response.content.decode()
    assert AgencyJob.objects.count() == 3


def test_a_workspace_without_a_website_gets_the_no_sites_page(client, world, queued):
    BlogSite.objects.filter(workspace=world.workspace).update(is_enabled=False)
    client.force_login(world.editor)

    response = client.get(_url("write", world))

    assert response.status_code == 200 and "No website to publish to" in response.content.decode()


def test_the_list_page_offers_write_with_the_team(client, world):
    client.force_login(world.editor)

    html = client.get(_url("list", world)).content.decode()

    assert "Write with the team" in html and _url("write", world) in html


# ---------------------------------------------------------------------------
# The team's progress
# ---------------------------------------------------------------------------


def test_the_progress_page_shows_who_is_working_and_polls(client, world, queued):
    job = blog_job.start_article(world.workspace, topic="Land titles", site=world.neopolis, requested_by=world.editor)
    client.force_login(world.editor)

    page = client.get(_url("team_job", world, job_id=job.pk)).content.decode()
    partial = client.get(_url("team_job", world, job_id=job.pk), HTTP_HX_REQUEST="true").content.decode()

    assert "Article: Land titles" in page and "SEO strategist" in page and "Up next" in page
    assert "Outline editor" in page and "Blog writer" in page
    assert 'hx-trigger="every 4s"' in partial and "<html" not in partial


def test_a_finished_job_links_to_the_draft_and_stops_polling(client, world, queued):
    post = make_post(world)
    job = blog_job.start_article(world.workspace, topic="Kokapet", site=world.neopolis, requested_by=world.editor)
    AgentRun.objects.create(
        job=job, agent="blog_writer", stage="write", status="succeeded", summary="Wrote 1,200 words."
    )
    AgencyJob.objects.filter(pk=job.pk).update(
        status="done", stage="done", blog_post=post, result={"blog_post_id": str(post.pk), "summary": "Saved."}
    )
    client.force_login(world.editor)

    html = client.get(_url("team_job", world, job_id=job.pk), HTTP_HX_REQUEST="true").content.decode()

    assert "Your draft is ready for approval" in html and _url("detail", world, post_id=post.pk) in html
    assert "Wrote 1,200 words." in html and "SEO score" in html
    assert "hx-trigger" not in html


def test_a_failed_job_offers_retry_and_retry_restarts_it(client, world, queued):
    job = blog_job.start_article(world.workspace, topic="Kokapet", site=world.neopolis, requested_by=world.editor)
    AgencyJob.objects.filter(pk=job.pk).update(status="failed", stage="write", error="Claude is busy.")
    client.force_login(world.editor)

    html = client.get(_url("team_job", world, job_id=job.pk)).content.decode()
    assert "Claude is busy." in html and _url("team_retry", world, job_id=job.pk) in html

    response = client.post(_url("team_retry", world, job_id=job.pk))

    job.refresh_from_db()
    assert response.status_code == 302 and job.status == "queued" and job.revision == 2
    assert queued[-1] == (job.pk, "write")


def test_another_workspace_s_job_is_not_found(client, world, queued):
    other = Workspace.objects.create(organization=world.org, name="Sister brand")
    job = engine.create(other, "blog", title="Theirs")
    client.force_login(world.owner)

    assert client.get(_url("team_job", world, job_id=job.pk)).status_code == 404


def test_a_client_can_t_see_the_team_s_work(client, world, queued):
    job = blog_job.start_article(world.workspace, topic="Kokapet", site=world.neopolis, requested_by=world.editor)
    client.force_login(world.client)

    assert client.get(_url("team_job", world, job_id=job.pk)).status_code == 403


# ---------------------------------------------------------------------------
# Ask the SEO team, on an article
# ---------------------------------------------------------------------------


def test_the_article_page_loads_the_ask_the_team_banner(client, world):
    post = make_post(world)
    client.force_login(world.editor)

    html = client.get(_url("detail", world, post_id=post.pk)).content.decode()

    assert _url("team_panel", world, post_id=post.pk) in html and 'hx-trigger="load"' in html


def test_the_banner_offers_a_change_and_improve_seo_on_a_draft(client, world):
    post = make_post(world)
    client.force_login(world.editor)

    html = client.get(_url("team_panel", world, post_id=post.pk)).content.decode()

    assert "Ask the SEO team" in html and "Improve SEO" in html and 'name="feedback"' in html
    assert _url("team_revise", world, post_id=post.pk) in html
    assert "Make social posts" not in html


def test_the_banner_offers_social_posts_once_approved(client, world):
    post = make_post(world)
    BlogPost.objects.filter(pk=post.pk).update(status=BlogPost.Status.APPROVED)
    _linkedin(world)
    client.force_login(world.editor)

    html = client.get(_url("team_panel", world, post_id=post.pk)).content.decode()

    assert "Make social posts" in html and "Improve SEO" not in html


@pytest.mark.parametrize("role", ["client", "viewer"])
def test_the_banner_is_empty_for_people_who_can_t_use_it(client, world, role):
    post = make_post(world)
    client.force_login(getattr(world, role))

    response = client.get(_url("team_panel", world, post_id=post.pk))

    assert response.status_code == 200 and response.content == b""


def test_asking_for_a_change_queues_a_revision(client, world, queued):
    post = make_post(world)
    client.force_login(world.editor)

    response = client.post(
        _url("team_revise", world, post_id=post.pk), {"feedback": "Add a section on encumbrance certificates"}
    )

    job = AgencyJob.objects.get()
    assert response["Location"] == _url("team_job", world, job_id=job.pk)
    assert job.blog_post_id == post.pk and job.kind == "blog"
    assert job.input == {"revision_of": str(post.pk), "feedback": "Add a section on encumbrance certificates"}
    post.refresh_from_db()
    assert post.revision == 1  # nothing changes until the team is done


def test_improve_seo_asks_the_team_to_fix_what_the_score_flags(client, world, queued):
    post = make_post(world)
    client.force_login(world.editor)

    client.post(_url("team_revise", world, post_id=post.pk), {"mode": "seo"})

    assert AgencyJob.objects.get().input["feedback"] == "Fix everything the SEO score flags"


def test_an_empty_change_request_is_refused(client, world, queued):
    post = make_post(world)
    client.force_login(world.editor)

    response = client.post(_url("team_revise", world, post_id=post.pk), {"feedback": "  "})

    assert response["Location"] == _url("detail", world, post_id=post.pk) and not AgencyJob.objects.exists()


def test_an_approved_article_is_not_revised_by_the_team(client, world, queued):
    post = make_post(world)
    BlogPost.objects.filter(pk=post.pk).update(status=BlogPost.Status.APPROVED)
    client.force_login(world.editor)

    client.post(_url("team_revise", world, post_id=post.pk), {"feedback": "Shorter"})

    assert not AgencyJob.objects.exists()


def test_one_team_job_per_article_at_a_time(client, world, queued):
    post = make_post(world)
    blog_job.start_revision(post, feedback="First", requested_by=world.editor)
    client.force_login(world.editor)

    client.post(_url("team_revise", world, post_id=post.pk), {"feedback": "Second"})

    assert AgencyJob.objects.count() == 1


def test_revising_needs_the_right_to_edit_that_article(client, world, queued):
    from apps.members.models import WorkspaceMembership

    post = make_post(world, author=world.owner)
    WorkspaceMembership.objects.filter(user=world.editor, workspace=world.workspace).update(
        workspace_role="contributor"
    )
    client.force_login(world.editor)

    response = client.post(_url("team_revise", world, post_id=post.pk), {"feedback": "Shorter"})

    assert response.status_code == 403 and not AgencyJob.objects.exists()


def test_revising_over_budget_queues_nothing(client, world, queued):
    AgencySettings.objects.create(workspace=world.workspace, monthly_budget_usd=0)
    post = make_post(world)
    client.force_login(world.editor)

    client.post(_url("team_revise", world, post_id=post.pk), {"feedback": "Shorter"})

    assert not AgencyJob.objects.exists()


def test_making_social_posts_from_an_approved_article(client, world, queued):
    post = make_post(world)
    BlogPost.objects.filter(pk=post.pk).update(status=BlogPost.Status.APPROVED)
    _linkedin(world)
    client.force_login(world.editor)

    response = client.post(_url("team_repurpose", world, post_id=post.pk))

    job = AgencyJob.objects.get()
    assert response["Location"] == _url("team_job", world, job_id=job.pk)
    assert job.kind == "repurpose" and job.blog_post_id == post.pk and queued == [(job.pk, "ideas")]
    post.refresh_from_db()
    assert post.status == BlogPost.Status.APPROVED


def test_social_posts_need_an_approved_article_and_an_account(client, world, queued):
    draft = make_post(world)
    client.force_login(world.editor)

    client.post(_url("team_repurpose", world, post_id=draft.pk))
    assert not AgencyJob.objects.exists()

    approved = make_post(world, slug="another-one", title="Another one")
    BlogPost.objects.filter(pk=approved.pk).update(status=BlogPost.Status.PUBLISHED)
    client.post(_url("team_repurpose", world, post_id=approved.pk))  # no social account connected
    assert not AgencyJob.objects.exists()


def test_a_client_can_t_ask_the_team(client, world, queued):
    post = make_post(world)
    client.force_login(world.client)

    assert client.post(_url("team_revise", world, post_id=post.pk), {"feedback": "x"}).status_code == 403
    assert client.post(_url("team_repurpose", world, post_id=post.pk)).status_code == 403
    assert not AgencyJob.objects.exists()


def test_another_workspace_s_article_is_not_found(client, world, queued):
    other = Workspace.objects.create(organization=world.org, name="Sister brand")
    site = BlogSite.objects.create(
        workspace=other, name="Sister", kind="morespace_static", site_url="https://sister.example", repo="o/s"
    )
    theirs = BlogPost.objects.create(workspace=other, site=site, title="Theirs", slug="theirs", body="x")
    client.force_login(world.owner)

    assert client.post(_url("team_revise", world, post_id=theirs.pk), {"feedback": "x"}).status_code == 404
    assert client.get(_url("team_panel", world, post_id=theirs.pk)).status_code == 404
    assert not AgencyJob.objects.exists()
