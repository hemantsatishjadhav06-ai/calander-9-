"""The SEO parts of the blog pages: the live score in the editor, the score card and badges, the check-up button."""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django.urls import reverse

from apps.blog.models import BlogPost, BlogPostEvent
from apps.blog.tests.conftest import approved_post, make_post
from apps.studio.models import AgencyJob

Status = BlogPost.Status


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    cache.clear()
    yield
    cache.clear()


def url(name, world, post=None, **extra):
    kwargs = {"workspace_id": world.workspace.id, **extra}
    if post is not None:
        kwargs["post_id"] = post.id
    return reverse(f"blog:{name}", kwargs=kwargs)


DRAFT = {
    "title": "How to read a land title in 5 checks",
    "slug": "how-to-read-a-land-title",
    "seo_title": "Land Title Verification: 5 Checks Before You Buy",
    "meta_description": "Buying in Hyderabad? Check these 5 things on a land title before you pay a token.",
    "excerpt": "Five checks.",
    "body": "## Why the title matters\n\nA clear title protects you.",
    "focus_keyword": "land title verification",
    "secondary_keywords": "encumbrance certificate, RERA",
    "faq_text": "Q: How long?\nA: A week.",
    "featured_image": "",
    "cover_style": "designed",
}


# ---------------------------------------------------------------------------
# The live score
# ---------------------------------------------------------------------------


def test_the_editor_has_the_keyword_fields_and_the_live_panel(client, world):
    client.force_login(world.editor)
    body = client.get(url("create", world)).content.decode()
    assert 'name="focus_keyword"' in body and 'name="secondary_keywords"' in body
    assert f'hx-post="{url("seo_score", world)}"' in body
    assert 'hx-include="#blog-post-form"' in body and 'id="blog-post-form"' in body
    assert "Google preview" in body and 'x-text="titleTag()' in body
    assert '"titleSuffixes"' in body  # the <title> rule reaches the counter


def test_the_score_endpoint_scores_unsaved_values_and_saves_nothing(client, world):
    client.force_login(world.editor)
    response = client.post(url("seo_score", world), {**DRAFT, "site": world.neopolis.pk}, HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Land Title Verification: 5 Checks Before You Buy" in body  # 49 + suffix > 60: no suffix
    assert "www.neopolisinfra.com › blog › how-to-read-a-land-title" in body
    assert 'id="seo-live" hx-swap-oob="true"' in body
    assert "Keyword in the search title" in body
    assert not BlogPost.objects.exists() and not BlogPostEvent.objects.exists()


def test_the_per_post_score_keeps_a_published_address_and_changes_nothing(client, world):
    post = approved_post(world)
    BlogPost.objects.filter(pk=post.pk).update(status=Status.PUBLISHED, published_card={"slug": post.slug})
    before = list(BlogPost.objects.filter(pk=post.pk).values_list("revision", "updated_at", "approved_fingerprint"))
    events = BlogPostEvent.objects.count()
    client.force_login(world.editor)
    response = client.post(
        url("post_seo_score", world, post), {**DRAFT, "slug": "sneaky-new-address", "site": world.morespace.pk}
    )
    body = response.content.decode()
    assert response.status_code == 200
    assert "flats-in-kokapet-2026" in body and "sneaky-new-address" not in body
    assert "www.neopolisinfra.com" in body  # a published post's website is fixed too
    assert list(BlogPost.objects.filter(pk=post.pk).values_list("revision", "updated_at", "approved_fingerprint")) == (
        before
    )
    assert BlogPostEvent.objects.count() == events


def test_a_site_from_another_workspace_is_ignored(client, world):
    from apps.blog.models import BlogSite
    from apps.workspaces.models import Workspace

    other = Workspace.objects.create(organization=world.org, name="Elsewhere")
    foreign = BlogSite.objects.create(
        workspace=other,
        name="Foreign",
        kind="morespace_static",
        site_url="https://foreign.example",
        repo="f/r",
        workflow_file="w",
    )
    client.force_login(world.editor)
    body = client.post(url("seo_score", world), {**DRAFT, "site": foreign.pk}).content.decode()
    assert "foreign.example" not in body


@pytest.mark.parametrize("role", ["client", "viewer", "outsider"])
def test_the_score_endpoint_is_for_the_team(client, world, role):
    client.force_login(getattr(world, role))
    assert client.post(url("seo_score", world), DRAFT).status_code in (403, 404)


def test_the_score_endpoint_takes_posts_only_and_needs_login(client, world):
    assert client.post(url("seo_score", world), DRAFT).status_code == 302
    client.force_login(world.editor)
    assert client.get(url("seo_score", world)).status_code == 405


def test_another_workspaces_post_is_not_scored(client, world):
    from apps.blog.models import BlogSite
    from apps.members.models import WorkspaceMembership
    from apps.workspaces.models import Workspace

    other = Workspace.objects.create(organization=world.org, name="Other")
    WorkspaceMembership.objects.create(user=world.editor, workspace=other, workspace_role="editor")
    BlogSite.objects.create(
        workspace=other, name="O", kind="morespace_static", site_url="https://o.example", repo="o/r2", workflow_file="w"
    )
    post = make_post(world)
    client.force_login(world.editor)
    response = client.post(reverse("blog:post_seo_score", kwargs={"workspace_id": other.id, "post_id": post.id}), DRAFT)
    assert response.status_code == 404


def test_saving_the_editor_stores_the_keywords(client, world):
    client.force_login(world.editor)
    response = client.post(url("create", world), {**DRAFT, "site": world.neopolis.pk, "featured_image_alt": ""})
    post = BlogPost.objects.get(slug="how-to-read-a-land-title")
    assert response.status_code == 302
    assert post.focus_keyword == "land title verification"
    assert post.secondary_keywords == ["encumbrance certificate", "RERA"]
    edit = client.get(url("edit", world, post)).content.decode()
    assert 'value="encumbrance certificate, RERA"' in edit


def test_too_many_related_terms_is_a_form_error(client, world):
    client.force_login(world.editor)
    terms = ", ".join(f"term {i}" for i in range(12))
    response = client.post(url("create", world), {**DRAFT, "site": world.neopolis.pk, "secondary_keywords": terms})
    assert response.status_code == 200 and "secondary_keywords" in response.context["form"].errors
    assert not BlogPost.objects.exists()


# ---------------------------------------------------------------------------
# Score card, badges and the Google Search section
# ---------------------------------------------------------------------------


def test_the_detail_page_has_an_seo_score_card(client, world):
    post = make_post(world, focus_keyword="flats in kokapet")
    client.force_login(world.editor)
    body = client.get(url("detail", world, post)).content.decode()
    assert "SEO score" in body and "flats in kokapet" in body and "See every check in the editor" in body
    assert "Flats in Kokapet 2026 | Neopolis Infra Blog" in body


def test_the_list_shows_a_score_badge_per_post_and_the_google_section(client, world, settings):
    settings.GSC_CLIENT_ID = ""
    make_post(world)
    client.force_login(world.owner)
    body = client.get(url("list", world)).content.decode()
    import re

    assert re.search(r"SEO \d+<span class=\"sr-only\"> of 100", body)
    assert 'id="google-search"' in body
    assert "Ask your admin to connect Google Search Console" in body
    assert "Run an SEO check-up" in body


def test_owners_see_the_connect_button_and_editors_do_not(client, world, settings):
    settings.GSC_CLIENT_ID = "id"
    settings.GSC_CLIENT_SECRET = "secret"
    client.force_login(world.owner)
    assert "Connect Google Search Console" in client.get(url("list", world)).content.decode()
    client.force_login(world.editor)
    body = client.get(url("list", world)).content.decode()
    assert "Connect Google Search Console" not in body and "An owner of this workspace can connect" in body


def test_clients_do_not_see_the_check_up(client, world):
    client.force_login(world.client)
    body = client.get(url("list", world)).content.decode()
    assert "Run an SEO check-up" not in body and "Latest SEO check-up" not in body


# ---------------------------------------------------------------------------
# The check-up button
# ---------------------------------------------------------------------------


def test_the_check_up_button_starts_the_seo_monitor_once(client, world):
    client.force_login(world.editor)
    response = client.post(url("seo_checkup", world))
    job = AgencyJob.objects.get(workspace=world.workspace, kind="seo")
    assert response.status_code == 302
    assert response["Location"] == reverse("studio:job", kwargs={"workspace_id": world.workspace.id, "job_id": job.pk})
    assert job.requested_by == world.editor and job.status == AgencyJob.Status.QUEUED
    again = client.post(url("seo_checkup", world))
    assert again["Location"] == response["Location"]
    assert AgencyJob.objects.filter(kind="seo").count() == 1


@pytest.mark.parametrize("role", ["client", "viewer"])
def test_only_the_team_can_start_a_check_up(client, world, role):
    client.force_login(getattr(world, role))
    assert client.post(url("seo_checkup", world)).status_code == 403
    assert not AgencyJob.objects.exists()


def test_the_check_up_button_is_rate_limited(client, world):
    client.force_login(world.editor)
    codes = [client.post(url("seo_checkup", world)).status_code for _ in range(11)]
    assert codes[:10] == [302] * 10 and codes[10] == 403
