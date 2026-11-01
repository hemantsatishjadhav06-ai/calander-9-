"""Tests for AuthRateLimitMiddleware — client-IP derivation and throttling —
and for the public pages TosAcceptanceMiddleware lets through.

Regression guard for the audit finding that the auth throttle trusted a
spoofable X-Forwarded-For header, letting an attacker rotate the header to
escape the per-IP bucket (defeating brute-force / password-reset email-bomb
protection).
"""

import pytest
from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, override_settings
from django.urls import reverse

from apps.accounts.middleware import AUTH_RATE_LIMIT, AuthRateLimitMiddleware
from apps.accounts.models import User


def _mw():
    return AuthRateLimitMiddleware(lambda request: HttpResponse("ok"))


class TestClientIp:
    def test_ignores_xff_without_trusted_proxy(self):
        rf = RequestFactory()
        request = rf.post("/accounts/login/", HTTP_X_FORWARDED_FOR="1.2.3.4", REMOTE_ADDR="10.0.0.9")
        # No BB_TRUSTED_PROXIES configured → XFF must be ignored.
        assert AuthRateLimitMiddleware._get_client_ip(request) == "10.0.0.9"

    @override_settings(BB_TRUSTED_PROXIES=("10.0.0.9",))
    def test_honours_xff_from_trusted_proxy(self):
        rf = RequestFactory()
        request = rf.post("/accounts/login/", HTTP_X_FORWARDED_FOR="1.2.3.4", REMOTE_ADDR="10.0.0.9")
        assert AuthRateLimitMiddleware._get_client_ip(request) == "1.2.3.4"

    @override_settings(BB_TRUSTED_PROXIES=("10.0.0.9",))
    def test_skips_trusted_hops_in_xff_chain(self):
        rf = RequestFactory()
        request = rf.post(
            "/accounts/login/",
            HTTP_X_FORWARDED_FOR="1.2.3.4, 10.0.0.9",
            REMOTE_ADDR="10.0.0.9",
        )
        assert AuthRateLimitMiddleware._get_client_ip(request) == "1.2.3.4"

    @override_settings(BB_TRUSTED_PROXIES=("10.0.0.1",))
    def test_untrusted_peer_ignores_xff(self):
        rf = RequestFactory()
        request = rf.post("/accounts/login/", HTTP_X_FORWARDED_FOR="1.2.3.4", REMOTE_ADDR="203.0.113.5")
        assert AuthRateLimitMiddleware._get_client_ip(request) == "203.0.113.5"


class TestThrottle:
    def setup_method(self):
        cache.clear()

    def teardown_method(self):
        cache.clear()

    def test_spoofed_xff_cannot_escape_bucket(self):
        """Rotating XFF per request must NOT reset the bucket (the core bug)."""
        mw = _mw()
        rf = RequestFactory()
        blocked = False
        for i in range(AUTH_RATE_LIMIT + 5):
            request = rf.post(
                "/accounts/login/",
                HTTP_X_FORWARDED_FOR=f"9.9.9.{i}",  # fresh spoofed IP each time
                REMOTE_ADDR="198.51.100.7",  # same real peer, untrusted
            )
            resp = mw(request)
            if resp.status_code == 429:
                blocked = True
                break
        assert blocked, "attacker rotating X-Forwarded-For was never throttled"

    def test_allows_up_to_limit_then_blocks(self):
        mw = _mw()
        rf = RequestFactory()
        for _ in range(AUTH_RATE_LIMIT):
            resp = mw(rf.post("/accounts/login/", REMOTE_ADDR="198.51.100.8"))
            assert resp.status_code == 200
        resp = mw(rf.post("/accounts/login/", REMOTE_ADDR="198.51.100.8"))
        assert resp.status_code == 429

    def test_distinct_ips_have_separate_buckets(self):
        mw = _mw()
        rf = RequestFactory()
        for _ in range(AUTH_RATE_LIMIT + 2):
            mw(rf.post("/accounts/login/", REMOTE_ADDR="198.51.100.10"))
        # A different real peer is unaffected.
        resp = mw(rf.post("/accounts/login/", REMOTE_ADDR="198.51.100.11"))
        assert resp.status_code == 200

    def test_non_auth_path_not_limited(self):
        mw = _mw()
        rf = RequestFactory()
        for _ in range(AUTH_RATE_LIMIT + 5):
            resp = mw(rf.post("/some/other/path/", REMOTE_ADDR="198.51.100.12"))
            assert resp.status_code == 200


@pytest.mark.django_db
class TestTermsExemptions:
    """Someone signed in who has not accepted the terms yet may still read the public pages
    the acceptance page and the marketing site link to, without being sent back to accept."""

    @pytest.fixture
    def not_yet_accepted(self, client):
        user = User.objects.create_user(email="new@agency.example", password="x-long-password-1")
        assert user.tos_accepted_at is None
        client.force_login(user)
        return client

    def test_request_invite_opens_without_the_terms_redirect(self, not_yet_accepted):
        response = not_yet_accepted.get(reverse("marketing:request_invite"))

        assert response.status_code == 200
        assert "marketing/request_invite.html" in [t.name for t in response.templates if t.name]

    def test_the_old_pricing_address_still_lands_on_request_invite(self, not_yet_accepted):
        response = not_yet_accepted.get("/pricing/", follow=True)

        assert response.redirect_chain == [(reverse("marketing:request_invite"), 301)]
        assert response.status_code == 200

    def test_other_pages_still_ask_for_the_terms_first(self, not_yet_accepted):
        response = not_yet_accepted.get(reverse("marketing:how_it_works"))

        assert response.status_code == 302
        assert response["Location"].startswith(reverse("accounts:accept_terms"))
