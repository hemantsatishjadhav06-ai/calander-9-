"""Root routing: public landing for anonymous, dashboard for authenticated."""

import pytest
from django.test import Client, override_settings


@pytest.mark.django_db
def test_landing_is_public_with_signup_cta():
    # Test settings open sign-up, so the CTA creates an account.
    resp = Client().get("/")
    assert resp.status_code == 200
    assert b"mk-hero" in resp.content
    assert b'href="/accounts/signup/"' in resp.content
    assert b'href="/accounts/login/"' in resp.content


@pytest.mark.django_db
@override_settings(SIGNUP_MODE="invite_only")
def test_landing_with_signup_closed_asks_for_an_invite():
    resp = Client().get("/")
    assert resp.status_code == 200
    assert b"mk-hero" in resp.content
    assert b'href="/request-invite/"' in resp.content
    assert b'href="/accounts/signup/"' not in resp.content
    assert b'href="/accounts/login/"' in resp.content


@pytest.mark.django_db
def test_authenticated_root_is_not_the_landing_page(user):
    c = Client()
    c.force_login(user)
    resp = c.get("/")
    # Authenticated users get the dashboard routing, never the marketing page.
    assert b"mk-hero" not in resp.content
