"""A post with no channel is a draft, never a scheduled post.

With zero channels connected the composer disables every action except Save
Draft, so this is the first-run path. Save Draft used to create a Post with no
PlatformPost children that no list in the product could show (the Drafts query
inner-joined on platform_posts), and Schedule / Publish now — disabled only
client-side — wrote a post that read "scheduled for <date>" and could never
fire, because the publisher polls PlatformPost rows and there were none.
"""

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.composer.models import PlatformPost, Post
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


class NoChannelGuardBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="owner@example.com", password="pw", name="Owner", tos_accepted_at=timezone.now()
        )
        self.org = Organization.objects.create(name="Org")
        self.ws = Workspace.objects.create(organization=self.org, name="WS")
        OrgMembership.objects.create(user=self.user, organization=self.org, org_role="owner")
        WorkspaceMembership.objects.create(
            user=self.user, workspace=self.ws, workspace_role=WorkspaceMembership.WorkspaceRole.OWNER
        )
        self.client.force_login(self.user)
        self.save_url = reverse("composer:save_post", kwargs={"workspace_id": self.ws.id})
        self.drafts_url = reverse("composer:drafts_list", kwargs={"workspace_id": self.ws.id})


class NothingConnectedTests(NoChannelGuardBase):
    def test_schedule_with_no_channel_is_refused_and_nothing_is_written(self):
        response = self.client.post(
            self.save_url,
            {"action": "schedule", "caption": "hi", "scheduled_date": "2030-01-01", "scheduled_time": "10:00"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("channels", response.json()["errors"])
        self.assertEqual(Post.objects.count(), 0)

    def test_publish_now_with_no_channel_is_refused(self):
        response = self.client.post(self.save_url, {"action": "publish_now", "caption": "hi"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Post.objects.count(), 0)

    def test_queue_with_no_channel_names_the_real_cause(self):
        """Used to say 'No active queue found', blaming the queue."""
        response = self.client.post(self.save_url, {"action": "add_to_queue", "caption": "hi"})
        self.assertEqual(response.status_code, 400)
        message = response.json()["errors"]["channels"]
        self.assertIn("No channels are connected", message)

    def test_a_draft_with_no_channel_is_saved_and_is_visible(self):
        response = self.client.post(self.save_url, {"action": "save_draft", "caption": "My very first draft"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Post.objects.count(), 1)
        self.assertEqual(PlatformPost.objects.count(), 0)

        drafts = self.client.get(self.drafts_url)
        self.assertContains(drafts, "My very first draft")

    def test_the_composer_tells_you_where_to_connect(self):
        response = self.client.get(reverse("composer:compose", kwargs={"workspace_id": self.ws.id}))
        self.assertContains(response, "Connect a channel")
        self.assertContains(response, reverse("social_accounts:connect", kwargs={"workspace_id": self.ws.id}))


class ChannelsConnectedButNoneSelectedTests(NoChannelGuardBase):
    def setUp(self):
        super().setUp()
        self.account = SocialAccount.objects.create(
            workspace=self.ws,
            platform="bluesky",
            account_platform_id="did",
            account_name="acct",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )

    def test_schedule_with_none_ticked_is_refused_with_a_select_message(self):
        response = self.client.post(
            self.save_url,
            {"action": "schedule", "caption": "hi", "scheduled_date": "2030-01-01", "scheduled_time": "10:00"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Select at least one channel", response.json()["errors"]["channels"])
        self.assertEqual(Post.objects.count(), 0)

    def test_deselecting_every_channel_on_a_scheduled_post_is_refused(self):
        """Editing with an empty selection would delete every child and strand the post."""
        post = Post.objects.create(workspace=self.ws, author=self.user, caption="live")
        pp = PlatformPost.objects.create(post=post, social_account=self.account, status=PlatformPost.Status.SCHEDULED)
        url = reverse("composer:save_post_edit", kwargs={"workspace_id": self.ws.id, "post_id": post.id})
        response = self.client.post(
            url,
            {"action": "schedule", "caption": "live", "scheduled_date": "2030-01-01", "scheduled_time": "10:00"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertTrue(PlatformPost.objects.filter(pk=pp.pk).exists())

    def test_scheduling_with_a_channel_still_works(self):
        response = self.client.post(
            self.save_url,
            {
                "action": "schedule",
                "caption": "hi",
                "scheduled_date": "2030-01-01",
                "scheduled_time": "10:00",
                "selected_accounts": str(self.account.id),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PlatformPost.objects.filter(status=PlatformPost.Status.SCHEDULED).count(), 1)
