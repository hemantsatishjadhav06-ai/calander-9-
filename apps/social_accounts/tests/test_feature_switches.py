"""The ``extra_providers`` switch on the connect screen (spec D6, R6).

Off (the default), Bluesky, Mastodon, DEV.to, Threads and TikTok are not offered for new
connections: the connect screen leaves them out and their connect forms say so in words. A
workspace that already has an account on one of them keeps reconnecting it (Bluesky, Mastodon and
DEV.to reconnect through the same form), the OAuth callback stays open, and connected accounts
keep appearing in the composer. On, everything is offered as before.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.social_accounts.availability import EXTRA_PROVIDERS
from apps.social_accounts.models import SocialAccount
from apps.studio.models import AgencySettings
from providers.types import AccountProfile, OAuthTokens

FORMS = {
    "bluesky": "social_accounts:connect_bluesky",
    "mastodon": "social_accounts:connect_mastodon",
    "devto": "social_accounts:connect_devto",
}
#: Credentials for the two OAuth providers in the set, so the screen would offer them if allowed.
OAUTH_CREDENTIALS = {
    "threads": {"app_id": "TH_ID", "app_secret": "TH_SECRET"},
    "tiktok": {"client_key": "TT_KEY", "client_secret": "TT_SECRET"},
}


@pytest.fixture
def workspace(db, organization):
    from apps.workspaces.models import Workspace

    return Workspace.objects.create(name="Test WS", organization=organization)


@pytest.fixture
def owner(db, user, organization, workspace):
    from apps.members.models import OrgMembership, WorkspaceMembership

    OrgMembership.objects.create(user=user, organization=organization, org_role="owner")
    WorkspaceMembership.objects.create(user=user, workspace=workspace, workspace_role="owner")
    return user


@pytest.fixture
def signed_in(client, owner):
    client.force_login(owner)
    return client


def _switch(workspace, on: bool):
    AgencySettings.objects.update_or_create(workspace=workspace, defaults={"features": {"extra_providers": on}})


def _account(workspace, platform, **fields):
    return SocialAccount.objects.create(
        workspace=workspace,
        platform=platform,
        account_platform_id=f"{platform}-1",
        account_name=f"Our {platform}",
        **fields,
    )


def _connect(workspace):
    return reverse("social_accounts:connect", kwargs={"workspace_id": workspace.id})


def _offered(response) -> set[str]:
    return {value for value, _label in response.context["platform_choices"]}


def test_the_switch_covers_exactly_the_five_providers():
    assert {"bluesky", "mastodon", "devto", "threads", "tiktok"} == EXTRA_PROVIDERS


# --- the connect screen ------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(PLATFORM_CREDENTIALS_FROM_ENV=OAUTH_CREDENTIALS)
def test_off_the_connect_screen_offers_none_of_them(signed_in, workspace):
    response = signed_in.get(_connect(workspace))

    assert response.status_code == 200
    assert not _offered(response) & EXTRA_PROVIDERS
    assert {"facebook", "linkedin_company", "x"} <= _offered(response)
    html = response.content.decode()
    for platform in EXTRA_PROVIDERS:
        assert f'data-testid="connect-platform-{platform}"' not in html


@pytest.mark.django_db
@override_settings(PLATFORM_CREDENTIALS_FROM_ENV=OAUTH_CREDENTIALS)
def test_on_the_connect_screen_offers_all_of_them(signed_in, workspace):
    _switch(workspace, True)

    response = signed_in.get(_connect(workspace))

    assert _offered(response) >= EXTRA_PROVIDERS
    html = response.content.decode()
    for platform in EXTRA_PROVIDERS:
        assert f'data-testid="connect-platform-{platform}"' in html


@pytest.mark.django_db
@override_settings(PLATFORM_CREDENTIALS_FROM_ENV=OAUTH_CREDENTIALS)
@pytest.mark.parametrize("platform", sorted(EXTRA_PROVIDERS))
def test_off_a_new_connection_is_refused_without_contacting_the_platform(signed_in, workspace, platform):
    with patch("apps.social_accounts.views._get_provider_for_platform") as provider:
        response = signed_in.post(_connect(workspace), {"platform": platform})

    assert response.status_code == 302
    assert response.url == _connect(workspace)  # back to the screen, not on to a form or a platform
    provider.assert_not_called()


@pytest.mark.django_db
@override_settings(PLATFORM_CREDENTIALS_FROM_ENV=OAUTH_CREDENTIALS)
def test_off_a_platform_the_workspace_already_has_stays_on_the_screen(signed_in, workspace):
    _account(workspace, "bluesky")

    response = signed_in.get(_connect(workspace))

    assert "bluesky" in _offered(response)
    assert not _offered(response) & (EXTRA_PROVIDERS - {"bluesky"})


@pytest.mark.django_db
@override_settings(PLATFORM_CREDENTIALS_FROM_ENV=OAUTH_CREDENTIALS)
def test_on_threads_starts_its_oauth_as_before(signed_in, workspace):
    _switch(workspace, True)

    response = signed_in.post(_connect(workspace), {"platform": "threads"})

    assert response.status_code == 302
    assert response.url.startswith("https://www.threads.com/oauth/authorize?")


# --- the Bluesky, Mastodon and DEV.to forms ----------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("platform", sorted(FORMS))
def test_off_the_form_says_so_in_words_and_offers_no_form(signed_in, workspace, platform):
    url = reverse(FORMS[platform], kwargs={"workspace_id": workspace.id})

    response = signed_in.get(url)

    assert response.status_code == 200  # the page still answers
    html = response.content.decode()
    assert "is not available for new connections in this workspace" in html
    assert f'action="{url}"' not in html
    assert 'data-testid="connect-unavailable"' in html


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("platform", "data"),
    [
        ("bluesky", {"handle": "us.bsky.social", "app_password": "xxxx-xxxx"}),
        ("mastodon", {"instance_url": "mastodon.social"}),
        ("devto", {"api_key": "key"}),
    ],
)
def test_off_a_submitted_form_is_refused_before_the_platform(signed_in, workspace, platform, data):
    url = reverse(FORMS[platform], kwargs={"workspace_id": workspace.id})

    with patch("apps.social_accounts.views._get_provider_for_platform") as provider:
        response = signed_in.post(url, data)

    assert response.status_code == 403
    assert "is not available for new connections in this workspace" in response.content.decode()
    provider.assert_not_called()
    assert not SocialAccount.objects.filter(workspace=workspace, platform=platform).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("platform", sorted(FORMS))
def test_on_the_form_is_shown(signed_in, workspace, platform):
    _switch(workspace, True)
    url = reverse(FORMS[platform], kwargs={"workspace_id": workspace.id})

    html = signed_in.get(url).content.decode()

    assert f'action="{url}"' in html
    assert 'data-testid="connect-unavailable"' not in html


@pytest.mark.django_db
def test_another_workspaces_account_does_not_unlock_the_form(signed_in, workspace, organization):
    from apps.workspaces.models import Workspace

    other = Workspace.objects.create(name="Other WS", organization=organization)
    _account(other, "bluesky")
    url = reverse(FORMS["bluesky"], kwargs={"workspace_id": workspace.id})

    assert 'data-testid="connect-unavailable"' in signed_in.get(url).content.decode()


# --- reconnect, callbacks and existing accounts ------------------------------------------------


@pytest.mark.django_db
def test_off_bluesky_reconnects_through_its_form(signed_in, workspace):
    account = _account(workspace, "bluesky", connection_status=SocialAccount.ConnectionStatus.ERROR)
    reconnect = reverse("social_accounts:reconnect", kwargs={"workspace_id": workspace.id, "account_id": account.id})
    form = reverse(FORMS["bluesky"], kwargs={"workspace_id": workspace.id})

    response = signed_in.post(reconnect)
    assert response.status_code == 302 and response.url == form

    assert f'action="{form}"' in signed_in.get(form).content.decode()

    provider = MagicMock()
    provider.create_session.return_value = OAuthTokens(access_token="new", refresh_token="r", expires_in=3600)
    provider.get_profile.return_value = AccountProfile(platform_id="bluesky-1", name="Our bluesky", handle="us")
    provider.pds_url = "https://bsky.social"
    with patch("apps.social_accounts.views._get_provider_for_platform", return_value=provider):
        saved = signed_in.post(form, {"handle": "us.bsky.social", "app_password": "xxxx-xxxx"})

    assert saved.status_code == 302
    account.refresh_from_db()
    assert account.connection_status == SocialAccount.ConnectionStatus.CONNECTED


@pytest.mark.django_db
def test_off_tiktok_reconnects_through_its_oauth(signed_in, workspace):
    account = _account(workspace, "tiktok")
    reconnect = reverse("social_accounts:reconnect", kwargs={"workspace_id": workspace.id, "account_id": account.id})
    provider = MagicMock()
    provider.uses_pkce = True
    provider.get_auth_url.return_value = "https://www.tiktok.com/v2/auth/authorize/?ok=1"

    with patch("apps.social_accounts.views._get_provider_for_platform", return_value=provider):
        response = signed_in.post(reconnect)

    assert response.status_code == 302
    assert response.url == "https://www.tiktok.com/v2/auth/authorize/?ok=1"


@pytest.mark.django_db
@pytest.mark.parametrize("slug", ["threads", "social1", "mastodon"])
def test_off_the_oauth_callback_stays_open(signed_in, workspace, slug):
    url = reverse("social_accounts:oauth_callback", kwargs={"platform": slug})

    response = signed_in.get(url, {"error": "access_denied"})

    assert response.status_code not in (403, 404)


@pytest.mark.django_db
def test_off_a_connected_account_still_appears_in_the_composer(signed_in, workspace):
    account = _account(
        workspace,
        "bluesky",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        oauth_access_token="token",
    )

    response = signed_in.get(reverse("composer:compose", kwargs={"workspace_id": workspace.id}))

    assert response.status_code == 200
    assert f'data-testid="compose-account-{account.id}"' in response.content.decode()
