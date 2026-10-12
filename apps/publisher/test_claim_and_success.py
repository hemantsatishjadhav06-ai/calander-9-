"""Publish claims use current timing; accepted posts are never sent twice."""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.approvals import gate
from apps.composer.models import PlatformPost, Post
from apps.organizations.models import Organization
from apps.publisher.engine import PublishEngine
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


class _PublishFixture(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Org")
        self.workspace = Workspace.objects.create(organization=self.org, name="WS")
        self.account = SocialAccount.objects.create(
            workspace=self.workspace,
            platform="bluesky",
            account_platform_id="did:plc:1",
            account_name="acct",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )
        self.engine = PublishEngine()

    def _scheduled(self, *, retry=False, fallback=False):
        when = timezone.now() - timedelta(minutes=5)
        post = Post.objects.create(workspace=self.workspace, caption="hi", scheduled_at=when)
        return PlatformPost.objects.create(
            post=post,
            social_account=self.account,
            status=PlatformPost.Status.SCHEDULED,
            scheduled_at=None if fallback else when,
            retry_count=1 if retry else 0,
            next_retry_at=when if retry else None,
        )


class PublishClaimTest(_PublishFixture):
    def _assert_group_waits(self, pp, due):
        with patch.object(PublishEngine, "_publish_platform_post") as publish:
            self.assertFalse(self.engine._publish_post_group(pp.post, due))
        publish.assert_not_called()
        pp.refresh_from_db()
        self.assertEqual(pp.status, PlatformPost.Status.SCHEDULED)

    def test_time_moved_after_due_query_waits_for_new_time(self):
        pp = self._scheduled()
        due = self.engine._get_due_platform_posts()
        PlatformPost.objects.filter(pk=pp.pk).update(scheduled_at=timezone.now() + timedelta(days=7))
        self._assert_group_waits(pp, due)

    def test_parent_fallback_time_is_rechecked_under_lock(self):
        pp = self._scheduled(fallback=True)
        due = self.engine._get_due_platform_posts()
        Post.objects.filter(pk=pp.post_id).update(scheduled_at=timezone.now() + timedelta(days=7))
        self._assert_group_waits(pp, due)

    def test_newly_approved_future_time_does_not_publish_early(self):
        pp = self._scheduled()
        self.workspace.require_dashboard_approval = True
        self.workspace.save(update_fields=["require_dashboard_approval"])
        pp.refresh_from_db()
        fingerprint = gate.fingerprint(pp)
        PlatformPost.objects.filter(pk=pp.pk).update(
            approved_fingerprint=fingerprint, approved_publish_at=pp.scheduled_at
        )
        due = self.engine._get_due_platform_posts()
        future = timezone.now() + timedelta(days=7)
        # The approver changed and approved the new time between query and claim.
        PlatformPost.objects.filter(pk=pp.pk).update(scheduled_at=future, approved_publish_at=future)
        self._assert_group_waits(pp, due)

    def test_new_backoff_after_due_query_is_respected(self):
        pp = self._scheduled(retry=True)
        due = self.engine._get_due_platform_posts()
        PlatformPost.objects.filter(pk=pp.pk).update(next_retry_at=timezone.now() + timedelta(hours=1))
        self._assert_group_waits(pp, due)

    def test_changed_account_tenant_is_rechecked_under_lock(self):
        pp = self._scheduled()
        due = self.engine._get_due_platform_posts()
        other = Workspace.objects.create(organization=self.org, name="Other")
        SocialAccount.objects.filter(pk=self.account.pk).update(workspace=other)
        self._assert_group_waits(pp, due)

    def _assert_retry_change_waits(self, change):
        rows = [self._scheduled(retry=True), self._scheduled(retry=True)]
        moved = []

        def publish(pp):
            # The queryset already holds both rows; move the other while this
            # row uploads, preserving scheduled status and retry count.
            other = next(row for row in rows if row.pk != pp.pk)
            change(other)
            moved.append(other)
            return {"success": False}

        with patch.object(PublishEngine, "_publish_platform_post", side_effect=publish) as dispatch:
            self.engine._process_retries()
        self.assertEqual(dispatch.call_count, 1)
        moved[0].refresh_from_db()
        self.assertEqual(moved[0].status, PlatformPost.Status.SCHEDULED)

    def test_retry_time_changed_during_previous_upload_waits(self):
        self._assert_retry_change_waits(
            lambda pp: PlatformPost.objects.filter(pk=pp.pk).update(scheduled_at=timezone.now() + timedelta(days=7))
        )

    def test_retry_backoff_changed_during_previous_upload_waits(self):
        self._assert_retry_change_waits(
            lambda pp: PlatformPost.objects.filter(pk=pp.pk).update(next_retry_at=timezone.now() + timedelta(hours=1))
        )

    def test_retry_account_changed_during_previous_upload_is_not_claimed(self):
        other = Workspace.objects.create(organization=self.org, name="Other")
        account = SocialAccount.objects.create(
            workspace=other, platform="bluesky", account_platform_id="did:plc:other", account_name="other"
        )
        self._assert_retry_change_waits(lambda pp: PlatformPost.objects.filter(pk=pp.pk).update(social_account=account))


class AcceptedPublishTest(_PublishFixture):
    def _publishing(self):
        pp = self._scheduled()
        PlatformPost.objects.filter(pk=pp.pk).update(status=PlatformPost.Status.PUBLISHING)
        pp.refresh_from_db()
        return pp

    def _assert_accepted_not_retried(self, pp, failure_patch, *, asynchronous=False, save_failed=False):
        result = {"success": True, "platform_post_id": "accepted-1", "response": {}}
        if asynchronous:
            result["async_publish"] = True
        with (
            patch.object(PublishEngine, "_dispatch_to_provider", return_value=result) as dispatch,
            patch.object(PublishEngine, "_schedule_retry") as retry,
            failure_patch,
        ):
            self.assertTrue(self.engine._publish_platform_post(pp)["success"])
            self.assertEqual(self.engine._get_due_platform_posts(), [])
            self.engine._process_retries()
        dispatch.assert_called_once()
        retry.assert_not_called()
        pp.refresh_from_db()
        expected = (
            PlatformPost.Status.FAILED
            if save_failed
            else PlatformPost.Status.PUBLISHING
            if asynchronous
            else PlatformPost.Status.PUBLISHED
        )
        self.assertEqual(pp.status, expected)
        self.assertEqual(pp.retry_count, 0)
        self.assertIsNone(pp.next_retry_at)
        if not save_failed:
            self.assertEqual(pp.platform_post_id, "accepted-1")
        else:
            self.assertEqual(pp.platform_extra["_delivery_state"]["kind"], "unknown")

    def test_publish_log_failure_does_not_resubmit_confirmed_post(self):
        self._assert_accepted_not_retried(
            self._publishing(),
            patch("apps.publisher.engine.PublishLog.objects.create", side_effect=RuntimeError("log unavailable")),
        )

    def test_rate_limit_bookkeeping_failure_does_not_resubmit_confirmed_post(self):
        self._assert_accepted_not_retried(
            self._publishing(),
            patch.object(PublishEngine, "_update_rate_limit", side_effect=RuntimeError("state unavailable")),
        )

    def test_async_accepted_post_keeps_its_handle_after_log_failure(self):
        self._assert_accepted_not_retried(
            self._publishing(),
            patch("apps.publisher.engine.PublishLog.objects.create", side_effect=RuntimeError("log unavailable")),
            asynchronous=True,
        )

    def test_accepted_post_with_failed_save_is_left_for_reconciliation(self):
        pp = self._publishing()
        self._assert_accepted_not_retried(
            pp, patch.object(pp, "save", side_effect=RuntimeError("database unavailable")), save_failed=True
        )
