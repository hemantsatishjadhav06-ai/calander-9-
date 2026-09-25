"""Root routing: public landing for anonymous, dashboard for authenticated."""

import pytest
from django.test import Client


@pytest.mark.django_db
def test_landing_is_public_with_signup_cta():
    resp = Client().get("/")
    assert resp.status_code == 200
    assert b"Own your social stack" in resp.content
    assert b'href="/accounts/signup/"' in resp.content
    assert b'href="/accounts/login/"' in resp.content


@pytest.mark.django_db
def test_authenticated_root_is_not_the_landing_page(user):
    c = Client()
    c.force_login(user)
    resp = c.get("/")
    # Authenticated users get the dashboard routing, never the marketing page.
    assert b"Own your social stack" not in resp.content
