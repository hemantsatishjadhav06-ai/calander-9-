"""Public legal placeholder pages render without auth and aren't login-gated."""

from django.test import Client, override_settings


def test_terms_page_is_public():
    resp = Client().get("/terms/")
    assert resp.status_code == 200
    assert b"Terms of Service" in resp.content


def test_privacy_page_is_public():
    resp = Client().get("/privacy/")
    assert resp.status_code == 200
    assert b"Privacy Policy" in resp.content


@override_settings(SITE_NAME="SM Bean", SUPPORT_EMAIL="help@smbean.example")
def test_branding_context_reaches_template():
    resp = Client().get("/terms/")
    assert b"SM Bean" in resp.content
    assert b"help@smbean.example" in resp.content
