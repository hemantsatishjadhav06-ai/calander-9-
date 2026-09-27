"""Branded error pages render (incl. 500 with no request context)."""

from django.template.loader import render_to_string
from django.test import Client


def test_404_uses_branded_page():
    resp = Client().get("/this-path-does-not-exist-xyz/")
    assert resp.status_code == 404
    assert b"Page not found" in resp.content
    assert b"Back to SM Bean" in resp.content


def test_500_template_renders_without_context():
    # The default server_error handler renders with an empty context — this
    # must not raise (no context-processor / {% url %} dependencies).
    html = render_to_string("500.html", {})
    assert "500" in html
    assert "Back to SM Bean" in html


def test_403_template_renders():
    html = render_to_string("403.html", {})
    assert "Access denied" in html
