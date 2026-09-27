"""Round-5 data-integrity findings on the composer, calendar and inbox pages.

- Autosave accepted any account UUID, so a crafted request could bind another
  workspace's channel to a post; Schedule then published through it.
- Deleting a child (or the whole post) mid-publish let the engine's later
  writes re-insert the deleted row, or publish a post the user removed.
- The chip endpoint accepted engine-only targets and moves out of publishing.
- A non-publisher's "Schedule" committed a time; it now goes to review.
- Pressing Schedule lifted a client hold through the draft hop.
- Recurrence rules were written by the composer and consumed by nothing.
- The saved-replies "New"/"edit" links rendered a page with no form.
"""

from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.calendar.models import RecurrenceRule
from apps.calendar.tasks import _compute_recurrence_dates, generate_recurring_posts
from apps.composer.models import PlatformPost, Post
from apps.inbox.models import SavedReply
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace

WR = WorkspaceMembership.WorkspaceRole


def _user(email):
    user = User.objects.create_user(email=email, password="pw", name="u", tos_accepted_at=timezone.now())
    auto = list(OrgMembership.objects.filter(user=user).values_list("organization_id", flat=True))
    WorkspaceMembership.objects.filter(user=user).delete()
    OrgMembership.objects.filter(user=user).delete()
    Organization.objects.filter(id__in=auto).delete()
    return user


def _account(ws, pid="did:1"):
    return SocialAccount.objects.create(
        workspace=ws,
        platform="bluesky",
        account_platform_id=pid,
        account_name=pid,
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
    )


class ComposerBase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Org")
        self.ws = Workspace.objects.create(organization=self.org, name="WS")
        self.owner = _user("owner@example.com")
        OrgMembership.objects.create(user=self.owner, organization=self.org, org_role="owner")
        WorkspaceMembership.objects.create(user=self.owner, workspace=self.ws, workspace_role=WR.OWNER)
        self.account = _account(self.ws)
        self.client.force_login(self.owner)

    def _post(self, status=PlatformPost.Status.SCHEDULED, when=None):
        when = when or (timezone.now() + timedelta(hours=1))
        post = Post.objects.create(workspace=self.ws, author=self.owner, caption="c", scheduled_at=when)
        pp = PlatformPost.objects.create(post=post, social_account=self.account, status=status, scheduled_at=when)
        return post, pp


class AutosaveScopingTests(ComposerBase):
    def test_another_workspaces_channel_is_never_bound(self):
        other_org = Organization.objects.create(name="Other")
        other_ws = Workspace.objects.create(organization=other_org, name="Other WS")
        foreign = _account(other_ws, "did:foreign")
        post, _ = self._post(status=PlatformPost.Status.DRAFT)

        url = reverse("composer:autosave_edit", kwargs={"workspace_id": self.ws.id, "post_id": post.id})
        response = self.client.post(url, {"caption": "c", "selected_accounts": f"{self.account.id},{foreign.id}"})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(PlatformPost.objects.filter(post=post, social_account=foreign).exists())
        self.assertTrue(PlatformPost.objects.filter(post=post, social_account=self.account).exists())

    def test_an_unknown_uuid_is_ignored_not_a_500(self):
        post, _ = self._post(status=PlatformPost.Status.DRAFT)
        url = reverse("composer:autosave_edit", kwargs={"workspace_id": self.ws.id, "post_id": post.id})
        response = self.client.post(url, {"caption": "c", "selected_accounts": "00000000-0000-0000-0000-000000000001"})
        self.assertEqual(response.status_code, 200)


class DeleteProtectsInFlightTests(ComposerBase):
    def test_a_publishing_child_cannot_be_deleted(self):
        post, pp = self._post(status=PlatformPost.Status.PUBLISHING)
        url = reverse("composer:post_delete", kwargs={"workspace_id": self.ws.id, "post_id": post.id})
        self.assertEqual(self.client.post(f"{url}?account={self.account.id}").status_code, 409)
        self.assertEqual(self.client.post(url).status_code, 409)
        self.assertTrue(PlatformPost.objects.filter(pk=pp.pk).exists())

    def test_a_scheduled_one_still_can(self):
        post, pp = self._post()
        url = reverse("composer:post_delete", kwargs={"workspace_id": self.ws.id, "post_id": post.id})
        self.assertEqual(self.client.post(url).status_code, 204)
        self.assertFalse(Post.objects.filter(pk=post.pk).exists())


class TransitionEndpointTests(ComposerBase):
    def _transition(self, post, pp, target):
        url = reverse(
            "composer:transition_platform_post",
            kwargs={"workspace_id": self.ws.id, "post_id": post.id, "platform_post_id": pp.id},
        )
        return self.client.post(url, {"target_status": target})

    def test_engine_only_targets_are_refused(self):
        post, pp = self._post()
        for target in ("published", "publishing", "failed"):
            with self.subTest(target=target):
                self.assertEqual(self._transition(post, pp, target).status_code, 400)
        pp.refresh_from_db()
        self.assertEqual(pp.status, PlatformPost.Status.SCHEDULED)

    def test_nothing_moves_out_of_publishing(self):
        post, pp = self._post(status=PlatformPost.Status.PUBLISHING)
        self.assertEqual(self._transition(post, pp, "scheduled").status_code, 409)
        self.assertEqual(self._transition(post, pp, "draft").status_code, 409)
        pp.refresh_from_db()
        self.assertEqual(pp.status, PlatformPost.Status.PUBLISHING)

    def test_scheduling_a_child_pins_its_time(self):
        post, pp = self._post(status=PlatformPost.Status.APPROVED)
        PlatformPost.objects.filter(pk=pp.pk).update(scheduled_at=None)
        self.assertEqual(self._transition(post, pp, "scheduled").status_code, 200)
        pp.refresh_from_db()
        self.assertEqual(pp.status, PlatformPost.Status.SCHEDULED)
        self.assertEqual(pp.scheduled_at, post.scheduled_at)


class ScheduleGateTests(ComposerBase):
    def test_a_contributor_schedule_becomes_a_review_request(self):
        contributor = _user("c@example.com")
        OrgMembership.objects.create(user=contributor, organization=self.org, org_role="member")
        WorkspaceMembership.objects.create(user=contributor, workspace=self.ws, workspace_role=WR.CONTRIBUTOR)
        self.client.force_login(contributor)
        response = self.client.post(
            reverse("composer:save_post", kwargs={"workspace_id": self.ws.id}),
            {
                "action": "schedule",
                "caption": "hi",
                "scheduled_date": "2030-01-01",
                "scheduled_time": "10:00",
                "selected_accounts": str(self.account.id),
            },
        )
        self.assertIn(response.status_code, (200, 204, 302))
        post = Post.objects.get()
        statuses = set(post.platform_posts.values_list("status", flat=True))
        self.assertNotIn(PlatformPost.Status.SCHEDULED, statuses)
        self.assertEqual(statuses, {PlatformPost.Status.PENDING_REVIEW})

    def test_schedule_does_not_lift_a_client_hold(self):
        post, pp = self._post(status=PlatformPost.Status.ON_HOLD)
        response = self.client.post(
            reverse("composer:save_post_edit", kwargs={"workspace_id": self.ws.id, "post_id": post.id}),
            {
                "action": "schedule",
                "caption": "c",
                "scheduled_date": "2030-01-01",
                "scheduled_time": "10:00",
                "selected_accounts": str(self.account.id),
            },
        )
        self.assertIn(response.status_code, (200, 204, 302, 400))
        pp.refresh_from_db()
        self.assertEqual(pp.status, PlatformPost.Status.ON_HOLD)


class RecurrenceTests(ComposerBase):
    def test_the_rule_is_registered_and_generates_each_date_once(self):
        from background_task.models import Task

        self.assertTrue(Task.objects.filter(verbose_name="run_recurrence_cycle").exists())

        post, _ = self._post(when=timezone.now() + timedelta(days=1))
        rule = RecurrenceRule.objects.create(post=post, frequency="weekly", interval=1)

        generate_recurring_posts()
        first_count = Post.objects.exclude(pk=post.pk).count()
        self.assertGreater(first_count, 0)
        clone = Post.objects.exclude(pk=post.pk).order_by("scheduled_at").first()
        self.assertEqual(clone.platform_posts.get().status, PlatformPost.Status.SCHEDULED)

        # Editing the caption and deleting an occurrence must not regenerate it.
        post.caption = "edited"
        post.save(update_fields=["caption"])
        clone.delete()
        generate_recurring_posts()
        self.assertEqual(Post.objects.exclude(pk=post.pk).count(), first_count - 1)
        rule.refresh_from_db()
        self.assertEqual(len(rule.generated_dates), first_count)

    def test_a_held_source_generates_nothing(self):
        post, _ = self._post(status=PlatformPost.Status.ON_HOLD, when=timezone.now() + timedelta(days=1))
        RecurrenceRule.objects.create(post=post, frequency="daily", interval=1)
        generate_recurring_posts()
        self.assertEqual(Post.objects.exclude(pk=post.pk).count(), 0)

    def test_monthly_dates_do_not_drift_after_february(self):
        dates = _compute_recurrence_dates(date(2026, 1, 31), "monthly", 1, date(2026, 6, 30))
        self.assertEqual(
            dates, [date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30), date(2026, 5, 31), date(2026, 6, 30)]
        )


class SavedRepliesPageTests(ComposerBase):
    def test_the_new_and_edit_links_render_the_form_and_the_list(self):
        existing = SavedReply.objects.create(workspace=self.ws, title="Thanks!", body="ty", created_by=self.owner)
        new = self.client.get(reverse("inbox:saved_reply_create", kwargs={"workspace_id": self.ws.id}))
        self.assertContains(new, "id_title")
        self.assertContains(new, "Thanks!")
        edit = self.client.get(
            reverse("inbox:saved_reply_edit", kwargs={"workspace_id": self.ws.id, "reply_id": existing.id})
        )
        self.assertContains(edit, "id_title")
        self.assertContains(edit, "Thanks!")


class VersionNumberingTests(ComposerBase):
    def test_a_gap_does_not_break_the_next_save(self):
        from apps.composer.models import PostVersion
        from apps.composer.views import _save_version

        post, _ = self._post()
        _save_version(post, self.owner)
        PostVersion.objects.filter(post=post).update(version_number=5)
        _save_version(post, self.owner)
        self.assertEqual(sorted(PostVersion.objects.filter(post=post).values_list("version_number", flat=True)), [5, 6])
