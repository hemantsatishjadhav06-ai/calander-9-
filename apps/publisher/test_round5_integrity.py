"""Round-5 publisher findings.

- The retry loop claimed rows on state read minutes earlier, publishing posts
  the user had since unscheduled or held.
- A retry fired on the old backoff time even after the post was moved to a
  later date.
- A child bound to another workspace's channel would have been published.
- A rate-limited publish burned the whole retry ladder inside the window.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import httpx
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.composer.models import PlatformPost, Post
from apps.organizations.models import Organization
from apps.publisher.engine import PublishEngine
from apps.publisher.models import PublishLog, RateLimitState
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace
from providers.exceptions import APIError, RateLimitError
from providers.types import PostType, PublishResult


def _world():
    author = User.objects.create_user(email="a@example.com", password="x", name="A", tos_accepted_at=timezone.now())
    org = Organization.objects.create(name="Org")
    ws = Workspace.objects.create(organization=org, name="WS")
    account = SocialAccount.objects.create(
        workspace=ws,
        platform="bluesky",
        account_platform_id="did:plc:1",
        account_name="acct",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
    )
    return author, ws, account


def _retrying_row(author, ws, account, *, next_retry_in=-1, scheduled_in=-5):
    when = timezone.now() + timedelta(minutes=scheduled_in)
    post = Post.objects.create(workspace=ws, caption="hi", author=author, scheduled_at=when)
    return PlatformPost.objects.create(
        post=post,
        social_account=account,
        status=PlatformPost.Status.SCHEDULED,
        scheduled_at=when,
        retry_count=1,
        next_retry_at=timezone.now() + timedelta(minutes=next_retry_in),
    )


class RetryLoopTests(TransactionTestCase):
    def setUp(self):
        self.author, self.ws, self.account = _world()

    def test_a_row_unscheduled_during_the_loop_is_not_published(self):
        first = _retrying_row(self.author, self.ws, self.account)
        second = _retrying_row(self.author, self.ws, self.account)
        provider = MagicMock()
        provider.publish_post.return_value = MagicMock(platform_post_id="x", platform_url="", response=None)

        def publish(pp, **kwargs):
            # While the first row uploads, the user pulls the second one back.
            if pp.pk == first.pk:
                PlatformPost.objects.filter(pk=second.pk).update(status=PlatformPost.Status.DRAFT)
            return {"success": True}

        with patch.object(PublishEngine, "_publish_platform_post", side_effect=publish) as spy:
            PublishEngine()._process_retries()

        self.assertEqual([call.args[0].pk for call in spy.call_args_list], [first.pk])
        second.refresh_from_db()
        self.assertEqual(second.status, PlatformPost.Status.DRAFT)

    def test_a_retry_waits_for_a_later_schedule(self):
        row = _retrying_row(self.author, self.ws, self.account, scheduled_in=+60 * 24 * 7)
        with patch.object(PublishEngine, "_publish_platform_post") as spy:
            PublishEngine()._process_retries()
        spy.assert_not_called()
        row.refresh_from_db()
        self.assertEqual(row.status, PlatformPost.Status.SCHEDULED)

    def test_a_retry_rescheduled_while_another_row_uploads_is_not_published(self):
        first = _retrying_row(self.author, self.ws, self.account)
        second = _retrying_row(self.author, self.ws, self.account)

        def publish(pp, **kwargs):
            if pp.pk == first.pk:
                PlatformPost.objects.filter(pk=second.pk).update(scheduled_at=timezone.now() + timedelta(days=7))
            return {"success": True}

        with patch.object(PublishEngine, "_publish_platform_post", side_effect=publish) as spy:
            PublishEngine()._process_retries()

        self.assertEqual([call.args[0].pk for call in spy.call_args_list], [first.pk])
        second.refresh_from_db()
        self.assertEqual(second.status, PlatformPost.Status.SCHEDULED)

    def test_due_snapshot_rescheduled_before_group_claim_is_not_published(self):
        row = _retrying_row(self.author, self.ws, self.account)
        due = PublishEngine()._get_due_platform_posts()
        PlatformPost.objects.filter(pk=row.pk).update(scheduled_at=timezone.now() + timedelta(days=7))

        with patch.object(PublishEngine, "_publish_platform_post") as publish:
            claimed = PublishEngine()._publish_post_group(row.post, due)

        self.assertFalse(claimed)
        publish.assert_not_called()
        row.refresh_from_db()
        self.assertEqual(row.status, PlatformPost.Status.SCHEDULED)

    def test_due_snapshot_with_new_backoff_before_group_claim_is_not_published(self):
        row = _retrying_row(self.author, self.ws, self.account)
        due = PublishEngine()._get_due_platform_posts()
        PlatformPost.objects.filter(pk=row.pk).update(next_retry_at=timezone.now() + timedelta(hours=1))

        with patch.object(PublishEngine, "_publish_platform_post") as publish:
            claimed = PublishEngine()._publish_post_group(row.post, due)

        self.assertFalse(claimed)
        publish.assert_not_called()


class TenantGuardTests(TestCase):
    def test_a_child_on_another_workspaces_channel_is_never_due(self):
        author, ws, account = _world()
        other_ws = Workspace.objects.create(organization=ws.organization, name="Other")
        when = timezone.now() - timedelta(minutes=1)
        post = Post.objects.create(workspace=other_ws, caption="hi", author=author, scheduled_at=when)
        PlatformPost.objects.create(
            post=post, social_account=account, status=PlatformPost.Status.SCHEDULED, scheduled_at=when
        )
        self.assertEqual(PublishEngine()._get_due_platform_posts(), [])


class RateLimitRetryTests(TestCase):
    def test_provider_retry_after_is_honored(self):
        author, ws, account = _world()
        pp = _retrying_row(author, ws, account)
        pp.status = PlatformPost.Status.PUBLISHING
        pp.save(update_fields=["status"])
        before = timezone.now()
        with patch.object(PublishEngine, "_dispatch_to_provider", side_effect=RateLimitError("wait", retry_after=7200)):
            PublishEngine()._publish_platform_post(pp)
        pp.refresh_from_db()
        self.assertGreaterEqual(pp.next_retry_at, before + timedelta(seconds=7200))

    def test_the_retry_waits_for_the_window_to_reset(self):
        author, ws, account = _world()
        resets_at = timezone.now() + timedelta(hours=6)
        RateLimitState.objects.create(
            social_account=account, platform=account.platform, requests_remaining=0, window_resets_at=resets_at
        )
        when = timezone.now() - timedelta(minutes=1)
        post = Post.objects.create(workspace=ws, caption="hi", author=author, scheduled_at=when)
        pp = PlatformPost.objects.create(
            post=post, social_account=account, status=PlatformPost.Status.PUBLISHING, scheduled_at=when
        )
        with patch("apps.publisher.engine._provider_and_access_token", return_value=(MagicMock(), "tok")):
            PublishEngine()._publish_platform_post(pp)
        pp.refresh_from_db()
        self.assertEqual(pp.status, PlatformPost.Status.SCHEDULED)
        self.assertGreaterEqual(pp.next_retry_at, resets_at)


class AcceptedPublishBookkeepingTests(TestCase):
    def setUp(self):
        author, ws, account = _world()
        self.pp = _retrying_row(author, ws, account)
        self.pp.status = PlatformPost.Status.PUBLISHING
        self.pp.save(update_fields=["status"])
        self.result = {"success": True, "platform_post_id": "live-post"}

    def test_a_log_failure_cannot_requeue_a_live_post(self):
        with (
            patch.object(PublishEngine, "_dispatch_to_provider", return_value=self.result),
            patch("apps.publisher.engine.PublishLog.objects.create", side_effect=RuntimeError("log write failed")),
            self.assertLogs("apps.publisher.engine", level="ERROR"),
        ):
            result = PublishEngine()._publish_platform_post(self.pp)
        self.assertTrue(result["success"])
        self.pp.refresh_from_db()
        self.assertEqual(self.pp.status, PlatformPost.Status.PUBLISHED)
        self.assertIsNone(self.pp.next_retry_at)

    def test_a_rate_limit_save_failure_cannot_requeue_a_live_post(self):
        with (
            patch.object(PublishEngine, "_dispatch_to_provider", return_value=self.result),
            patch.object(PublishEngine, "_update_rate_limit", side_effect=RuntimeError("state write failed")),
            self.assertLogs("apps.publisher.engine", level="ERROR"),
        ):
            PublishEngine()._publish_platform_post(self.pp)
        self.pp.refresh_from_db()
        self.assertEqual(self.pp.status, PlatformPost.Status.PUBLISHED)
        self.assertIsNone(self.pp.next_retry_at)

    def test_a_failed_publish_save_is_left_for_recovery_without_resending(self):
        with (
            patch.object(PublishEngine, "_dispatch_to_provider", return_value=self.result),
            patch.object(self.pp, "save", side_effect=RuntimeError("publish write failed")),
            patch.object(PublishEngine, "_schedule_retry") as retry,
            self.assertLogs("apps.publisher.engine", level="ERROR"),
        ):
            result = PublishEngine()._publish_platform_post(self.pp)
        self.assertTrue(result["success"])
        retry.assert_not_called()
        self.pp.refresh_from_db()
        self.assertEqual(self.pp.status, PlatformPost.Status.PUBLISHING)


class UnknownPublishOutcomeTests(TestCase):
    def setUp(self):
        author, ws, account = _world()
        self.pp = _retrying_row(author, ws, account)
        self.pp.status = PlatformPost.Status.PUBLISHING
        self.pp.save(update_fields=["status"])
        self.provider = MagicMock()
        self.provider.supported_post_types = [PostType.TEXT]
        self.provider.needs_local_media = False
        self.provider.publish_is_async = False

    def _publish_with(self, error):
        self.provider.publish_post.side_effect = error
        with patch("apps.publisher.engine._provider_and_access_token", return_value=(self.provider, "token")):
            return PublishEngine()._publish_platform_post(self.pp)

    def _assert_unknown(self, error):
        result = self._publish_with(error)
        self.assertTrue(result["outcome_unknown"])
        self.pp.refresh_from_db()
        self.assertEqual(self.pp.status, PlatformPost.Status.FAILED)
        self.assertIsNone(self.pp.next_retry_at)
        self.assertIn("Check the account", self.pp.publish_error)
        self.assertIn(str(error), PublishLog.objects.get(platform_post=self.pp).error_message)
        PublishEngine()._process_retries()
        self.provider.publish_post.assert_called_once()

    def test_timeout_during_external_publish_does_not_resend(self):
        self._assert_unknown(httpx.ReadTimeout("response lost after submission"))

    def test_server_error_during_external_publish_does_not_resend(self):
        self._assert_unknown(APIError("server failed after submission", status_code=503))

    def test_rate_limit_rejection_keeps_the_safe_retry(self):
        before = timezone.now()
        result = self._publish_with(RateLimitError("write rejected", retry_after=600))
        self.assertNotIn("outcome_unknown", result)
        self.pp.refresh_from_db()
        self.assertEqual(self.pp.status, PlatformPost.Status.SCHEDULED)
        self.assertGreaterEqual(self.pp.next_retry_at, before + timedelta(seconds=600))

    def test_definitive_client_error_keeps_the_existing_retry_policy(self):
        result = self._publish_with(APIError("write rejected", status_code=400))
        self.assertNotIn("outcome_unknown", result)
        self.pp.refresh_from_db()
        self.assertEqual(self.pp.status, PlatformPost.Status.SCHEDULED)
        self.assertIsNotNone(self.pp.next_retry_at)

    def test_timeout_before_provider_publish_is_safe_to_retry(self):
        with patch("apps.publisher.engine._provider_and_access_token", side_effect=httpx.ReadTimeout("setup failed")):
            result = PublishEngine()._publish_platform_post(self.pp)
        self.assertNotIn("outcome_unknown", result)
        self.provider.publish_post.assert_not_called()
        self.pp.refresh_from_db()
        self.assertEqual(self.pp.status, PlatformPost.Status.SCHEDULED)


class ExtraMediaScopeTests(TestCase):
    def setUp(self):
        author, self.ws, account = _world()
        self.pp = _retrying_row(author, self.ws, account)
        self.pp.status = PlatformPost.Status.PUBLISHING
        self.pp.save(update_fields=["status"])
        self.provider = MagicMock()
        self.provider.supported_post_types = [PostType.TEXT]
        self.provider.needs_local_media = False
        self.provider.publish_is_async = False
        self.provider.publish_post.return_value = PublishResult(platform_post_id="published")

    def _asset(self, *, workspace=None, organization=None):
        from apps.media_library.models import MediaAsset

        return MediaAsset.objects.create(
            workspace=workspace,
            organization=organization,
            filename="cover.jpg",
            file="media_library/cover.jpg",
            media_type="image",
        )

    def _publish_asset(self, asset, key):
        self.pp.platform_extra = {key: str(asset.id)}
        with (
            patch("apps.publisher.engine._provider_and_access_token", return_value=(self.provider, "token")),
            patch("apps.publisher.engine.download_to_path") as download,
        ):
            result = PublishEngine()._publish_platform_post(self.pp)
        return result, download

    def test_foreign_workspace_thumbnail_is_rejected_before_provider_io(self):
        other = Workspace.objects.create(organization=self.ws.organization, name="Other")
        asset = self._asset(workspace=other, organization=self.ws.organization)
        result, download = self._publish_asset(asset, "thumbnail_asset_id")
        self.assertFalse(result["success"])
        download.assert_not_called()
        self.provider.publish_post.assert_not_called()
        self.pp.refresh_from_db()
        self.assertEqual(self.pp.status, PlatformPost.Status.FAILED)

    def test_foreign_workspace_cover_is_rejected_before_provider_io(self):
        other = Workspace.objects.create(organization=self.ws.organization, name="Other")
        asset = self._asset(workspace=other, organization=self.ws.organization)
        result, download = self._publish_asset(asset, "cover_image_asset_id")
        self.assertFalse(result["success"])
        download.assert_not_called()
        self.provider.publish_post.assert_not_called()

    def test_shared_asset_from_another_org_is_rejected(self):
        other_org = Organization.objects.create(name="Other org")
        asset = self._asset(organization=other_org)
        result, download = self._publish_asset(asset, "thumbnail_asset_id")
        self.assertFalse(result["success"])
        download.assert_not_called()
        self.provider.publish_post.assert_not_called()

    def test_cover_without_a_thumbnail_can_use_workspace_media(self):
        asset = self._asset(workspace=self.ws, organization=self.ws.organization)
        result, download = self._publish_asset(asset, "cover_image_asset_id")
        self.assertTrue(result["success"])
        download.assert_called_once()
        content = self.provider.publish_post.call_args.args[1]
        self.assertIn("cover_image_file", content.extra)

    def test_shared_org_media_remains_available_for_thumbnails(self):
        asset = self._asset(organization=self.ws.organization)
        result, download = self._publish_asset(asset, "thumbnail_asset_id")
        self.assertTrue(result["success"])
        download.assert_called_once()
        content = self.provider.publish_post.call_args.args[1]
        self.assertIn("thumbnail_file", content.extra)
