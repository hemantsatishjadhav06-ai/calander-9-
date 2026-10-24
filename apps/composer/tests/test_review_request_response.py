"""What save_post tells the composer when Schedule, Queue or Publish now cannot schedule.

Review findings pinned here:
- On a new post, a Schedule that became a review request answered without X-Post-Edit-Url. The
  composer now stays open in that case, so it kept the create URL and the next autosave made a
  second copy of the post.
- The composer guessed "sent for approval, the time is kept as a proposal" from the channel
  statuses alone. It said so after a Schedule that submitted nothing and cleared the proposal.
  The server now says what it did in X-Sent-For-Review.
- A Schedule on a post whose every channel waits for approval (or is on hold) moved no channel,
  yet stamped the post's time, cleared its proposal and answered as if it had worked.
"""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.composer.models import PlatformPost, Post, PostMedia
from apps.media_library.models import MediaAsset
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


class SentForReviewHeaderTests(ReviewRequestResponseBase):
    def test_a_schedule_sent_for_review_keeps_the_picked_time_as_the_proposal(self):
        self.client.force_login(self.contributor)
        response = self._save(action="schedule", scheduled_date=WHEN, scheduled_time="10:00")
        self.assertEqual(response["X-Sent-For-Review"], "proposal")
        post = Post.objects.get()
        self.assertIsNone(post.scheduled_at)
        self.assertIsNotNone(post.proposed_publish_at)

    def test_a_queue_sent_for_review_mentions_no_time(self):
        self.client.force_login(self.contributor)
        response = self._save(action="add_to_queue")
        self.assertEqual(response["X-Sent-For-Review"], "sent")

    def test_a_schedule_whose_time_was_not_kept_mentions_no_time(self):
        # A post that still carries an old schedule keeps it; the picked time is not a proposal.
        self.client.force_login(self.contributor)
        post = Post.objects.create(
            workspace=self.ws,
            author=self.contributor,
            caption="Launch day",
            scheduled_at=timezone.now() + timedelta(days=3),
        )
        PlatformPost.objects.create(post=post, social_account=self.account, status=PlatformPost.Status.DRAFT)
        response = self._save(post, action="schedule", scheduled_date=WHEN, scheduled_time="10:00")
        self.assertEqual(response["X-Sent-For-Review"], "sent")
        post.refresh_from_db()
        self.assertIsNone(post.proposed_publish_at)

    def test_a_review_request_that_submitted_nothing_says_so(self):
        self.client.force_login(self.contributor)
        post = Post.objects.create(workspace=self.ws, author=self.contributor, caption="Launch day")
        PlatformPost.objects.create(post=post, social_account=self.account, status=PlatformPost.Status.PENDING_REVIEW)
        response = self._save(post, action="schedule", scheduled_date=WHEN, scheduled_time="10:00")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["X-Sent-For-Review"], "not_sent")

    def test_a_real_schedule_and_an_explicit_submission_carry_no_header(self):
        self.client.force_login(self.owner)
        response = self._save(action="schedule", caption="scheduled", scheduled_date=WHEN, scheduled_time="10:00")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(Post.objects.get(caption="scheduled").platform_posts.get().status, "scheduled")
        self.assertNotIn("X-Sent-For-Review", response)
        response = self._save(action="submit_for_approval", caption="submitted")
        self.assertEqual(response.status_code, 204)
        self.assertNotIn("X-Sent-For-Review", response)


class ScheduleWithNothingToMoveTests(ReviewRequestResponseBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.owner)
        self.proposal = timezone.now() + timedelta(days=2)
        self.post = Post.objects.create(
            workspace=self.ws, author=self.owner, caption="Original", proposed_publish_at=self.proposal
        )

    def _child(self, status, account=None):
        return PlatformPost.objects.create(post=self.post, social_account=account or self.account, status=status)

    def test_a_schedule_with_every_channel_in_review_is_refused_and_writes_nothing(self):
        for status in (
            PlatformPost.Status.PENDING_REVIEW,
            PlatformPost.Status.PENDING_CLIENT,
            PlatformPost.Status.ON_HOLD,
        ):
            with self.subTest(status=status):
                PlatformPost.objects.filter(post=self.post).delete()
                child = self._child(status)
                response = self._save(
                    self.post, action="schedule", caption="Edited", scheduled_date=WHEN, scheduled_time="10:00"
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("Nothing was scheduled", response.json()["errors"]["schedule"])
                self.post.refresh_from_db()
                self.assertIsNone(self.post.scheduled_at)
                self.assertEqual(self.post.proposed_publish_at, self.proposal)
                self.assertEqual(self.post.caption, "Original")
                child.refresh_from_db()
                self.assertEqual(child.status, status)
                self.assertIsNone(child.scheduled_at)

    def test_a_refused_schedule_keeps_the_media_waiting_to_be_attached(self):
        self._child(PlatformPost.Status.PENDING_REVIEW)
        asset = MediaAsset.objects.create(
            organization=self.org,
            workspace=self.ws,
            uploaded_by=self.owner,
            file="tests/pending.png",
            filename="pending.png",
            media_type="image",
            mime_type="image/png",
            file_size=1,
        )
        session = self.client.session
        session[f"pending_media_{self.ws.id}"] = [str(asset.id)]
        session.save()
        response = self._save(self.post, action="schedule", scheduled_date=WHEN, scheduled_time="10:00")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(PostMedia.objects.filter(post=self.post).exists())
        self.assertEqual(self.client.session[f"pending_media_{self.ws.id}"], [str(asset.id)])

    def test_a_schedule_that_moves_some_channel_still_goes_ahead(self):
        other = SocialAccount.objects.create(
            workspace=self.ws,
            platform="bluesky",
            account_platform_id="did:2",
            account_name="Other",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )
        waiting = self._child(PlatformPost.Status.PENDING_REVIEW)
        draft = self._child(PlatformPost.Status.DRAFT, account=other)
        response = self._save(
            self.post,
            action="schedule",
            selected_accounts=f"{self.account.id},{other.id}",
            scheduled_date=WHEN,
            scheduled_time="10:00",
        )
        self.assertEqual(response.status_code, 204)
        waiting.refresh_from_db()
        draft.refresh_from_db()
        self.assertEqual(waiting.status, PlatformPost.Status.PENDING_REVIEW)
        self.assertEqual(draft.status, PlatformPost.Status.SCHEDULED)
