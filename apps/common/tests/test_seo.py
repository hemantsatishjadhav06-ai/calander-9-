"""robots.txt, favicon.ico, and base-template SEO meta."""

import pytest
from django.test import Client


def test_robots_txt():
    resp = Client().get("/robots.txt")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/plain")
    assert b"User-agent: *" in resp.content
    assert b"Disallow: /api/" in resp.content


def test_favicon_redirects_to_static():
    resp = Client().get("/favicon.ico")
    assert resp.status_code == 301
    assert "favicon/favicon.ico" in resp["Location"]


@pytest.mark.django_db
def test_login_page_has_seo_meta():
    # Exercises base.html head with a real request context (unauthenticated).
    resp = Client().get("/accounts/login/")
    assert resp.status_code == 200
    assert b'property="og:site_name"' in resp.content
    assert b'name="description"' in resp.content
