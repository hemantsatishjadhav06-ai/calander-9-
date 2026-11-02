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

import hashlib
import time

import jwt
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


# --- the network key: one bucket per IPv6 /64 (Request invite) ------------------------------------
#
# An IPv6 client is usually handed a whole /64 network and can take a fresh address from it for each
# request, so a per-address limit is no limit for them. ``ratelimit_client_network`` groups them by
# that network and keeps IPv4 per address; ``ratelimit_client_ip``, which every other view uses, is
# unchanged.


@override_settings(BB_TRUSTED_PROXIES=())
def test_the_network_key_groups_an_ipv6_client_by_its_64():
    from apps.common.net import ratelimit_client_network

    one = ratelimit_client_network("group", req("2001:db8:1:2::1"))
    assert one == "2001:db8:1:2::/64"
    assert ratelimit_client_network("group", req("2001:db8:1:2:ffff:ffff:ffff:fffe")) == one
    assert ratelimit_client_network("group", req("2001:db8:1:3::1")) == "2001:db8:1:3::/64"


@override_settings(BB_TRUSTED_PROXIES=())
def test_the_network_key_keeps_ipv4_per_address():
    from apps.common.net import ratelimit_client_network

    assert ratelimit_client_network("group", req("203.0.113.7")) == "203.0.113.7"
    assert ratelimit_client_network("group", req("203.0.113.8")) == "203.0.113.8"
    # An IPv4 address written the IPv6 way is still that one IPv4 address, not a /64 of them.
    assert ratelimit_client_network("group", req("::ffff:203.0.113.7")) == "203.0.113.7"


@override_settings(BB_TRUSTED_PROXIES=("10.0.0.0/8",))
def test_the_network_key_reads_the_client_behind_a_trusted_proxy():
    from apps.common.net import ratelimit_client_network

    assert ratelimit_client_network("group", req("10.0.0.1", "2001:db8:9:9::42")) == "2001:db8:9:9::/64"


def test_the_network_key_without_an_address_is_empty():
    from apps.common.net import ratelimit_client_network

    request = RequestFactory().get("/")
    request.META.pop("REMOTE_ADDR", None)
    assert ratelimit_client_network("group", request) == ""


@override_settings(BB_TRUSTED_PROXIES=())
def test_every_other_view_keeps_its_per_address_key():
    from apps.common.net import ratelimit_client_ip

    assert ratelimit_client_ip("group", req("2001:db8:1:2::1")) == "2001:db8:1:2::1"
    assert ratelimit_client_ip("group", req("2001:db8:1:2::2")) == "2001:db8:1:2::2"


# --- Netlify in front of Render ------------------------------------------------------------------
#
# The public address is a Netlify site that proxies every request to the Render web service, so a
# request reaches Django as visitor -> Netlify -> Render's proxy -> gunicorn. Render's proxy is the
# socket peer (a private 10.x address) and appends the address it saw, which for every visitor is one
# of Netlify's: trusting the private range alone would put everyone behind the same Netlify node in
# one rate-limit bucket. Netlify's supported header for the visitor is X-Nf-Client-Connection-Ip (an
# X-Forwarded-For may arrive as well, which the app does not rely on) and, for a signed proxy rule,
# it signs each request with X-Nf-Sign (an HS256 JWS made from FRONT_DOOR_SIGNING_SECRET). Only a request carrying that signature has its
# X-Nf-Client-Connection-Ip believed. The service's own *.onrender.com address is public, so anyone
# can send both headers straight to it; without the secret they cannot sign them.


# Derived, not written out: a long random-looking literal reads as a leaked credential to a secret scan.
SIGNING_SECRET = hashlib.sha256(b"the front door, in tests").hexdigest()
ANOTHER_SECRET = hashlib.sha256(b"somebody else").hexdigest()
RENDER_PROXY = "10.204.7.31"
NETLIFY_NODE = "198.51.100.20"


def netlify_signature(secret=SIGNING_SECRET, **claims):
    payload = {
        "deploy_context": "production",
        "exp": int(time.time()) + 300,
        "iss": "netlify",
        "netlify_id": "1be0f471-6532-45ff-b1b1-f9c66ea24dc1",
        "site_url": "https://sm-bean.netlify.app",
    }
    payload.update(claims)
    return jwt.encode({k: v for k, v in payload.items() if v is not None}, secret, algorithm="HS256")


def via_front_door(visitor, *, signature=None, forwarded=None, peer=RENDER_PROXY):
    """A request as Render hands it on after Netlify proxied it (or a forgery shaped like one)."""
    request = req(peer, forwarded if forwarded is not None else f"{visitor}, {NETLIFY_NODE}")
    request.META["HTTP_X_NF_CLIENT_CONNECTION_IP"] = visitor
    if signature is not None:
        request.META["HTTP_X_NF_SIGN"] = signature
    return request


@override_settings(BB_TRUSTED_PROXIES=("10.0.0.0/8",), FRONT_DOOR_SIGNING_SECRET=SIGNING_SECRET)
def test_a_signed_front_door_request_names_the_visitor():
    assert client_ip(via_front_door("203.0.113.9", signature=netlify_signature())) == "203.0.113.9"


@override_settings(BB_TRUSTED_PROXIES=("10.0.0.0/8",), FRONT_DOOR_SIGNING_SECRET=SIGNING_SECRET)
def test_two_visitors_behind_one_netlify_node_get_two_buckets():
    """The point of the signature: ten failed logins from one visitor must not lock out the next."""
    first = client_ip(via_front_door("203.0.113.9", signature=netlify_signature()))
    second = client_ip(via_front_door("192.0.2.44", signature=netlify_signature()))
    assert first != second
    assert NETLIFY_NODE not in (first, second)


@override_settings(BB_TRUSTED_PROXIES=("10.0.0.0/8",), FRONT_DOOR_SIGNING_SECRET=SIGNING_SECRET)
def test_an_ipv6_visitor_is_named_too():
    assert client_ip(via_front_door("2001:db8:5::7", signature=netlify_signature())) == "2001:db8:5::7"


@override_settings(BB_TRUSTED_PROXIES=("10.0.0.0/8",), FRONT_DOOR_SIGNING_SECRET=SIGNING_SECRET)
def test_without_a_signature_the_netlify_header_is_ignored():
    """Unsigned, the request falls back to what Render's proxy vouched for: never the header's claim."""
    assert client_ip(via_front_door("203.0.113.9")) == NETLIFY_NODE


@pytest.mark.parametrize(
    "signature",
    [
        "",
        "not-a-jws",
        netlify_signature(secret=ANOTHER_SECRET),
        netlify_signature(exp=int(time.time()) - 3600),
        netlify_signature(exp=None),
        netlify_signature(iss="somebody-else"),
        netlify_signature(iss=None),
        jwt.encode({"iss": "netlify", "exp": int(time.time()) + 300}, key="", algorithm="none"),
    ],
    ids=["empty", "junk", "wrong-secret", "expired", "no-expiry", "wrong-issuer", "no-issuer", "alg-none"],
)
@override_settings(BB_TRUSTED_PROXIES=("10.0.0.0/8",), FRONT_DOOR_SIGNING_SECRET=SIGNING_SECRET)
def test_a_bad_signature_is_no_signature(signature):
    assert client_ip(via_front_door("203.0.113.9", signature=signature)) == NETLIFY_NODE


@override_settings(BB_TRUSTED_PROXIES=("10.0.0.0/8",), FRONT_DOOR_SIGNING_SECRET="")
def test_without_the_secret_nothing_is_believed():
    """Unconfigured, a token signed with an empty or guessed key must not count as Netlify's."""
    for secret in (SIGNING_SECRET, "x" * 32):
        request = via_front_door("203.0.113.9", signature=netlify_signature(secret=secret))
        assert client_ip(request) == NETLIFY_NODE


@override_settings(BB_TRUSTED_PROXIES=("10.0.0.0/8",), FRONT_DOOR_SIGNING_SECRET=SIGNING_SECRET)
def test_going_round_the_front_door_cannot_borrow_another_visitors_address():
    """Straight to *.onrender.com with every header forged: Render appends the sender's real address."""
    attacker = "198.51.100.66"
    victim = "203.0.113.9"
    forged = via_front_door(
        victim,
        signature=netlify_signature(secret=ANOTHER_SECRET),
        forwarded=f"{victim}, {attacker}",
    )
    assert client_ip(forged) == attacker


@override_settings(BB_TRUSTED_PROXIES=("10.0.0.0/8",), FRONT_DOOR_SIGNING_SECRET=SIGNING_SECRET)
def test_a_signed_request_with_a_junk_visitor_falls_back():
    request = via_front_door("not-an-ip", signature=netlify_signature(), forwarded=f"203.0.113.9, {NETLIFY_NODE}")
    assert client_ip(request) == NETLIFY_NODE


@override_settings(BB_TRUSTED_PROXIES=(), FRONT_DOOR_SIGNING_SECRET=SIGNING_SECRET)
def test_the_signature_does_not_depend_on_the_proxy_list():
    """Render's proxy address is not published; the signature alone proves the request came from Netlify."""
    assert client_ip(via_front_door("203.0.113.9", signature=netlify_signature())) == "203.0.113.9"
    # Unsigned and with no trusted proxy, the socket peer is all that can be vouched for.
    assert client_ip(via_front_door("203.0.113.9")) == RENDER_PROXY


@pytest.mark.django_db
@override_settings(BB_TRUSTED_PROXIES=("10.0.0.0/8",), FRONT_DOOR_SIGNING_SECRET=SIGNING_SECRET)
def test_the_login_throttle_the_api_and_the_rate_limits_agree_behind_the_front_door():
    from apps.accounts.middleware import AuthRateLimitMiddleware
    from apps.api.limits import _client_ip
    from apps.common.net import ratelimit_client_ip, ratelimit_client_network

    request = via_front_door("203.0.113.9", signature=netlify_signature())
    assert AuthRateLimitMiddleware._get_client_ip(request) == _client_ip(request) == "203.0.113.9"
    assert ratelimit_client_ip("group", request) == ratelimit_client_network("group", request) == "203.0.113.9"
