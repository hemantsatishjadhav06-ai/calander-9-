"""SSRF-safe outbound HTTP.

``is_safe_url`` / ``resolve_public_ip`` resolve a hostname and check the
addresses, but a plain ``httpx`` call then performs its *own* DNS resolution at
connect time — a rebinding DNS server (TTL 0, alternating public/private
answers) passes the check and then connects to a private address.

``pinned_request`` closes that TOCTOU: it resolves the hostname to a vetted
public IP once and connects to that *literal* address, while pinning the TLS
SNI + certificate verification and the ``Host`` header to the original
hostname (httpcore uses the ``sni_hostname`` extension as the TLS
``server_hostname``, which drives both SNI and cert hostname matching).

Redirects are never followed here — callers that allow redirects must handle
each hop themselves and re-validate it, or the pin is bypassed on the next hop.
"""

from urllib.parse import urlparse

import httpx

from .validators import resolve_public_ip


class UnsafeUrlError(Exception):
    """Raised when a URL is not a public http(s) endpoint (or won't resolve)."""


def _host_header(parsed) -> str:
    """Original Host header value, preserving a non-default port."""
    host = parsed.hostname or ""
    default_port = 443 if parsed.scheme == "https" else 80
    if parsed.port and parsed.port != default_port:
        return f"{host}:{parsed.port}"
    return host


def pin_url(url: str, headers=None) -> tuple[str, dict, dict]:
    """Resolve *url* to a vetted public IP and return the pieces to connect to
    that literal address while pinning TLS SNI + Host to the hostname:
    ``(pinned_url, headers_with_host, extensions)``.

    Use directly with httpx:
        pinned, hdrs, ext = pin_url(url, headers)
        client.request(method, pinned, headers=hdrs, extensions=ext, ...)

    Raises UnsafeUrlError if the URL is not http(s) or resolves to a
    private/reserved/loopback/link-local address.
    """
    parsed = urlparse(url)
    ip = resolve_public_ip(url)
    if ip is None:
        raise UnsafeUrlError(f"URL rejected (must be a public http(s) endpoint): {url}")

    pinned_url = str(httpx.URL(url).copy_with(host=ip))  # httpx brackets IPv6 for us

    req_headers = dict(headers or {})
    # Connect target is the IP, but the server must still see the real Host.
    req_headers["Host"] = _host_header(parsed)

    extensions: dict = {}
    if parsed.scheme == "https":
        # Verify the cert against the real hostname, not the IP we dialled.
        extensions["sni_hostname"] = parsed.hostname

    return pinned_url, req_headers, extensions


def build_pinned_request(client: httpx.Client, method: str, url: str, *, headers=None, content=None) -> httpx.Request:
    """Build an httpx.Request pinned to *url*'s vetted public IP.

    Raises UnsafeUrlError if the URL is not http(s) or resolves to a
    private/reserved/loopback/link-local address.
    """
    pinned_url, req_headers, extensions = pin_url(url, headers)
    return client.build_request(method, pinned_url, headers=req_headers, content=content, extensions=extensions)


def pinned_request(
    method: str,
    url: str,
    *,
    headers=None,
    content=None,
    timeout: float = 10.0,
) -> httpx.Response:
    """Issue a single, redirect-free request pinned to *url*'s vetted public IP.

    Raises UnsafeUrlError on an unsafe/unresolvable URL and propagates
    httpx.RequestError on transport failure. Never follows redirects.
    """
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        request = build_pinned_request(client, method, url, headers=headers, content=content)
        return client.send(request)
