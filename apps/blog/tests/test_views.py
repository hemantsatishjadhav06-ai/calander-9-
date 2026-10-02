"""Dashboard pages: access, the authenticated preview, and the buttons' rules."""

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.blog.models import BlogPost
from apps.blog.tests.conftest import approved_post, make_post

Status = BlogPost.Status


def url(name, world, post=None):
    kwargs = {"workspace_id": world.workspace.id}
    if post is not None:
        kwargs["post_id"] = post.id
    return reverse(f"blog:{name}", kwargs=kwargs)


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def test_preview_requires_login(client, world):
    post = make_post(world)
    response = client.get(url("preview", world, post))
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


def test_preview_is_forbidden_to_non_members(client, world):
    post = make_post(world)
    client.force_login(world.outsider)
    response = client.get(url("preview", world, post))
    assert response.status_code in (403, 404)


def test_preview_of_another_workspaces_post_is_404(client, world):
    from apps.blog.models import BlogSite
    from apps.members.models import WorkspaceMembership
    from apps.workspaces.models import Workspace

    other = Workspace.objects.create(organization=world.org, name="More Space")
    WorkspaceMembership.objects.create(user=world.owner, workspace=other, workspace_role="owner")
    BlogSite.objects.create(
        workspace=other,
        name="Other",
        kind=BlogSite.Kind.MORESPACE_STATIC,
        site_url="https://morespace.netlify.app",
        repo="o/r",
        workflow_file="w.yml",
    )
    post = make_post(world)
    client.force_login(world.owner)
    response = client.get(reverse("blog:preview", kwargs={"workspace_id": other.id, "post_id": post.id}))
    assert response.status_code == 404


def test_preview_renders_the_publishable_page_privately(client, world, image_asset):
    asset = image_asset()
    post = make_post(world, featured_image=asset, featured_image_alt="Towers")
    client.force_login(world.viewer)  # any member may look
    response = client.get(url("preview", world, post))
    assert response.status_code == 200
    assert response["X-Robots-Tag"] == "noindex, nofollow"
    assert response["Cache-Control"] == "private, no-store"
    assert "sandbox" in response["Content-Security-Policy"]
    body = response.content.decode()
    assert '<link rel="canonical" href="https://www.neopolisinfra.com/blog/flats-in-kokapet-2026">' in body
    assert 'href="https://www.neopolisinfra.com/blog/blog.css"' in body
    assert f'src="http://testserver{asset.file.url}"' in body  # the not-yet-published hero


def test_morespace_preview_points_at_the_live_site(client, world):
    post = make_post(world, site=world.morespace)
    client.force_login(world.owner)
    body = client.get(url("preview", world, post)).content.decode()
    assert '<base href="https://morespace.netlify.app/">' in body
    assert 'href="https://morespace.netlify.app/css/styles.css"' in body
    assert (
        "script-src https://morespace.netlify.app" in client.get(url("preview", world, post))["Content-Security-Policy"]
    )


# ---------------------------------------------------------------------------
# Pages and actions
# ---------------------------------------------------------------------------


def test_list_has_status_tabs_and_empty_states(client, world):
    client.force_login(world.editor)
    response = client.get(url("list", world))
    body = response.content.decode()
    assert response.status_code == 200
    for label in ("Drafts", "Awaiting approval", "Approved", "Published", "Failed"):
        assert label in body
    assert "No drafts" in body

    make_post(world)
    body = client.get(url("list", world)).content.decode()
    assert "Flats in Kokapet 2026" in body
    assert "No awaiting" not in body
    review = client.get(url("list", world) + "?tab=review").content.decode()
    assert "Nothing awaiting approval" in review


def test_create_edit_and_submit_from_the_dashboard(client, world):
    client.force_login(world.editor)
    assert client.get(url("create", world)).status_code == 200
    response = client.post(
        url("create", world),
        {
            "site": world.neopolis.pk,
            "title": "Narsingi price guide",
            "slug": "narsingi-price-guide",
            "excerpt": "What flats cost.",
            "body": "## Prices\n\nText.",
            "featured_image": "",
            "featured_image_alt": "",
            "seo_title": "Narsingi prices 2026",
            "meta_description": "Narsingi flat prices.",
            "category": "Price Guide",
            "faq_text": "Q: Is Narsingi good?\nA: Yes.\n\nQ: Ready flats?\nA: Some.",
        },
    )
    post = BlogPost.objects.get(slug="narsingi-price-guide")
    assert response.status_code == 302 and response["Location"] == url("detail", world, post)
    assert post.faq == [{"q": "Is Narsingi good?", "a": "Yes."}, {"q": "Ready flats?", "a": "Some."}]
    assert post.author == world.editor and post.status == Status.DRAFT

    detail = client.get(url("detail", world, post)).content.decode()
    assert "Submit for approval" in detail and "Approve revision" not in detail

    client.post(url("submit", world, post))
    assert BlogPost.objects.get(pk=post.pk).status == Status.PENDING_REVIEW


def test_form_errors_are_announced(client, world):
    client.force_login(world.editor)
    response = client.post(
        url("create", world), {"site": world.neopolis.pk, "title": "", "slug": "Bad Slug", "body": "x"}
    )
    body = response.content.decode()
    assert response.status_code == 200
    assert 'role="alert"' in body
    assert not BlogPost.objects.exists()


def test_seo_limits_are_enforced(client, world):
    client.force_login(world.editor)
    response = client.post(
        url("create", world),
        {
            "site": world.neopolis.pk,
            "title": "T",
            "slug": "t",
            "body": "x",
            "seo_title": "x" * 61,
            "meta_description": "y" * 161,
        },
    )
    form = response.context["form"]
    assert "seo_title" in form.errors and "meta_description" in form.errors


def test_owner_approves_in_the_dashboard_but_a_client_cannot(client, world):
    post = make_post(world)
    from apps.blog import services

    services.submit_for_review(post, world.editor)

    client.force_login(world.client)
    assert client.post(url("approve", world, post)).status_code == 403
    assert BlogPost.objects.get(pk=post.pk).status == Status.PENDING_REVIEW

    client.force_login(world.editor)
    assert client.post(url("approve", world, post)).status_code == 403

    client.force_login(world.owner)
    response = client.post(url("approve", world, post))
    assert response.status_code == 302
    post = BlogPost.objects.get(pk=post.pk)
    assert post.status == Status.APPROVED and post.approved_by == world.owner


def test_api_path_cannot_reach_blog_approval(client, world):
    """Requests under /api/ are never the dashboard actor, whatever cookie they carry."""
    from apps.approvals.actor import channel_for_path

    assert channel_for_path(url("approve", world, make_post(world))) == "dashboard"
    assert channel_for_path("/api/v1/blog/approve") == "api"


@override_settings(BLOG_GITHUB_TOKEN="")
def test_publish_without_a_token_explains_and_leaves_the_post_approved(client, world):
    post = approved_post(world)
    client.force_login(world.owner)
    detail = client.get(url("detail", world, post)).content.decode()
    assert "Publish to Neopolis Infra website" in detail
    assert "BLOG_GITHUB_TOKEN" in detail

    response = client.post(url("publish", world, post), follow=True)
    assert "Publishing needs BLOG_GITHUB_TOKEN on the SM Manager service" in response.content.decode()
    assert BlogPost.objects.get(pk=post.pk).status == Status.APPROVED


@override_settings(BLOG_GITHUB_TOKEN="github_pat_test")
def test_publish_from_the_dashboard_claims_the_post(client, world):
    post = approved_post(world)
    client.force_login(world.owner)
    client.post(url("publish", world, post))
    post = BlogPost.objects.get(pk=post.pk)
    assert post.status == Status.PUBLISHING
    status_panel = client.get(url("status", world, post)).content.decode()
    assert 'hx-trigger="every 10s"' in status_panel


def test_editing_an_approved_post_warns_and_withdraws(client, world):
    post = approved_post(world)
    client.force_login(world.editor)
    form_page = client.get(url("edit", world, post)).content.decode()
    assert "withdraws the approval" in form_page
    data = {
        "site": world.neopolis.pk,
        "title": post.title,
        "slug": post.slug,
        "excerpt": post.excerpt,
        "body": post.body + "\n\nNew paragraph.",
        "featured_image": "",
        "featured_image_alt": "",
        "seo_title": "",
        "meta_description": "",
        "category": post.category,
        "faq_text": "Q: Is Kokapet a good investment?\nA: For most buyers, yes.",
    }
    client.post(url("edit", world, post), data)
    post = BlogPost.objects.get(pk=post.pk)
    assert post.status == Status.PENDING_REVIEW and post.revision == 2


def test_viewer_cannot_create(client, world):
    client.force_login(world.viewer)
    assert client.get(url("create", world)).status_code == 403


def test_social_drafts_button_creates_a_composer_draft(client, world):
    post = approved_post(world)
    client.force_login(world.editor)
    response = client.post(url("social_drafts", world, post))
    assert response.status_code == 302
    assert "/compose/" in response["Location"]


@pytest.mark.parametrize("status", [s for s, _label in Status.choices])
def test_detail_and_list_render_in_every_status(client, world, status):
    post = approved_post(world)
    BlogPost.objects.filter(pk=post.pk).update(
        status=status,
        last_error="GitHub returned 500" if status == Status.FAILED else "",
        commit_sha="b" * 40 if status in (Status.PUBLISHING, Status.PUBLISHED, Status.FAILED) else "",
        deploy_run_url="https://github.com/o/r/actions/runs/1" if status == Status.PUBLISHED else "",
        published_url="https://www.neopolisinfra.com/blog/flats-in-kokapet-2026" if status == Status.PUBLISHED else "",
    )
    client.force_login(world.owner)
    detail = client.get(url("detail", world, post))
    assert detail.status_code == 200
    body = detail.content.decode()
    assert "History" in body and "Approval" in body
    if status == Status.FAILED:
        assert 'role="alert"' in body and "GitHub returned 500" in body and "Retry publish" in body
    if status == Status.PUBLISHING:
        assert 'hx-trigger="every 10s"' in body and "Edit</a>" not in body
    if status == Status.PUBLISHED:
        assert "Create social drafts" in body and "Live at" in body
    tab = {"draft": "drafts", "changes_requested": "drafts", "pending_review": "review", "approved": "approved"}
    tab.update({"publishing": "approved", "published": "published", "failed": "failed"})
    listing = client.get(url("list", world) + f"?tab={tab[status]}").content.decode()
    assert post.title in listing


def test_edit_page_of_a_published_post_locks_the_address(client, world):
    post = approved_post(world)
    BlogPost.objects.filter(pk=post.pk).update(status=Status.PUBLISHED, published_card={"slug": post.slug})
    client.force_login(world.editor)
    body = client.get(url("edit", world, post)).content.decode()
    assert "its address is fixed" in body
    assert 'name="slug"' in body and "disabled" in body


def test_form_labels_and_descriptions_point_at_real_elements(client, world, image_asset):
    import re

    image_asset()
    client.force_login(world.editor)
    html = client.get(url("create", world)).content.decode()
    form = html[html.find('<form method="post" x-data') :]
    form = form[: form.find("</form>")]
    ids = set(re.findall(r'\sid="([^"]+)"', form))
    assert set(re.findall(r'\sfor="([^"]+)"', form)) <= ids
    described = {ref for refs in re.findall(r'aria-describedby="([^"]+)"', form) for ref in refs.split()}
    assert described <= ids | {"featured-image-help"} and "featured-image-help" in html
    # Every picker option is a real, keyboard-reachable radio button.
    assert form.count('type="radio" name="featured_image"') == 2
    assert 'x-text="seo.length' in form and 'x-text="meta.length' in form


@pytest.mark.parametrize("name", ["list", "create"])
def test_pages_need_login(client, world, name):
    response = client.get(url(name, world))
    assert response.status_code == 302
