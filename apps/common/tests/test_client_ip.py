"""Who a request came from, when a proxy sits in front.

``X-Forwarded-For`` is attacker-controlled. Honouring it unconditionally lets
someone rotate the header per request to land in a fresh rate-limit bucket
every time, and pin audit-log rows to a victim's address. It is trusted only
when the socket peer is a proxy we run.

CIDR support is what makes the setting fillable on a managed platform: Railway
and friends front the app with an edge whose address comes from a private range
and is not stable per deploy, so an exact-match-only list cannot be written
correctly — and an empty list means every visitor shares one bucket, where ten
failed logins from anyone lock out everyone.
"""

import pytest
from django.test import RequestFactory, override_settings

from apps.common.net import client_ip, is_trusted_proxy


def req(remote, forwarded=None):
    request = RequestFactory().get("/")
    request.META["REMOTE_ADDR"] = remote
    if forwarded is not None:
        request.META["HTTP_X_FORWARDED_FOR"] = forwarded
    return request


@override_settings(BB_TRUSTED_PROXIES=())
def test_nothing_is_trusted_by_default():
    """An app reachable without a proxy must not believe the header."""
    assert client_ip(req("203.0.113.9", "1.2.3.4")) == "203.0.113.9"


@override_settings(BB_TRUSTED_PROXIES=("10.0.0.1",))
def test_an_exact_address_still_works():
    assert client_ip(req("10.0.0.1", "203.0.113.9")) == "203.0.113.9"
    # A peer that is not the proxy is the client, header or no header.
    assert client_ip(req("198.51.100.7", "203.0.113.9")) == "198.51.100.7"


@override_settings(BB_TRUSTED_PROXIES=("100.64.0.0/10",))
def test_a_cidr_range_covers_an_edge_whose_address_moves():
    assert client_ip(req("100.64.3.17", "203.0.113.9")) == "203.0.113.9"
    assert client_ip(req("100.127.255.1", "203.0.113.9")) == "203.0.113.9"
    # Just outside the range.
    assert client_ip(req("100.128.0.1", "203.0.113.9")) == "100.128.0.1"


@override_settings(BB_TRUSTED_PROXIES=("10.0.0.0/8",))
def test_the_leftmost_untrusted_hop_is_the_client():
    """RFC 7239: the rightmost entry is the proxy nearest us."""
    assert client_ip(req("10.0.0.1", "203.0.113.9, 10.0.0.5, 10.0.0.1")) == "203.0.113.9"


@override_settings(BB_TRUSTED_PROXIES=("10.0.0.0/8",))
def test_a_forged_header_cannot_move_the_bucket():
    """The whole point: a client that is not behind our proxy is pinned to its peer."""
    forged = "10.0.0.2, 127.0.0.1"
    assert client_ip(req("198.51.100.7", forged)) == "198.51.100.7"


@override_settings(BB_TRUSTED_PROXIES=("10.0.0.0/8",))
def test_an_all_trusted_chain_falls_back_to_the_peer():
    assert client_ip(req("10.0.0.1", "10.0.0.9, 10.0.0.5")) == "10.0.0.1"


@override_settings(BB_TRUSTED_PROXIES=("10.0.0.0/8",))
def test_a_junk_hop_is_not_treated_as_a_client():
    """The nearest untrusted hop wins; junk further left is never reached."""
    assert client_ip(req("10.0.0.1", "not-an-ip, 203.0.113.9")) == "203.0.113.9"
    # Junk nearest the proxy means the chain can't be trusted: use the peer.
    assert client_ip(req("10.0.0.1", "203.0.113.9, not-an-ip")) == "10.0.0.1"


@override_settings(BB_TRUSTED_PROXIES=("10.0.0.0/8",))
def test_a_client_written_prefix_cannot_move_the_bucket():
    """The edge appends the real address; whatever the client put first is ignored."""
    for forged in ("1.1.1.1", "8.8.8.8", "9.9.9.9"):
        assert client_ip(req("10.0.0.1", f"{forged}, 203.0.113.9")) == "203.0.113.9"


@override_settings(BB_TRUSTED_PROXIES=("10.0.0.0/8", "nonsense", "192.168.1.1"))
def test_an_unparseable_entry_is_dropped_not_fatal():
    """A typo in env config must not take the site down."""
    assert is_trusted_proxy("10.1.2.3") is True
    assert is_trusted_proxy("192.168.1.1") is True
    assert is_trusted_proxy("203.0.113.9") is False


@override_settings(BB_TRUSTED_PROXIES=("10.0.0.0/8",))
def test_a_missing_peer_is_not_trusted():
    assert is_trusted_proxy(None) is False
    assert is_trusted_proxy("") is False


@pytest.mark.django_db
@override_settings(BB_TRUSTED_PROXIES=("10.0.0.0/8",))
def test_the_throttle_and_the_api_agree_on_the_address():
    """Two buckets keyed differently would let one path launder the other."""
    from apps.accounts.middleware import AuthRateLimitMiddleware
    from apps.api.limits import _client_ip

    request = req("10.0.0.1", "203.0.113.9")
    assert AuthRateLimitMiddleware._get_client_ip(request) == _client_ip(request) == "203.0.113.9"
