"""Public pricing page (OSS + managed-hosting model)."""

from django.test import Client, override_settings


def test_pricing_is_public():
    resp = Client().get("/pricing/")
    assert resp.status_code == 200
    assert b"Self-hosted" in resp.content
    assert b"Managed Cloud" in resp.content
    assert b"Free" in resp.content


def test_pricing_links_signup_and_source():
    resp = Client().get("/pricing/")
    assert b'href="/accounts/signup/"' in resp.content


@override_settings(SUPPORT_EMAIL="sales@smbean.example")
def test_managed_cta_uses_support_email():
    resp = Client().get("/pricing/")
    assert b"mailto:sales@smbean.example" in resp.content


def test_landing_links_to_pricing():
    resp = Client().get("/")
    assert b'href="/pricing/"' in resp.content
