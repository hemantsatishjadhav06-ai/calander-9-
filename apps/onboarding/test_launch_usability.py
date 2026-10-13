from datetime import timedelta
from smtplib import SMTPException
from unittest.mock import MagicMock, patch

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.social_accounts.models import SocialAccount
from providers.types import AccountProfile

from .models import ConnectionLink, ConnectionLinkUsage


@pytest.mark.django_db
@pytest.mark.parametrize("signed_in", [False, True])
def test_public_connection_flow_is_visible_to_signed_in_visitors(client, user, signed_in):
    link = ConnectionLink.objects.create(
        workspace=user.workspace_memberships.first().workspace, expires_at=timezone.now() + timedelta(days=1)
    )
    if signed_in:
        client.force_login(user)
    response = client.get(reverse("onboarding:connection_page", args=[link.token]))
    assert response.status_code == 200
    assert "Connect your social accounts" in response.content.decode()
    response = client.post(reverse("onboarding:connection_done", args=[link.token]))
    assert response.status_code == 200
    assert "All done!" in response.content.decode()
    assert "No accounts have been connected" in response.content.decode()
    link.revoked_at = timezone.now()
    link.save(update_fields=["revoked_at"])
    response = client.get(reverse("onboarding:connection_page", args=[link.token]))
    assert "This link has been revoked" in response.content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize("email", ["not-an-email", "person@example.com\nBcc: other@example.com"])
def test_connection_email_rejects_invalid_addresses(client, user, email):
    client.force_login(user)
    workspace = user.workspace_memberships.first().workspace
    link = ConnectionLink.objects.create(workspace=workspace, expires_at=timezone.now() + timedelta(days=1))
    with patch("apps.onboarding.views.EmailMultiAlternatives.send") as send:
        response = client.post(
            reverse("onboarding:send_link_email", args=[workspace.id, link.id]), {"email": email}, follow=True
        )
    assert response.status_code == 200
    assert "Enter a valid email address." in response.content.decode()
    send.assert_not_called()


@pytest.mark.django_db
def test_connection_email_delivery_failure_is_actionable(client, user):
    client.force_login(user)
    workspace = user.workspace_memberships.first().workspace
    link = ConnectionLink.objects.create(workspace=workspace, expires_at=timezone.now() + timedelta(days=1))
    with patch("apps.onboarding.views.EmailMultiAlternatives.send", side_effect=SMTPException("SMTP unavailable")):
        response = client.post(
            reverse("onboarding:send_link_email", args=[workspace.id, link.id]),
            {"email": "client@example.com"},
            follow=True,
        )
    assert response.status_code == 200
    assert "We could not send that link right now." in response.content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url_name", ["onboarding:connection_bluesky", "onboarding:connection_mastodon", "onboarding:connection_devto"]
)
def test_public_connections_are_rate_limited_before_contacting_provider(client, user, url_name):
    workspace = user.workspace_memberships.first().workspace
    link = ConnectionLink.objects.create(workspace=workspace, expires_at=timezone.now() + timedelta(days=1))
    with (
        patch("apps.onboarding.views._check_rate_limit", return_value=False),
        patch("apps.onboarding.views._get_provider_for_platform") as provider,
    ):
        response = client.post(reverse(url_name, args=[link.token]))
    assert response.status_code == 429
    provider.assert_not_called()


@pytest.mark.django_db
def test_client_connects_devto_with_their_own_api_key(client, user):
    workspace = user.workspace_memberships.first().workspace
    link = ConnectionLink.objects.create(workspace=workspace, expires_at=timezone.now() + timedelta(days=1))
    provider = MagicMock()
    provider.get_profile.return_value = AccountProfile(platform_id="devto-1", name="Client", handle="client")
    with patch("apps.onboarding.views._get_provider_for_platform", return_value=provider):
        response = client.post(reverse("onboarding:connection_devto", args=[link.token]), {"api_key": "client-key"})
    assert response.status_code == 302
    provider.get_profile.assert_called_once_with("client-key")
    provider.get_auth_url.assert_not_called()
    account = SocialAccount.objects.get(workspace=workspace, platform="devto")
    assert account.oauth_access_token == "client-key"
    assert ConnectionLinkUsage.objects.filter(connection_link=link, social_account=account).exists()
    assert "connection_link_error" not in client.session


@pytest.mark.django_db
@pytest.mark.parametrize("api_key", ["", "invalid-key"])
def test_devto_connection_errors_are_shown_without_creating_accounts(client, user, api_key):
    workspace = user.workspace_memberships.first().workspace
    link = ConnectionLink.objects.create(workspace=workspace, expires_at=timezone.now() + timedelta(days=1))
    provider = MagicMock()
    provider.get_profile.side_effect = ValueError("Invalid key")
    with patch("apps.onboarding.views._get_provider_for_platform", return_value=provider):
        response = client.post(reverse("onboarding:connection_devto", args=[link.token]), {"api_key": api_key})
    assert response.status_code == 302
    assert "API key" in client.session["connection_link_error"]
    assert not ConnectionLinkUsage.objects.filter(connection_link=link).exists()


@pytest.mark.django_db
def test_devto_connection_is_not_routed_into_oauth(client, user):
    workspace = user.workspace_memberships.first().workspace
    link = ConnectionLink.objects.create(workspace=workspace, expires_at=timezone.now() + timedelta(days=1))
    page = client.get(reverse("onboarding:connection_page", args=[link.token]))
    assert reverse("onboarding:connection_devto", args=[link.token]) in page.content.decode()
    with patch("apps.onboarding.views._get_provider_for_platform") as provider:
        response = client.post(reverse("onboarding:connection_oauth_start", args=[link.token]), {"platform": "devto"})
    assert response.status_code == 302
    provider.assert_not_called()
