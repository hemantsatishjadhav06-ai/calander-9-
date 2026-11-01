"""HTML responses are gzipped for browsers that ask; files, streams and JSON are left alone.

Before this, nothing compressed HTML: Home was 136 KB on the wire on a phone, most of what a slow
connection waits for before the first paint (issue #25). Static files were already compressed by
WhiteNoise, which answers before this middleware and so never reaches it.
"""

import gzip
import io

import pytest
from django.conf import settings
from django.http import FileResponse, HttpResponse, JsonResponse, StreamingHttpResponse
from django.test import RequestFactory

from apps.common.middleware import HtmlGZipMiddleware

PAGE = "<!doctype html><html><body>" + "<p>The team is working.</p>" * 40 + "</body></html>"


def _through(response, accept="gzip, deflate, br"):
    request = RequestFactory().get("/", HTTP_ACCEPT_ENCODING=accept)
    return HtmlGZipMiddleware(lambda _request: response)(request)


@pytest.mark.django_db
def test_a_page_is_gzipped_for_a_browser_that_asks(client):
    response = client.get("/accounts/login/", HTTP_ACCEPT_ENCODING="gzip, deflate, br")

    assert response.status_code == 200
    assert response["Content-Encoding"] == "gzip"
    assert "Accept-Encoding" in response["Vary"]
    page = gzip.decompress(response.content).decode()
    assert "<html" in page and "</html>" in page


@pytest.mark.django_db
def test_a_page_stays_plain_for_a_client_that_does_not_ask(client):
    response = client.get("/accounts/login/")

    assert response.status_code == 200
    assert not response.has_header("Content-Encoding")
    assert "<html" in response.content.decode()


def test_an_htmx_fragment_is_html_too():
    response = _through(HttpResponse("<li>Draft</li>" * 40, content_type="text/html; charset=utf-8"))

    assert response["Content-Encoding"] == "gzip"
    assert gzip.decompress(response.content).decode() == "<li>Draft</li>" * 40


def test_json_files_and_streams_are_left_alone():
    payload = {"items": ["a post"] * 200}
    assert not _through(JsonResponse(payload)).has_header("Content-Encoding")

    picture = _through(FileResponse(io.BytesIO(b"\x89PNG" + b"0" * 4000), content_type="image/png"))
    assert not picture.has_header("Content-Encoding")
    assert b"".join(picture.streaming_content).startswith(b"\x89PNG")

    stream = _through(StreamingHttpResponse(iter([PAGE]), content_type="text/html"))
    assert not stream.has_header("Content-Encoding")


def test_a_page_already_encoded_or_tiny_is_left_alone():
    encoded = HttpResponse(PAGE, content_type="text/html")
    encoded["Content-Encoding"] = "br"
    assert _through(encoded)["Content-Encoding"] == "br"

    assert not _through(HttpResponse("<p>ok</p>", content_type="text/html")).has_header("Content-Encoding")
    assert not _through(HttpResponse(PAGE, content_type="text/html"), accept="identity").has_header("Content-Encoding")


def test_compression_keeps_djangos_breach_padding():
    # Django pads the gzip header with up to this many random bytes, so the length of a page that
    # reflects input next to a secret (the CSRF token, which Django also masks) does not leak it.
    assert HtmlGZipMiddleware.max_random_bytes >= 100


def test_compression_sits_after_whitenoise_and_before_every_middleware_that_writes_the_page():
    order = list(settings.MIDDLEWARE)
    here = order.index("apps.common.middleware.HtmlGZipMiddleware")

    # WhiteNoise answers static files before reaching it (they are compressed already); every
    # middleware listed after it finishes its response first, so the page is compressed last.
    assert order.index("whitenoise.middleware.WhiteNoiseMiddleware") < here
    for later in ("csp.middleware.CSPMiddleware", "django.contrib.messages.middleware.MessageMiddleware"):
        assert order.index(later) > here
    assert "django.middleware.gzip.GZipMiddleware" not in order
