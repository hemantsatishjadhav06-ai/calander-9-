"""Tests for apps.common.net.pinned_request (SSRF connection pinning).

Verifies the fix for the DNS-rebinding TOCTOU: the request must connect to a
pre-validated public IP while pinning TLS SNI + Host to the real hostname, and
must reject hosts that resolve to private/reserved addresses.
"""

from unittest import mock

import httpx
import pytest

from apps.common import net


def _send(url, ip, **kwargs):
    """Build+send a pinned request through a MockTransport; return the request."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, text="ok")

    transport = httpx.MockTransport(handler)
    with (
        mock.patch("apps.common.net.resolve_public_ip", return_value=ip),
        httpx.Client(transport=transport) as client,
    ):
        request = net.build_pinned_request(client, "GET", url, **kwargs)
        client.send(request)
    return captured["request"]


def test_rejects_private_or_unresolvable():
    with (
        mock.patch("apps.common.net.resolve_public_ip", return_value=None),
        pytest.raises(net.UnsafeUrlError),
    ):
        net.pinned_request("GET", "http://169.254.169.254/latest/meta-data/")


def test_build_pins_ip_and_preserves_host_and_sni():
    req = _send("https://example.com/feed", "93.184.216.34", headers={"User-Agent": "x"})
    assert req.url.host == "93.184.216.34"  # dialled the vetted IP
    assert req.headers["host"] == "example.com"  # server still sees real host
    assert req.extensions.get("sni_hostname") == "example.com"  # cert verified vs host
    assert req.headers["user-agent"] == "x"


def test_non_default_port_preserved_in_host_header():
    req = _send("https://example.com:8443/x", "93.184.216.34")
    assert req.url.host == "93.184.216.34"
    assert req.url.port == 8443
    assert req.headers["host"] == "example.com:8443"


def test_http_scheme_sets_no_sni():
    req = _send("http://example.com/x", "93.184.216.34")
    assert "sni_hostname" not in req.extensions


def test_ipv6_is_bracketed():
    req = _send("https://example.com/x", "2606:2800:220:1:248:1893:25c8:1946")
    assert req.url.netloc.decode().startswith("[2606:")
