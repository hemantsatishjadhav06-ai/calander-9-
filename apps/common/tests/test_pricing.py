"""/pricing/ during the invite-only beta: a permanent redirect to Request invite.

The page used to list plans with sign-up and mailto CTAs. The beta asks for an
invitation instead, so the old URL (and its ``pricing`` name, still used by
``{% url 'pricing' %}``) answers 301 to the form, and no public page links to it.
"""

import pytest
from django.test import Client
from django.urls import reverse


def test_pricing_keeps_its_url_name():
    assert reverse("pricing") == "/pricing/"


def test_pricing_answers_301_to_request_invite():
    resp = Client().get("/pricing/")
    assert resp.status_code == 301
    assert resp["Location"] == reverse("marketing:request_invite")


def test_pricing_redirect_lands_on_a_working_page():
    resp = Client().get("/pricing/", follow=True)
    assert resp.status_code == 200
    assert resp.redirect_chain == [("/request-invite/", 301)]
    assert "pricing.html" not in [t.name for t in resp.templates]


def test_pricing_stays_read_only():
    assert Client().post("/pricing/").status_code == 405


@pytest.mark.django_db
def test_landing_links_to_request_invite_not_pricing():
    resp = Client().get("/")
    assert b'href="/pricing/"' not in resp.content
    assert b'href="/request-invite/"' in resp.content


def test_request_invite_uses_the_marketing_sites_header_and_footer():
    """Like pricing before it, the form page extends marketing/base.html rather than carrying its own chrome."""
    html = Client().get("/request-invite/").content.decode()
    assert ">How it works</a>" in html
    assert 'href="/request-invite/" class="is-active" aria-current="page">Request invite</a>' in html
    assert 'class="mk-footer"' in html
    assert 'class="pr-foot"' not in html
    assert html.count("<main") == 1 and html.count("<header") == 1
