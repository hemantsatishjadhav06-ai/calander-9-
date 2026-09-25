"""An expired token fails the post at once and marks the account.

Measured before this: a ``TokenExpiredError`` was retried three times over
half an hour — an error a retry can never fix — after which the post failed
with "Try again, or reconnect the account if it keeps happening" while the
channel still read Connected. The publisher knew the token was dead and asked
the user to guess.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.test import TransactionTestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.composer.models import PlatformPost, Post
from apps.organizations.models import Organization
from apps.publisher.engine import PublishEngine
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace
from providers.exceptions import TokenExpiredError


class TokenExpiredFlagsAccountTest(TransactionTestCase):
    def setUp(self):
        self.author = User.objects.create_user(
            email="a@example.com", password="x", name="A", tos_accepted_at=timezone.now()
        )
        org = Organization.objects.create(name="Org")
        self.ws = Workspace.objects.create(organization=org, name="WS")
        self.account = SocialAccount.objects.create(
            workspace=self.ws,
            platform="bluesky",
            account_platform_id="did:plc:1",
            account_name="acct",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )
        when = timezone.now() - timedelta(minutes=1)
        post = Post.objects.create(workspace=self.ws, caption="hi", author=self.author, scheduled_at=when)
        self.pp = PlatformPost.objects.create(
            post=post, social_account=self.account, status=PlatformPost.Status.SCHEDULED, scheduled_at=when
        )

    def _cycle_with(self, exc):
        provider = MagicMock()
        provider.publish_post.side_effect = exc
        with patch("apps.publisher.engine._provider_and_access_token", return_value=(provider, "tok")):
            PublishEngine().poll_and_publish()
        self.pp.refresh_from_db()
        self.account.refresh_from_db()

    def test_fails_immediately_and_marks_the_account(self):
        self._cycle_with(TokenExpiredError("token dead", status_code=401))

        self.assertEqual(self.pp.status, PlatformPost.Status.FAILED)
        self.assertEqual(self.pp.retry_count, 0, "an auth failure is not something a retry can fix")
        self.assertEqual(self.account.connection_status, SocialAccount.ConnectionStatus.ERROR)
        self.assertIn("Reconnect", self.account.last_error)

    def test_an_ordinary_api_error_still_retries(self):
        """The change is scoped to the token case; transient failures keep their backoff."""
        from providers.exceptions import APIError

        self._cycle_with(APIError("platform hiccup", status_code=500))

        self.assertEqual(self.pp.status, PlatformPost.Status.SCHEDULED)
        self.assertEqual(self.pp.retry_count, 1)
        self.assertEqual(self.account.connection_status, SocialAccount.ConnectionStatus.CONNECTED)
