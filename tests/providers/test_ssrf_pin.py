"""Provider-layer SSRF pinning for user-controlled hosts (Mastodon/Bluesky).

Round-2 finding: the DNS-rebind pinning added for feeds/webhooks did not cover
the provider request path, whose instance_url/pds_url is user-controlled.
"""

from unittest import mock

import pytest

from providers.base import SocialProvider
from providers.bluesky import BlueskyProvider
from providers.exceptions import ProviderError
from providers.mastodon import MastodonProvider


def test_pin_dns_enabled_only_for_user_host_providers():
    assert MastodonProvider.PIN_DNS is True
    assert BlueskyProvider.PIN_DNS is True
    # Fixed first-party hosts (base default) must NOT pin — an egress proxy that
    # allowlists by hostname would otherwise break all first-party publishing.
    assert getattr(SocialProvider, "PIN_DNS", False) is False


def test_mastodon_refuses_private_resolving_instance():
    p = MastodonProvider({"instance_url": "https://evil.example", "client_id": "a", "client_secret": "b"})
    with mock.patch("apps.common.net.resolve_public_ip", return_value=None), pytest.raises(ProviderError):
        p.register_app("https://evil.example", "https://cb.example/x")


def test_mastodon_error_is_non_retryable():
    p = MastodonProvider({"instance_url": "https://evil.example", "client_id": "a", "client_secret": "b"})
    with mock.patch("apps.common.net.resolve_public_ip", return_value=None):
        try:
            p.register_app("https://evil.example", "https://cb.example/x")
            raise AssertionError("expected ProviderError")
        except ProviderError as exc:
            # Refusal is permanent, not a transient failure to retry.
            assert exc.retryable is False
