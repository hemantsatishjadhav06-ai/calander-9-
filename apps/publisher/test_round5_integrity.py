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

from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.composer.models import PlatformPost, Post
from apps.organizations.models import Organization
from apps.publisher.engine import PublishEngine
from apps.publisher.models import RateLimitState
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


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
