"""Sign in with Google, from the button to the calendar.

Google itself is never called: the code-for-token exchange and the profile
lookup are the two network steps, and both are replaced. Everything else —
the login page, allauth's state check, auto-signup, the invite-only rule, the
terms page and the landing — is the real code.
"""

from unittest import mock
from urllib.parse import parse_qs, urlparse

import pytest
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from django.test import override_settings
from django.urls import reverse

from apps.accounts.models import OAuthConnection, User
from apps.members.models import OrgMembership, WorkspaceMembership

GOOGLE = {
    "SCOPE": ["profile", "email"],
    "AUTH_PARAMS": {"access_type": "online"},
    "VERIFIED_EMAIL": True,
}
GOOGLE_CONFIGURED = {
    "google": {**GOOGLE, "APP": {"client_id": "test-client.apps.googleusercontent.com", "secret": "s"}}
}
GOOGLE_NOT_CONFIGURED = {"google": GOOGLE}

LOGIN = "/accounts/login/"
GOOGLE_LOGIN = "/accounts/google/login/"
CALLBACK = "/accounts/google/login/callback/"


def _profile(email="ana@agency.com", sub="1122334455"):
    return {
        "sub": sub,
        "email": email,
        "email_verified": True,
        "name": "Ana Lima",
        "given_name": "Ana",
        "family_name": "Lima",
    }


def _google_returns(profile):
    """Replace the two calls allauth makes to Google after the redirect back."""

    def complete_login(self, request, app, token, **kwargs):
        return self.get_provider().sociallogin_from_response(request, profile)

    return (
        mock.patch.object(
            OAuth2Client,
            "get_access_token",
            return_value={"access_token": "test-access-token", "expires_in": 3599, "token_type": "Bearer"},
        ),
        mock.patch.object(GoogleOAuth2Adapter, "complete_login", autospec=True, side_effect=complete_login),
    )


def _sign_in_with_google(client, profile, *, start=LOGIN):
    """Press the button on ``start``, come back from Google, return the callback response."""
    page = client.get(start)
    assert page.status_code == 200
    action = _google_form_action(page.content.decode())
    to_google = client.post(action)
    assert to_google.status_code == 302
    state = parse_qs(urlparse(to_google["Location"]).query)["state"][0]
    exchange, login = _google_returns(profile)
    with exchange, login:
        return client.get(CALLBACK, {"code": "4/abc", "state": state})


def _google_form_action(html):
    marker = f'action="{GOOGLE_LOGIN}'
    start = html.index(marker) + len('action="')
    return html[start : html.index('"', start)].replace("&amp;", "&")


@override_settings(SOCIALACCOUNT_PROVIDERS=GOOGLE_NOT_CONFIGURED)
@pytest.mark.django_db
def test_no_google_button_until_the_credentials_are_set(client):
    for url in (LOGIN, "/accounts/signup/"):
        html = client.get(url).content.decode()
        assert "Sign in with Google" not in html and "Sign up with Google" not in html
        assert GOOGLE_LOGIN not in html


@override_settings(SOCIALACCOUNT_PROVIDERS=GOOGLE_CONFIGURED)
@pytest.mark.django_db
def test_the_buttons_send_people_to_google_with_this_sites_callback(client):
    assert "Sign in with Google" in client.get(LOGIN).content.decode()
    assert "Sign up with Google" in client.get("/accounts/signup/").content.decode()

    action = _google_form_action(client.get(LOGIN).content.decode())
    response = client.post(action)

    assert response.status_code == 302
    url = urlparse(response["Location"])
    assert url.netloc == "accounts.google.com"
    query = parse_qs(url.query)
    assert query["client_id"] == ["test-client.apps.googleusercontent.com"]
    assert query["redirect_uri"] == ["http://testserver" + CALLBACK]
    assert set(query["scope"][0].split()) == {"profile", "email"}
    assert query["response_type"] == ["code"]


@override_settings(SOCIALACCOUNT_PROVIDERS=GOOGLE_CONFIGURED)
@pytest.mark.django_db
def test_a_new_person_gets_an_account_accepts_the_terms_and_lands_on_the_calendar(client):
    response = _sign_in_with_google(client, _profile())

    user = User.objects.get(email="ana@agency.com")
    assert user.name == "Ana Lima"
    assert SocialAccount.objects.filter(user=user, provider="google", uid="1122334455").exists()
    assert OAuthConnection.objects.filter(user=user, provider_user_id="1122334455").exists()
    workspace = WorkspaceMembership.objects.get(user=user).workspace
    assert OrgMembership.objects.filter(user=user, org_role=OrgMembership.OrgRole.OWNER).exists()

    # Signed in, but the terms come first: Google users haven't seen them yet.
    assert response.status_code == 302
    page = client.get(response["Location"], follow=True)
    assert page.redirect_chain[-1][0] == reverse("accounts:accept_terms")
    assert user.tos_accepted_at is None

    accepted = client.post(reverse("accounts:accept_terms"), {"agree": "on"}, follow=True)
    assert accepted.status_code == 200
    assert accepted.redirect_chain[-1][0] == reverse("calendar:calendar", kwargs={"workspace_id": workspace.id})
    user.refresh_from_db()
    assert user.tos_accepted_at is not None


@override_settings(SOCIALACCOUNT_PROVIDERS=GOOGLE_CONFIGURED)
@pytest.mark.django_db
def test_the_page_someone_asked_for_survives_google_and_the_terms(client):
    target = reverse("accounts:settings")
    response = _sign_in_with_google(client, _profile(), start=f"{LOGIN}?next={target}")

    assert response["Location"] == target
    to_terms = client.get(target)
    assert to_terms["Location"] == f"{reverse('accounts:accept_terms')}?next=%2Faccounts%2Fsettings%2F"
    accepted = client.post(to_terms["Location"], {"agree": "on"})
    assert accepted["Location"] == target


@override_settings(SOCIALACCOUNT_PROVIDERS=GOOGLE_CONFIGURED)
@pytest.mark.django_db
def test_an_existing_account_with_the_same_address_signs_straight_in(client):
    from django.utils import timezone

    existing = User.objects.create_user(email="ana@agency.com", password="x-long-password-1")
    existing.tos_accepted_at = timezone.now()
    existing.save(update_fields=["tos_accepted_at"])
    workspace = WorkspaceMembership.objects.get(user=existing).workspace

    response = _sign_in_with_google(client, _profile())

    assert User.objects.filter(email="ana@agency.com").count() == 1
    assert SocialAccount.objects.filter(user=existing, provider="google").exists()
    landed = client.get(response["Location"], follow=True)
    assert landed.redirect_chain[-1][0] == reverse("calendar:calendar", kwargs={"workspace_id": workspace.id})


@override_settings(SOCIALACCOUNT_PROVIDERS=GOOGLE_CONFIGURED, SIGNUP_MODE="invite_only", SIGNUP_ALLOWLIST=[])
@pytest.mark.django_db
def test_invite_only_turns_away_a_stranger(client):
    response = _sign_in_with_google(client, _profile("stranger@gmail.com"))

    assert response.status_code == 200
    assert "invite-only" in response.content.decode()
    assert not User.objects.filter(email="stranger@gmail.com").exists()


@override_settings(
    SOCIALACCOUNT_PROVIDERS=GOOGLE_CONFIGURED, SIGNUP_MODE="invite_only", SIGNUP_ALLOWLIST=["@agency.com"]
)
@pytest.mark.django_db
def test_invite_only_lets_an_allowlisted_domain_in(client):
    _sign_in_with_google(client, _profile("ana@agency.com"))

    assert User.objects.filter(email="ana@agency.com").exists()


@override_settings(SOCIALACCOUNT_PROVIDERS=GOOGLE_CONFIGURED)
@pytest.mark.django_db
def test_cancelling_at_google_explains_and_offers_the_way_back(client):
    action = _google_form_action(client.get(LOGIN).content.decode())
    state = parse_qs(urlparse(client.post(action)["Location"]).query)["state"][0]

    page = client.get(CALLBACK, {"error": "access_denied", "state": state}, follow=True)

    html = page.content.decode()
    assert "Sign-in cancelled" in html
    assert f'href="{LOGIN}"' in html


@override_settings(SOCIALACCOUNT_PROVIDERS=GOOGLE_CONFIGURED)
@pytest.mark.django_db
def test_a_failed_sign_in_says_so_and_logs_why(client, caplog):
    action = _google_form_action(client.get(LOGIN).content.decode())
    state = parse_qs(urlparse(client.post(action)["Location"]).query)["state"][0]

    with mock.patch.object(OAuth2Client, "get_access_token", side_effect=_oauth_error("invalid_client")):
        page = client.get(CALLBACK, {"code": "4/abc", "state": state})

    assert page.status_code == 401
    html = page.content.decode()
    assert "Google sign-in didn&#x27;t finish" in html or "Google sign-in didn't finish" in html
    assert f'href="{LOGIN}"' in html
    assert "invalid_client" in caplog.text
    assert not User.objects.exists()


def _oauth_error(message):
    from allauth.socialaccount.providers.oauth2.client import OAuth2Error

    return OAuth2Error(message)


@pytest.mark.django_db
def test_the_terms_page_never_redirects_off_site(client):
    user = User.objects.create_user(email="ana@agency.com", password="x-long-password-1")
    client.force_login(user)

    response = client.post(f"{reverse('accounts:accept_terms')}?next=https://evil.example/", {"agree": "on"})

    assert response["Location"] == "/"


@pytest.mark.django_db
def test_the_terms_page_needs_a_signed_in_user(client):
    response = client.get(reverse("accounts:accept_terms"))

    assert response.status_code == 302
    assert response["Location"].startswith(LOGIN)
