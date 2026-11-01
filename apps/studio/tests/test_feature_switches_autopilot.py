"""The ``blog`` switch inside the autopilot form (spec D6, R6).

With blog off, the form neither shows nor saves the blog fields: a save from the page keeps the
stored article quota and website exactly as they were, and never trips over them. With blog on,
the fields are back and validated as before. The planner reads the stored values either way, so
articles already planned keep coming (nothing here touches it).
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.blog.models import BlogSite
from apps.studio.forms_agency import AgencySettingsForm
from apps.studio.models import AgencySettings

BLOG_FIELDS = ("blog_posts_per_month", "blog_site")


def _site(world, **fields):
    return BlogSite.objects.create(
        workspace=world.workspace,
        name="Neopolis website",
        kind=BlogSite.Kind.NEOPOLIS_STATIC,
        site_url="https://www.example.com",
        repo="example/site",
        workflow_file="publish.yml",
        **fields,
    )


def _switch(world, **features):
    row, _ = AgencySettings.objects.get_or_create(workspace=world.workspace)
    row.features = {**(row.features or {}), **features}
    row.save(update_fields=["features"])
    return row


def _page_form(world, **overrides):
    """What the page posts when the blog fields are not on it."""
    data = {
        "autopilot_enabled": "on",
        "posts_per_week": "4",
        "accounts": [str(world.linkedin.pk)],
        "pillars": "Explainers",
        "plan_weekday": "4",
        "plan_hour": "16",
        "monthly_budget_usd": "120",
        "lead": str(world.manager.pk),
    }
    data.update(overrides)
    return data


def _autopilot(world):
    return reverse("studio:autopilot", kwargs={"workspace_id": world.workspace.id})


def _settings_tab(world):
    return reverse("settings:index", kwargs={"workspace_id": world.workspace.id}) + "?tab=autopilot"


# --- the form --------------------------------------------------------------------------------


@pytest.mark.django_db
def test_blog_off_the_form_has_no_blog_fields(world):
    form = AgencySettingsForm(instance=AgencySettings(workspace=world.workspace), workspace=world.workspace)

    for name in BLOG_FIELDS:
        assert name not in form.fields
    assert form.shows_blog is False


@pytest.mark.django_db
def test_blog_on_the_form_keeps_its_blog_fields(world):
    _site(world)  # an enabled website turns blog on by default

    form = AgencySettingsForm(instance=AgencySettings(workspace=world.workspace), workspace=world.workspace)

    for name in BLOG_FIELDS:
        assert name in form.fields
    assert form.shows_blog is True


@pytest.mark.django_db
def test_an_explicit_switch_wins_over_the_website_default(world):
    _site(world)
    _switch(world, blog=False)

    form = AgencySettingsForm(instance=AgencySettings(workspace=world.workspace), workspace=world.workspace)

    assert "blog_posts_per_month" not in form.fields


# --- the page and the Settings tab -----------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("url", [_autopilot, _settings_tab], ids=["autopilot page", "settings tab"])
def test_blog_off_the_page_hides_the_blog_fields(client, world, url):
    client.force_login(world.owner)

    response = client.get(url(world))

    assert response.status_code == 200
    html = response.content.decode()
    assert 'name="posts_per_week"' in html
    assert 'name="blog_posts_per_month"' not in html
    assert 'name="blog_site"' not in html


@pytest.mark.django_db
@pytest.mark.parametrize("url", [_autopilot, _settings_tab], ids=["autopilot page", "settings tab"])
def test_blog_on_the_page_shows_the_blog_fields(client, world, url):
    _site(world)
    client.force_login(world.owner)

    html = client.get(url(world)).content.decode()

    assert 'name="blog_posts_per_month"' in html
    assert 'name="blog_site"' in html


# --- saving ------------------------------------------------------------------------------------


@pytest.mark.django_db
def test_blog_off_a_save_keeps_the_stored_quota_and_website(client, world):
    site = _site(world)
    row = _switch(world, blog=False)
    row.blog_posts_per_month = 3
    row.blog_site = site
    row.save(update_fields=["blog_posts_per_month", "blog_site"])
    client.force_login(world.owner)

    response = client.post(_autopilot(world), _page_form(world, posts_per_week="6"))

    assert response.status_code == 302
    row.refresh_from_db()
    assert row.posts_per_week == 6  # the save happened
    assert row.blog_posts_per_month == 3 and row.blog_site == site  # and kept the hidden values


@pytest.mark.django_db
def test_blog_off_a_stored_quota_without_a_website_never_blocks_a_save(client, world):
    # A quota left behind after its website went away: hidden, so it must not reject the save.
    row = _switch(world, blog=False)
    row.blog_posts_per_month = 2
    row.save(update_fields=["blog_posts_per_month"])
    client.force_login(world.owner)

    response = client.post(_autopilot(world), _page_form(world))

    assert response.status_code == 302
    row.refresh_from_db()
    assert row.blog_posts_per_month == 2 and row.blog_site is None


@pytest.mark.django_db
def test_blog_on_the_page_saves_the_quota_and_still_wants_a_website(client, world):
    site = _site(world)
    client.force_login(world.owner)

    refused = client.post(_autopilot(world), _page_form(world, blog_posts_per_month="2", blog_site=""))
    assert refused.status_code == 400 and "Choose the website" in refused.content.decode()

    saved = client.post(_autopilot(world), _page_form(world, blog_posts_per_month="2", blog_site=str(site.pk)))
    assert saved.status_code == 302
    row = AgencySettings.objects.get(workspace=world.workspace)
    assert row.blog_posts_per_month == 2 and row.blog_site == site
