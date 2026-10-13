"""Database-backed Neopolis publisher probes; every external write is mocked."""

import threading
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
from django.db import connections
from django.test import TransactionTestCase
from django.utils import timezone

from apps.composer.models import PlatformPost, Post
from apps.organizations.models import Organization
from apps.publisher.engine import PublishEngine
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace
from providers.exceptions import APIError, RateLimitError
from providers.types import AuthType


class NeopolisPublishRecoveryTests(TransactionTestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Neopolis audit")
        self.workspace = Workspace.objects.create(organization=self.org, name="Neopolis", timezone="Asia/Kolkata")
        self.account = SocialAccount.objects.create(
            workspace=self.workspace,
            platform="instagram",
            account_platform_id="17841400000000000",
            account_name="Neopolis Infra",
            account_handle="neopolisinfra",
            oauth_access_token="audit-token",
        )
        when = timezone.now() - timedelta(minutes=2)
        self.post = Post.objects.create(workspace=self.workspace, caption="Neopolis site visit", scheduled_at=when)
        self.pp = PlatformPost.objects.create(
            post=self.post, social_account=self.account, status=PlatformPost.Status.SCHEDULED, scheduled_at=when
        )
        self.engine = PublishEngine()

    def claim(self):
        PlatformPost.objects.filter(pk=self.pp.pk).update(status=PlatformPost.Status.PUBLISHING)
        self.pp.refresh_from_db()
        # Deliberately cache the pre-change account, as an already-running upload would.
        self.assertEqual(self.pp.social_account.connection_status, SocialAccount.ConnectionStatus.CONNECTED)

    def assert_blocked_without_api(self):
        with patch.object(PublishEngine, "_dispatch_to_provider") as dispatch:
            result = self.engine._publish_platform_post(self.pp)
        dispatch.assert_not_called()
        self.assertFalse(result["success"])
        self.pp.refresh_from_db()
        self.assertEqual(self.pp.status, PlatformPost.Status.FAILED)
        self.assertEqual(self.pp.retry_count, 0)
        self.assertIsNone(self.pp.next_retry_at)

    def test_error_channel_after_claim_never_uses_cached_token(self):
        self.claim()
        SocialAccount.objects.filter(pk=self.account.pk).update(connection_status=SocialAccount.ConnectionStatus.ERROR)
        self.assert_blocked_without_api()
        self.assertIn("reconnect", self.pp.publish_error)

    def test_disconnected_channel_after_claim_cannot_send(self):
        self.claim()
        SocialAccount.objects.filter(pk=self.account.pk).update(
            connection_status=SocialAccount.ConnectionStatus.DISCONNECTED, oauth_access_token=""
        )
        self.assert_blocked_without_api()

    def test_changed_channel_workspace_after_claim_cannot_send(self):
        self.claim()
        other = Workspace.objects.create(organization=self.org, name="More Space")
        SocialAccount.objects.filter(pk=self.account.pk).update(workspace=other)
        self.assert_blocked_without_api()

    def test_changed_destination_after_claim_cannot_send(self):
        self.claim()
        replacement = SocialAccount.objects.create(
            workspace=self.workspace,
            platform="instagram",
            account_platform_id="17841400000000999",
            account_name="Replacement",
            oauth_access_token="replacement-token",
        )
        PlatformPost.objects.filter(pk=self.pp.pk).update(social_account=replacement)
        self.assert_blocked_without_api()

    def test_rotated_token_is_adopted_before_provider_dispatch(self):
        self.claim()
        SocialAccount.objects.filter(pk=self.account.pk).update(oauth_access_token="rotated-audit-token")

        def accepted(pp, **kwargs):
            self.assertEqual(pp.social_account.oauth_access_token, "rotated-audit-token")
            return {"success": True, "platform_post_id": "mock-neopolis-1"}

        with patch.object(PublishEngine, "_dispatch_to_provider", side_effect=accepted) as dispatch:
            result = self.engine._publish_platform_post(self.pp)
        self.assertTrue(result["success"])
        dispatch.assert_called_once()

    def test_disconnected_due_retry_is_terminal_without_upload(self):
        PlatformPost.objects.filter(pk=self.pp.pk).update(
            retry_count=1, next_retry_at=timezone.now() - timedelta(minutes=1)
        )
        SocialAccount.objects.filter(pk=self.account.pk).update(connection_status=SocialAccount.ConnectionStatus.ERROR)
        with patch.object(PublishEngine, "_dispatch_to_provider") as dispatch:
            self.engine._process_retries()
        dispatch.assert_not_called()
        self.pp.refresh_from_db()
        self.assertEqual(self.pp.status, PlatformPost.Status.FAILED)

    def test_four_overlapping_publish_cycles_upload_once(self):
        barrier = threading.Barrier(4)
        errors, outcomes = [], []
        dispatch_lock = threading.Lock()
        uploads = []

        def accepted(pp, **kwargs):
            with dispatch_lock:
                uploads.append(pp.pk)
            return {"success": True, "platform_post_id": "mock-neopolis-concurrent"}

        def publish():
            try:
                due = [PlatformPost.objects.select_related("post", "social_account").get(pk=self.pp.pk)]
                barrier.wait(timeout=10)
                outcomes.append(PublishEngine()._publish_post_group(due[0].post, due))
            except Exception as exc:
                errors.append(exc)
            finally:
                connections.close_all()

        with patch.object(PublishEngine, "_dispatch_to_provider", side_effect=accepted):
            threads = [threading.Thread(target=publish) for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=20)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(uploads, [self.pp.pk])
        self.assertEqual(sum(outcomes), 1)
        self.pp.refresh_from_db()
        self.assertEqual(self.pp.status, PlatformPost.Status.PUBLISHED)

    def provider(self):
        return MagicMock(auth_type=AuthType.OAUTH2, publish_is_async=False)

    def test_platform_accepts_write_then_loses_response_without_duplicate_cycle(self):
        accepted = []
        provider = self.provider()

        def accepted_then_timeout(token, content):
            accepted.append(content.text)
            raise httpx.ReadTimeout("response lost after platform committed")

        provider.publish_post.side_effect = accepted_then_timeout
        with patch("apps.publisher.engine._provider_and_access_token", return_value=(provider, "audit-token")):
            self.engine.poll_and_publish()
            self.engine.poll_and_publish()
        self.assertEqual(accepted, ["Neopolis site visit"])
        self.pp.refresh_from_db()
        self.assertEqual(self.pp.status, PlatformPost.Status.FAILED)
        self.assertEqual(self.pp.retry_count, 0)
        self.assertIsNone(self.pp.next_retry_at)
        self.assertIn("Check the account", self.pp.publish_error)

    def test_partial_write_and_server_error_do_not_automatically_resubmit(self):
        faults = (
            httpx.WriteTimeout("partial write"),
            httpx.WriteError("connection lost"),
            httpx.ReadError("connection lost"),
            httpx.RemoteProtocolError("missing response"),
            APIError("platform server failed after write", status_code=500),
        )
        for fault in faults:
            with self.subTest(fault=type(fault).__name__):
                # Each transport fault belongs to a fresh campaign attempt.
                # The preceding unknown attempt must remain held.
                PlatformPost.objects.filter(pk=self.pp.pk).update(status=PlatformPost.Status.DRAFT)
                when = timezone.now() - timedelta(minutes=2)
                post = Post.objects.create(workspace=self.workspace, caption="Neopolis site visit", scheduled_at=when)
                self.pp = PlatformPost.objects.create(
                    post=post, social_account=self.account, status=PlatformPost.Status.SCHEDULED, scheduled_at=when
                )
                provider = self.provider()
                provider.publish_post.side_effect = fault
                with patch("apps.publisher.engine._provider_and_access_token", return_value=(provider, "audit-token")):
                    self.engine.poll_and_publish()
                    self.engine.poll_and_publish()
                provider.publish_post.assert_called_once()
                self.pp.refresh_from_db()
                self.assertEqual(self.pp.status, PlatformPost.Status.FAILED)
                self.assertEqual(self.pp.retry_count, 0)

    def test_failure_before_connection_remains_retryable_with_backoff(self):
        for fault in (httpx.ConnectError("no connection"), httpx.ConnectTimeout("no connection")):
            with self.subTest(fault=type(fault).__name__):
                PlatformPost.objects.filter(pk=self.pp.pk).update(
                    status=PlatformPost.Status.SCHEDULED, retry_count=0, next_retry_at=None
                )
                provider = self.provider()
                provider.publish_post.side_effect = fault
                with patch("apps.publisher.engine._provider_and_access_token", return_value=(provider, "audit-token")):
                    self.engine.poll_and_publish()
                    self.engine.poll_and_publish()
                provider.publish_post.assert_called_once()
                self.pp.refresh_from_db()
                self.assertEqual(self.pp.status, PlatformPost.Status.SCHEDULED)
                self.assertEqual(self.pp.retry_count, 1)
                self.assertGreater(self.pp.next_retry_at, timezone.now())

    def test_platform_clear_rate_limit_rejection_remains_retryable(self):
        provider = self.provider()
        provider.publish_post.side_effect = RateLimitError("not accepted", retry_after=120)
        with patch("apps.publisher.engine._provider_and_access_token", return_value=(provider, "audit-token")):
            self.engine.poll_and_publish()
        self.pp.refresh_from_db()
        self.assertEqual(self.pp.status, PlatformPost.Status.SCHEDULED)
        self.assertEqual(self.pp.retry_count, 1)

    def test_known_async_handle_survives_local_response_metadata_failure(self):
        provider = self.provider()
        provider.publish_is_async = True
        provider.publish_post.return_value = SimpleNamespace(platform_post_id="known-upload-handle")
        with patch("apps.publisher.engine._provider_and_access_token", return_value=(provider, "audit-token")):
            self.engine.poll_and_publish()
            self.engine.poll_and_publish()
        provider.publish_post.assert_called_once()
        self.pp.refresh_from_db()
        self.assertEqual(self.pp.status, PlatformPost.Status.PUBLISHING)
        self.assertEqual(self.pp.platform_post_id, "known-upload-handle")
