"""QA round 1: /support/ existed nowhere and the policy pages were placeholders."""

import pytest
from django.test import override_settings


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/terms/", "/privacy/", "/support/"])
def test_public_policy_pages_render_for_anonymous_visitors(client, path):
    resp = client.get(path)
    assert resp.status_code == 200
    assert b"brightbean" not in resp.content.lower()


@pytest.mark.django_db
def test_privacy_carries_the_google_limited_use_disclosure(client):
    resp = client.get("/privacy/")
    assert b"Limited Use" in resp.content
    assert b"Digital Personal Data Protection Act" in resp.content


@pytest.mark.django_db
def test_draft_notice_goes_once_counsel_has_signed_off(client):
    assert b"<strong>Draft.</strong>" in client.get("/terms/").content
    with override_settings(LEGAL_PAGES_REVIEWED=True):
        assert b"<strong>Draft.</strong>" not in client.get("/terms/").content


@pytest.mark.django_db
@override_settings(LAUNCHED_PLATFORMS=["bluesky"])
def test_support_lists_only_launched_platforms_as_live(client):
    body = client.get("/support/").content.decode()
    live, _, soon = body.partition("Coming soon")
    assert "Bluesky" in live
    assert "Instagram" not in live
    assert "Instagram" in soon
