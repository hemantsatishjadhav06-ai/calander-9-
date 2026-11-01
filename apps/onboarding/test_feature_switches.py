"""The ``extra_providers`` switch on a client's connection link page (spec D6, R6).

The link page is a second connect screen with no workspace in its URL, so it reads the switch for
the link's workspace. Off (the default), it offers neither Bluesky, Mastodon, DEV.to, Threads nor
TikTok, and their endpoints refuse a new connection in words without contacting the platform; a
platform the workspace already has stays available (that is how a client reconnects it), and one
already connected through this link still shows as connected. On, everything is offered as before.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.social_accounts.availability import EXTRA_PROVIDERS
from apps.social_accounts.models import SocialAccount
from apps.studio.models import AgencySettings
from providers.types import AccountProfile

from .models import ConnectionLink, ConnectionLinkUsage

OAUTH_CREDENTIALS = {
    "threads": {"app_id": "TH_ID", "app_secret": "TH_SECRET"},
    "tiktok": {"client_key": "TT_KEY", "client_secret": "TT_SECRET"},
}
FORM_POSTS = [
    ("onboarding:connection_bluesky", "bluesky", {"handle": "client.bsky.social", "app_password": "xxxx"}),
    ("onboarding:connection_mastodon", "mastodon", {"instance_url": "mastodon.social"}),
    ("onboarding:connection_devto", "devto", {"api_key": "client-key"}),
]


@pytest.fixture
def workspace(db, organization):
    from apps.workspaces.models import Workspace

    return Workspace.objects.create(name="Client WS", organization=organization)


@pytest.fixture
def link(workspace):
    return ConnectionLink.objects.create(workspace=workspace, expires_at=timezone.now() + timedelta(days=1))


def _switch(workspace, on: bool):
    AgencySettings.objects.update_or_create(workspace=workspace, defaults={"features": {"extra_providers": on}})


def _page(client, link):
    return client.get(reverse("onboarding:connection_page", args=[link.token]))


def _offered(response) -> set[str]:
    return {value for value, _label in response.context["platform_choices"]}


@pytest.mark.django_db
@override_settings(PLATFORM_CREDENTIALS_FROM_ENV=OAUTH_CREDENTIALS)
def test_off_the_link_page_offers_none_of_them(client, link):
    response = _page(client, link)

    assert response.status_code == 200
    assert not _offered(response) & EXTRA_PROVIDERS
    assert "x" in _offered(response) and "facebook" in _offered(response)
    html = response.content.decode()
    for name in ("connection_bluesky", "connection_mastodon", "connection_devto"):
        assert reverse(f"onboarding:{name}", args=[link.token]) not in html
    for platform in ("threads", "tiktok"):
        assert f'name="platform" value="{platform}"' not in html


@pytest.mark.django_db
@override_settings(PLATFORM_CREDENTIALS_FROM_ENV=OAUTH_CREDENTIALS)
def test_on_the_link_page_offers_all_of_them(client, link, workspace):
    _switch(workspace, True)

    response = _page(client, link)

    assert _offered(response) >= EXTRA_PROVIDERS
    html = response.content.decode()
    for name in ("connection_bluesky", "connection_mastodon", "connection_devto"):
        assert reverse(f"onboarding:{name}", args=[link.token]) in html
    for platform in ("threads", "tiktok"):
        assert f'name="platform" value="{platform}"' in html


@pytest.mark.django_db
def test_off_an_account_connected_through_the_link_still_shows_as_connected(client, link, workspace):
    account = SocialAccount.objects.create(workspace=workspace, platform="devto", account_platform_id="d-1")
    ConnectionLinkUsage.objects.create(connection_link=link, social_account=account)

    response = _page(client, link)

    assert "devto" in _offered(response)
    assert "devto" in response.context["connected_accounts"]


@pytest.mark.django_db
@pytest.mark.parametrize(("url_name", "platform", "data"), FORM_POSTS)
def test_off_a_new_connection_is_refused_in_words(client, link, url_name, platform, data):
    with patch("apps.onboarding.views._get_provider_for_platform") as provider:
        response = client.post(reverse(url_name, args=[link.token]), data)

    assert response.status_code == 302
    assert response.url == reverse("onboarding:connection_page", args=[link.token])
    assert "is not available for new connections" in client.session["connection_link_error"]
    provider.assert_not_called()
    assert not ConnectionLinkUsage.objects.filter(connection_link=link).exists()


@pytest.mark.django_db
@override_settings(PLATFORM_CREDENTIALS_FROM_ENV=OAUTH_CREDENTIALS)
@pytest.mark.parametrize("platform", ["threads", "tiktok"])
def test_off_a_new_oauth_connection_is_refused_in_words(client, link, platform):
    with patch("apps.onboarding.views._get_provider_for_platform") as provider:
        response = client.post(reverse("onboarding:connection_oauth_start", args=[link.token]), {"platform": platform})

    assert response.status_code == 302
    assert response.url == reverse("onboarding:connection_page", args=[link.token])
    assert "is not available for new connections" in client.session["connection_link_error"]
    provider.assert_not_called()


@pytest.mark.django_db
def test_off_a_platform_the_workspace_already_has_can_be_reconnected(client, link, workspace):
    SocialAccount.objects.create(workspace=workspace, platform="devto", account_platform_id="devto-1")
    assert "devto" in _offered(_page(client, link))
    provider = MagicMock()
    provider.get_profile.return_value = AccountProfile(platform_id="devto-1", name="Client", handle="client")

    with patch("apps.onboarding.views._get_provider_for_platform", return_value=provider):
        response = client.post(reverse("onboarding:connection_devto", args=[link.token]), {"api_key": "new-key"})

    assert response.status_code == 302
    provider.get_profile.assert_called_once_with("new-key")
    assert SocialAccount.objects.get(workspace=workspace, platform="devto").oauth_access_token == "new-key"
    assert "connection_link_error" not in client.session
