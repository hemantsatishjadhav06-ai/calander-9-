"""Smoke tests for the public marketing pages.

The pages are static templates, so these tests check the routing contract
rather than the copy: every page renders for an anonymous visitor, the site
root still behaves as the dashboard for signed-in users, and the navigation
points at the real sign-in and sign-up URLs.
"""

import pytest
from django.urls import reverse

from apps.marketing.views import PLATFORMS

PUBLIC_PAGES = [
    "marketing:home",
    "marketing:features",
    "marketing:how_it_works",
    "marketing:platforms",
    "marketing:developers",
    "marketing:get_started",
]


def _template_names(response):
    return [t.name for t in response.templates if t.name]


@pytest.mark.django_db
@pytest.mark.parametrize("url_name", PUBLIC_PAGES)
def test_public_pages_render_for_anonymous_visitors(client, url_name):
    response = client.get(reverse(url_name))

    assert response.status_code == 200
    assert "marketing/base.html" in _template_names(response)
    content = response.content.decode()
    assert "SM Bean" in content
    assert reverse("account_login") in content
    assert reverse("account_signup") in content


@pytest.mark.django_db
@pytest.mark.parametrize("url_name", PUBLIC_PAGES)
def test_public_pages_are_read_only(client, url_name):
    assert client.post(reverse(url_name)).status_code == 405


def test_site_root_keeps_the_dashboard_url_name():
    """``redirect("dashboard")`` across the app must still land on "/"."""
    assert reverse("marketing:home") == "/"
    assert reverse("dashboard") == "/"


@pytest.mark.django_db
def test_signed_in_user_gets_the_dashboard_not_the_landing_page(client, user):
    """A signed-in visit to "/" behaves exactly as before the marketing pages.

    A fresh user is provisioned a workspace on creation, so the dashboard
    forwards them to that workspace's calendar rather than rendering a page.
    """
    client.force_login(user)

    response = client.get("/")

    assert response.status_code == 302
    assert "/calendar/" in response["Location"]
    assert "marketing/home.html" not in _template_names(response)


@pytest.mark.django_db
def test_platform_matrix_lists_every_connector(client):
    response = client.get(reverse("marketing:platforms"))
    content = response.content.decode()

    for platform in PLATFORMS:
        assert platform["name"] in content


@pytest.mark.django_db
def test_pages_carry_canonical_and_description_metadata(client, settings):
    settings.APP_URL = "https://studio.example.com/"

    response = client.get(reverse("marketing:features"))
    content = response.content.decode()

    assert '<link rel="canonical" href="https://studio.example.com/features/">' in content
    assert '<meta name="description" content="' in content
    assert 'property="og:image" content="https://studio.example.com/static/' in content
