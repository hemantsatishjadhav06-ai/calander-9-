"""Smoke tests for the public marketing pages.

The pages are static templates, so these tests check the routing contract
rather than the copy: every page renders for an anonymous visitor, the site
root still behaves as the dashboard for signed-in users, and the navigation
points at the real sign-in and sign-up URLs.

Three pages are linked (Home, How it works, Request invite). Features,
Platforms, Developers and Get started keep rendering for old links but are
linked from nowhere on the three and ask search engines not to index them.
"""

import re

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.marketing.views import PLATFORMS, UPSTREAM_URL

PUBLIC_PAGES = [
    "marketing:home",
    "marketing:features",
    "marketing:how_it_works",
    "marketing:platforms",
    "marketing:developers",
    "marketing:get_started",
]

LINKED_PAGES = ["marketing:home", "marketing:how_it_works", "marketing:request_invite"]
HIDDEN_PAGES = ["marketing:features", "marketing:platforms", "marketing:developers", "marketing:get_started"]
NOINDEX = '<meta name="robots" content="noindex">'


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
    """A newly provisioned owner starts their workspace's guided post workflow."""
    workspace = user.workspace_memberships.get().workspace
    client.force_login(user)

    response = client.get("/")

    assert response.status_code == 302
    assert response["Location"] == reverse("studio:index", kwargs={"workspace_id": workspace.pk})
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


@pytest.mark.django_db
def test_source_code_links_point_at_this_deployments_repository(client, settings):
    # AGPL-3.0 §13: users must be offered the source of the version they use, not the upstream's.
    settings.SOURCE_URL = "https://example.com/our-fork"
    for url_name in ("marketing:home", "marketing:get_started"):
        html = client.get(reverse(url_name)).content.decode()
        assert 'href="https://example.com/our-fork" rel="noopener">Source code</a>' in html


def _hrefs(html, tag):
    """Every href inside the page's one ``<tag ...>...</tag>`` element."""
    block = re.search(rf"<{tag}\b.*?</{tag}>", html, re.S)
    assert block, tag
    return set(re.findall(r'href="([^"]*)"', block.group(0)))


def _allowed_chrome_links(settings):
    return {
        reverse("marketing:home"),
        reverse("marketing:how_it_works"),
        reverse("marketing:request_invite"),
        reverse("account_login"),
        settings.LEGAL_TERMS_URL,
        settings.LEGAL_PRIVACY_URL,
        reverse("support"),
        settings.SOURCE_URL,
        UPSTREAM_URL,
    }


@pytest.mark.django_db
@pytest.mark.parametrize("url_name", LINKED_PAGES + HIDDEN_PAGES)
@override_settings(SIGNUP_MODE="invite_only")
def test_header_and_footer_link_only_the_three_pages_sign_in_and_legal(client, settings, url_name):
    html = client.get(reverse(url_name)).content.decode()

    links = _hrefs(html, "header") | _hrefs(html, "footer")

    assert links <= _allowed_chrome_links(settings), links - _allowed_chrome_links(settings)
    for required in ("/", "/how-it-works/", "/request-invite/", "/accounts/login/", "/terms/", "/privacy/"):
        assert required in links, required


@pytest.mark.django_db
@override_settings(SIGNUP_MODE="open")
def test_with_signup_open_the_chrome_may_also_offer_the_account(client, settings):
    html = client.get(reverse("marketing:home")).content.decode()

    links = _hrefs(html, "header") | _hrefs(html, "footer")

    assert links <= _allowed_chrome_links(settings) | {reverse("account_signup")}
    assert reverse("account_signup") in links


@pytest.mark.django_db
@pytest.mark.parametrize("url_name", LINKED_PAGES)
@pytest.mark.parametrize("signup_mode", ["open", "invite_only"])
def test_the_linked_pages_never_link_the_hidden_ones(client, settings, url_name, signup_mode):
    settings.SIGNUP_MODE = signup_mode
    html = client.get(reverse(url_name)).content.decode()

    for hidden in HIDDEN_PAGES + ["pricing"]:
        assert f'href="{reverse(hidden)}' not in html, hidden


@pytest.mark.django_db
@pytest.mark.parametrize("url_name", HIDDEN_PAGES)
def test_hidden_pages_still_render_and_ask_not_to_be_indexed(client, url_name):
    response = client.get(reverse(url_name))

    assert response.status_code == 200
    assert NOINDEX in response.content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize("url_name", LINKED_PAGES)
def test_the_linked_pages_may_be_indexed(client, url_name):
    response = client.get(reverse(url_name))

    assert response.status_code == 200
    assert 'name="robots"' not in response.content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize("url_name", PUBLIC_PAGES)
@override_settings(SIGNUP_MODE="invite_only")
def test_with_signup_closed_every_cta_asks_for_an_invite(client, url_name):
    html = client.get(reverse(url_name)).content.decode()

    assert f'href="{reverse("account_signup")}"' not in html
    assert f'href="{reverse("marketing:request_invite")}"' in html


@pytest.mark.django_db
@pytest.mark.parametrize("url_name", LINKED_PAGES)
def test_the_linked_pages_name_no_model_or_vendor(client, url_name):
    html = client.get(reverse(url_name)).content.decode()

    for name in ("Claude", "Anthropic", "OpenRouter", "OpenAI", "GPT"):
        assert name not in html, name
