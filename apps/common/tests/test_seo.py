"""robots.txt, favicon.ico, and base-template SEO meta."""

import pytest
from django.test import Client


def test_robots_txt():
    resp = Client().get("/robots.txt")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/plain")
    assert b"User-agent: *" in resp.content
    assert b"Disallow: /api/" in resp.content


def test_robots_txt_points_at_the_sitemap():
    """An absolute URL: crawlers ignore a relative Sitemap: line."""
    resp = Client().get("/robots.txt")
    assert b"Sitemap: http://testserver/sitemap.xml" in resp.content


def test_sitemap_lists_the_public_pages_only():
    resp = Client().get("/sitemap.xml")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("application/xml")
    body = resp.content.decode()
    # The three linked pages, then the legal pages it always listed.
    for path in ("/", "/how-it-works/", "/request-invite/", "/terms/", "/privacy/", "/support/"):
        assert f"<loc>http://testserver{path}</loc>" in body
    # Pricing redirects now, and the hidden pages ask not to be indexed.
    for path in ("/pricing/", "/features/", "/platforms/", "/developers/", "/get-started/"):
        assert f"<loc>http://testserver{path}</loc>" not in body
    # The app surface is disallowed in robots.txt; it must not be advertised here.
    assert "/workspace/" not in body
    assert "/accounts/" not in body


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
