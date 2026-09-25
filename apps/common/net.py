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

import ipaddress
import logging
from functools import lru_cache
from urllib.parse import urlparse

import httpx
from django.conf import settings

from .validators import resolve_public_ip

logger = logging.getLogger(__name__)


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


# ---------------------------------------------------------------------------
# Trusted-proxy client IP
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _trusted_networks(entries: tuple[str, ...]) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """Parse ``BB_TRUSTED_PROXIES`` entries into networks, once per value.

    A bare address parses as a single-host network, so exact IPs keep working
    exactly as before. Entries that are not valid addresses or networks are
    dropped rather than raising: a typo in env config must not take the site
    down, and dropping one only means that hop stops being trusted.
    """
    networks = []
    for entry in entries:
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            logger.warning("Ignoring unparseable BB_TRUSTED_PROXIES entry %r", entry)
    return tuple(networks)


def is_trusted_proxy(addr: str | None) -> bool:
    """True when *addr* falls inside a configured trusted-proxy range.

    CIDR ranges matter on managed platforms: Railway, Fly and friends front the
    app with an edge whose address comes from a private range and is not stable
    per deploy, so an exact-match-only list is impossible to fill in correctly.
    An empty setting trusts nothing, which is the right default for an app
    reachable without a proxy in front of it.
    """
    if not addr:
        return False
    networks = _trusted_networks(tuple(getattr(settings, "BB_TRUSTED_PROXIES", ()) or ()))
    if not networks:
        return False
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return any(ip in network for network in networks)


def ratelimit_client_ip(group, request) -> str:
    """django-ratelimit ``key`` callable: bucket by the real client IP.

    ``key="ip"`` buckets on ``REMOTE_ADDR``, which behind a managed platform's
    edge is the edge itself — one bucket shared by every caller, so a legitimate
    sender is throttled by everyone else's traffic and a single abuser can
    empty it for all of them. See :func:`client_ip` for the trust rules.
    """
    return client_ip(request) or ""


def client_ip(request) -> str | None:
    """The originating client IP, honouring ``X-Forwarded-For`` only from a proxy we run.

    A remote client can put anything in ``X-Forwarded-For``, so honouring it
    unconditionally lets an attacker rotate the header per request to land in a
    fresh rate-limit bucket every time — defeating the throttle, and letting
    them pin audit-log rows to a victim's IP. Only trust the header when the
    socket peer is itself a trusted proxy; otherwise the peer is the only
    address we can vouch for.

    Within a trusted chain the leftmost hop that is not itself a trusted proxy
    is the client: per RFC 7239 the rightmost entry is the proxy closest to us.
    """
    remote = request.META.get("REMOTE_ADDR")
    if not is_trusted_proxy(remote):
        return remote

    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        for hop in (h.strip() for h in forwarded.split(",") if h.strip()):
            if not is_trusted_proxy(hop):
                return hop
        # Every hop was a trusted proxy — the peer is all we have.
    return remote
