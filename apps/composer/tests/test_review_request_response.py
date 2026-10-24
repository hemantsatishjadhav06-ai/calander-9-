"""What save_post tells the composer when Schedule, Queue or Publish now cannot schedule.

Review findings pinned here:
- On a new post, a Schedule that became a review request answered without X-Post-Edit-Url. The
  composer now stays open in that case, so it kept the create URL and the next autosave made a
  second copy of the post.
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

WR = WorkspaceMembership.WorkspaceRole
WHEN = "2030-01-01"


class ReviewRequestResponseBase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Org")
        self.ws = Workspace.objects.create(organization=self.org, name="WS")
        self.owner = self._member("owner@example.com", WR.OWNER, org_role="owner")
        self.contributor = self._member("contributor@example.com", WR.CONTRIBUTOR)
        self.account = SocialAccount.objects.create(
            workspace=self.ws,
            platform="bluesky",
            account_platform_id="did:1",
            account_name="Account",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )
        self.kw = {"workspace_id": self.ws.id}

    def _member(self, email, role, org_role="member"):
        user = User.objects.create_user(email=email, password="pw", tos_accepted_at=timezone.now())
        OrgMembership.objects.create(user=user, organization=self.org, org_role=org_role)
        WorkspaceMembership.objects.create(user=user, workspace=self.ws, workspace_role=role)
        return user

    def _save(self, post=None, **data):
        url = (
            reverse("composer:save_post_edit", kwargs={**self.kw, "post_id": post.id})
            if post
            else reverse("composer:save_post", kwargs=self.kw)
        )
        payload = {"caption": "Launch day", "selected_accounts": str(self.account.id), **data}
        return self.client.post(url, payload, HTTP_HX_REQUEST="true")

    def _edit_url(self, post):
        return reverse("composer:compose_edit", kwargs={**self.kw, "post_id": post.id})


class NewPostReviewRequestTests(ReviewRequestResponseBase):
    def test_a_new_post_schedule_that_becomes_a_review_request_returns_the_edit_url(self):
        self.client.force_login(self.contributor)
        response = self._save(action="schedule", scheduled_date=WHEN, scheduled_time="10:00")
        self.assertEqual(response.status_code, 204)
        post = Post.objects.get()
        self.assertEqual(post.platform_posts.get().status, PlatformPost.Status.PENDING_REVIEW)
        self.assertEqual(response["X-Post-Edit-Url"], self._edit_url(post))

    def test_every_review_request_answer_returns_the_edit_url(self):
        self.ws.require_dashboard_approval = True
        self.ws.save(update_fields=["require_dashboard_approval"])
        self.client.force_login(self.owner)
        for action in ("schedule", "publish_now", "add_to_queue", "add_to_queue_priority", "submit_for_approval"):
            with self.subTest(action=action):
                response = self._save(action=action, caption=action, scheduled_date=WHEN, scheduled_time="10:00")
                self.assertEqual(response.status_code, 204)
                post = Post.objects.get(caption=action)
                self.assertEqual(post.platform_posts.get().status, PlatformPost.Status.PENDING_REVIEW)
                self.assertEqual(response["X-Post-Edit-Url"], self._edit_url(post))

    def test_a_resubmission_returns_the_edit_url(self):
        self.client.force_login(self.owner)
        post = Post.objects.create(workspace=self.ws, author=self.owner, caption="Launch day")
        PlatformPost.objects.create(
            post=post, social_account=self.account, status=PlatformPost.Status.CHANGES_REQUESTED
        )
        response = self._save(post, action="resubmit_for_approval")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(post.platform_posts.get().status, PlatformPost.Status.PENDING_REVIEW)
        self.assertEqual(response["X-Post-Edit-Url"], self._edit_url(post))
