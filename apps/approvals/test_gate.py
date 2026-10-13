"""The approval gate in workspaces that require dashboard approval.

Approval is tied to the exact content and time that will go out; only an
internal approver in the dashboard can give it; edits withdraw it; and the
publisher re-checks it before anything reaches a platform — on the first
attempt, on retries, and once more right before the provider call.
"""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.approvals import gate, services
from apps.approvals.actor import API, DASHBOARD, PORTAL, acting_as
from apps.approvals.models import ApprovalAction
from apps.composer.models import PlatformPost, Post, PostMedia
from apps.composer.services import create_post, transition_platform_post
from apps.media_library.models import MediaAsset
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.publisher.engine import PublishEngine
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


def _user(email):
    user = User.objects.create_user(email=email, password="pw-12345678", tos_accepted_at=timezone.now())
    auto_orgs = list(OrgMembership.objects.filter(user=user).values_list("organization_id", flat=True))
    WorkspaceMembership.objects.filter(user=user).delete()
    OrgMembership.objects.filter(user=user).delete()
    Organization.objects.filter(id__in=auto_orgs).delete()
    return user


def _world(enforced=True, prefix=""):
    org = Organization.objects.create(name="Brand Org")
    ws = Workspace.objects.create(
        organization=org,
        name="Neopolis",
        timezone="Asia/Kolkata",
        approval_workflow_mode="required_internal",
        require_dashboard_approval=enforced,
    )
    approver = _user(f"{prefix}approver@example.com")
    editor = _user(f"{prefix}editor@example.com")
    client = _user(f"{prefix}client@example.com")
    OrgMembership.objects.create(user=approver, organization=org, org_role="owner")
    WorkspaceMembership.objects.create(user=approver, workspace=ws, workspace_role="owner")
    WorkspaceMembership.objects.create(user=editor, workspace=ws, workspace_role="editor")
    WorkspaceMembership.objects.create(user=client, workspace=ws, workspace_role="client")
    account = SocialAccount.objects.create(
        workspace=ws,
        platform="facebook",
        account_platform_id="585141221346435",
        account_name="Neopolis Infra",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
    )
    return ws, approver, editor, client, account


def _pending(ws, author, account, *, caption="Landlord-share flats in West Hyderabad", when=None):
    post = Post.objects.create(workspace=ws, author=author, caption=caption, proposed_publish_at=when)
    PlatformPost.objects.create(post=post, social_account=account, status="pending_review")
    return post


class ApprovingTests(TestCase):
    def setUp(self):
        self.ws, self.approver, self.editor, self.client_user, self.account = _world()
        self.when = timezone.now() + timedelta(days=2)
        self.post = _pending(self.ws, self.editor, self.account, when=self.when)

    def test_dashboard_approver_stamps_the_reviewed_revision(self):
        with acting_as(self.approver, DASHBOARD):
            services.approve_post(self.post, self.approver, self.ws)
        pp = self.post.platform_posts.get()
        self.assertEqual(pp.status, "approved")
        self.assertEqual(pp.approved_fingerprint, gate.fingerprint(pp))
        self.assertEqual(pp.approved_by, self.approver)
        self.assertIsNotNone(pp.approved_at)
        self.assertEqual(pp.approved_publish_at, self.when)
        action = ApprovalAction.objects.get(action="approved")
        self.assertEqual(action.platform_post, pp)
        self.assertEqual(action.fingerprint, pp.approved_fingerprint)
        self.assertEqual(action.channel, DASHBOARD)
        self.assertEqual(action.publish_at, self.when)

    def test_automation_cannot_approve(self):
        for user, channel in ((self.approver, API), (None, "system"), (self.approver, PORTAL)):
            with acting_as(user, channel):
                services.approve_post(self.post, self.approver, self.ws)
            self.assertEqual(self.post.platform_posts.get().status, "pending_review", channel)
        self.assertFalse(ApprovalAction.objects.filter(action="approved").exists())

    def test_an_editor_or_client_in_the_dashboard_cannot_approve(self):
        for user in (self.editor, self.client_user):
            with acting_as(user, DASHBOARD):
                services.approve_post(self.post, user, self.ws)
        self.assertEqual(self.post.platform_posts.get().status, "pending_review")

    def test_approve_view_stamps_through_the_middleware(self):
        self.client.force_login(self.approver)
        url = reverse("approvals:approve", kwargs={"workspace_id": self.ws.id, "post_id": self.post.id})
        self.assertEqual(self.client.post(url).status_code, 204)
        pp = self.post.platform_posts.get()
        self.assertEqual(pp.status, "approved")
        self.assertEqual(pp.approved_by, self.approver)

    def test_requesting_changes_clears_the_approval(self):
        with acting_as(self.approver, DASHBOARD):
            services.approve_post(self.post, self.approver, self.ws)
            pp = self.post.platform_posts.get()
            pp.transition_to("pending_review")
            pp.save()
            services.request_changes(self.post, self.approver, self.ws, "Fix the price line")
        pp.refresh_from_db()
        self.assertEqual(pp.status, "changes_requested")
        self.assertEqual(pp.approved_fingerprint, "")


class SchedulingTests(TestCase):
    def setUp(self):
        self.ws, self.approver, self.editor, _client, self.account = _world()
        self.when = timezone.now() + timedelta(days=1)
        self.post = _pending(self.ws, self.editor, self.account, when=self.when)

    def _approve(self):
        with acting_as(self.approver, DASHBOARD):
            services.approve_post(self.post, self.approver, self.ws)
        return self.post.platform_posts.get()

    def test_unapproved_content_cannot_be_scheduled_by_anyone(self):
        draft = Post.objects.create(workspace=self.ws, caption="draft")
        pp = PlatformPost.objects.create(post=draft, social_account=self.account, status="draft")
        for user, channel in ((self.approver, DASHBOARD), (None, API), (None, "system")):
            with acting_as(user, channel), self.assertRaises(gate.ApprovalRequired):
                transition_platform_post(pp, "scheduled", scheduled_at=self.when)
        pp.refresh_from_db()
        self.assertEqual(pp.status, "draft")

    def test_the_api_cannot_create_a_scheduled_post(self):
        with acting_as(None, API), self.assertRaises(ValueError):
            create_post(
                workspace=self.ws,
                social_account=self.account,
                caption="straight to schedule",
                scheduled_at=self.when,
                status="scheduled",
            )
        self.assertFalse(PlatformPost.objects.filter(status="scheduled").exists())

    def test_approved_content_schedules_at_the_approved_time(self):
        pp = self._approve()
        with acting_as(None, API):
            transition_platform_post(pp, "scheduled", scheduled_at=self.when)
        pp.refresh_from_db()
        self.assertEqual(pp.status, "scheduled")

    def test_a_different_time_needs_an_approver(self):
        pp = self._approve()
        later = self.when + timedelta(hours=3)
        with acting_as(None, API), self.assertRaises(gate.ApprovalRequired):
            transition_platform_post(pp, "scheduled", scheduled_at=later)
        pp = PlatformPost.objects.get(pk=pp.pk)
        with acting_as(self.approver, DASHBOARD):
            transition_platform_post(pp, "scheduled", scheduled_at=later)
        pp.refresh_from_db()
        self.assertEqual(pp.status, "scheduled")
        self.assertEqual(pp.approved_publish_at, later)
        self.assertTrue(ApprovalAction.objects.filter(action="time_approved", platform_post=pp).exists())

    def test_a_non_enforced_workspace_is_unchanged(self):
        ws, approver, *_rest, account = _world(enforced=False, prefix="legacy-")
        ws.approval_workflow_mode = "none"
        ws.save()
        post = Post.objects.create(workspace=ws, caption="legacy")
        pp = PlatformPost.objects.create(post=post, social_account=account, status="draft")
        transition_platform_post(pp, "scheduled", scheduled_at=self.when)
        pp.refresh_from_db()
        self.assertEqual(pp.status, "scheduled")


class WithdrawalTests(TestCase):
    def setUp(self):
        self.ws, self.approver, self.editor, _client, self.account = _world()
        self.when = timezone.now() + timedelta(days=1)
        with self.captureOnCommitCallbacks(execute=True):
            self.post = _pending(self.ws, self.editor, self.account, when=self.when)
            with acting_as(self.approver, DASHBOARD):
                services.approve_post(self.post, self.approver, self.ws)
            self.pp = self.post.platform_posts.get()
            with acting_as(None, API):
                transition_platform_post(self.pp, "scheduled", scheduled_at=self.when)
        self.pp.refresh_from_db()
        assert self.pp.status == "scheduled"

    def _assert_withdrawn(self):
        self.pp.refresh_from_db()
        self.assertEqual(self.pp.status, "pending_review")
        self.assertEqual(self.pp.approved_fingerprint, "")
        self.assertTrue(ApprovalAction.objects.filter(action="approval_withdrawn", platform_post=self.pp).exists())

    def test_editing_the_caption_withdraws_the_approval(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.post.caption = "A new price claim nobody reviewed"
            self.post.save()
        self._assert_withdrawn()

    def test_even_the_approver_editing_needs_a_fresh_approval(self):
        with acting_as(self.approver, DASHBOARD), self.captureOnCommitCallbacks(execute=True):
            self.post.caption = "Edited by the approver"
            self.post.save()
        self._assert_withdrawn()

    def test_adding_media_withdraws_the_approval(self):
        asset = MediaAsset.objects.create(
            organization=self.ws.organization,
            workspace=self.ws,
            file="media_library/x.jpg",
            filename="x.jpg",
            media_type="image",
        )
        with self.captureOnCommitCallbacks(execute=True):
            PostMedia.objects.create(post=self.post, media_asset=asset, position=0)
        self._assert_withdrawn()

    def test_changing_the_format_withdraws_the_approval(self):
        with self.captureOnCommitCallbacks(execute=True):
            pp = PlatformPost.objects.get(pk=self.pp.pk)
            pp.platform_extra = {"post_type": "reel"}
            pp.save()
        self._assert_withdrawn()

    def test_moving_the_time_without_an_approver_withdraws_it(self):
        with acting_as(self.editor, DASHBOARD), self.captureOnCommitCallbacks(execute=True):
            pp = PlatformPost.objects.get(pk=self.pp.pk)
            pp.scheduled_at = self.when + timedelta(days=1)
            pp.save()
        self._assert_withdrawn()

    def test_the_approver_moving_the_time_approves_it(self):
        later = self.when + timedelta(days=1)
        with acting_as(self.approver, DASHBOARD), self.captureOnCommitCallbacks(execute=True):
            pp = PlatformPost.objects.get(pk=self.pp.pk)
            pp.scheduled_at = later
            pp.save()
        self.pp.refresh_from_db()
        self.assertEqual(self.pp.status, "scheduled")
        self.assertEqual(self.pp.approved_publish_at, later)

    def test_an_unrelated_save_keeps_the_approval(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.post.internal_notes = "internal only"
            self.post.save()
        self.pp.refresh_from_db()
        self.assertEqual(self.pp.status, "scheduled")


def _due_world():
    ws, approver, editor, _client, account = _world()
    when = timezone.now() - timedelta(minutes=1)
    post = Post.objects.create(workspace=ws, author=editor, caption="Due now", scheduled_at=when)
    pp = PlatformPost.objects.create(post=post, social_account=account, status="pending_review", scheduled_at=when)
    with acting_as(approver, DASHBOARD):
        services.approve_post(post, approver, ws)
    pp.refresh_from_db()
    PlatformPost.objects.filter(pk=pp.pk).update(status="scheduled")
    return ws, approver, post, PlatformPost.objects.get(pk=pp.pk)


_OK = {"success": True, "platform_post_id": "fb_1", "status_code": 200, "response": {}}


class PublisherTests(TransactionTestCase):
    def test_an_approved_row_publishes_once(self):
        _ws, _approver, _post, pp = _due_world()
        with patch.object(PublishEngine, "_dispatch_to_provider", return_value=_OK) as send:
            PublishEngine().poll_and_publish()
            PublishEngine().poll_and_publish()
        self.assertEqual(send.call_count, 1)
        pp.refresh_from_db()
        self.assertEqual(pp.status, "published")

    def test_a_stale_approval_never_reaches_the_platform(self):
        _ws, _approver, post, pp = _due_world()
        # Simulate an edit that slipped past every web-side check.
        Post.objects.filter(pk=post.pk).update(caption="Edited behind the gate's back")
        with patch.object(PublishEngine, "_dispatch_to_provider", return_value=_OK) as send:
            PublishEngine().poll_and_publish()
        send.assert_not_called()
        pp.refresh_from_db()
        self.assertEqual(pp.status, "failed")
        self.assertIn("changed after approval", pp.publish_error)
        self.assertTrue(ApprovalAction.objects.filter(action="publish_blocked", platform_post=pp).exists())

    def test_a_row_scheduled_without_approval_is_blocked(self):
        ws, _approver, _editor, _client, account = _world()
        when = timezone.now() - timedelta(minutes=1)
        post = Post.objects.create(workspace=ws, caption="never reviewed", scheduled_at=when)
        pp = PlatformPost.objects.create(post=post, social_account=account, status="draft", scheduled_at=when)
        PlatformPost.objects.filter(pk=pp.pk).update(status="scheduled")  # e.g. a bulk_create path
        with patch.object(PublishEngine, "_dispatch_to_provider", return_value=_OK) as send:
            PublishEngine().poll_and_publish()
        send.assert_not_called()
        pp.refresh_from_db()
        self.assertEqual(pp.status, "failed")
        self.assertIn("never approved", pp.publish_error)

    def test_an_edit_between_claim_and_send_is_caught(self):
        _ws, _approver, post, pp = _due_world()
        engine = PublishEngine()
        original = PublishEngine._approval_blocker

        def edit_then_check(platform_post):
            Post.objects.filter(pk=post.pk).update(caption="Edited mid-flight")
            return original(platform_post)

        with (
            patch.object(PublishEngine, "_approval_blocker", side_effect=edit_then_check),
            patch.object(PublishEngine, "_dispatch_to_provider", return_value=_OK) as send,
        ):
            engine.poll_and_publish()
        send.assert_not_called()
        pp.refresh_from_db()
        self.assertEqual(pp.status, "failed")

    def test_a_retry_with_a_stale_approval_is_blocked(self):
        _ws, _approver, post, pp = _due_world()
        PlatformPost.objects.filter(pk=pp.pk).update(retry_count=1, next_retry_at=timezone.now() - timedelta(seconds=5))
        Post.objects.filter(pk=post.pk).update(caption="changed during backoff")
        with patch.object(PublishEngine, "_dispatch_to_provider", return_value=_OK) as send:
            PublishEngine()._process_retries()
        send.assert_not_called()
        pp.refresh_from_db()
        self.assertEqual(pp.status, "failed")

    def test_a_moved_time_is_blocked(self):
        _ws, _approver, _post, pp = _due_world()
        PlatformPost.objects.filter(pk=pp.pk).update(scheduled_at=timezone.now() - timedelta(minutes=30))
        with patch.object(PublishEngine, "_dispatch_to_provider", return_value=_OK) as send:
            PublishEngine().poll_and_publish()
        send.assert_not_called()


class RecurrenceTests(TestCase):
    def test_occurrences_wait_for_review(self):
        from apps.calendar.tasks import _clone_occurrence

        ws, _approver, editor, _client, account = _world()
        source = Post.objects.create(workspace=ws, author=editor, caption="weekly", scheduled_at=timezone.now())
        PlatformPost.objects.create(post=source, social_account=account, status="draft")
        _clone_occurrence(source, timezone.now() + timedelta(days=7))
        clone = Post.objects.exclude(pk=source.pk).get()
        self.assertEqual(clone.platform_posts.get().status, "pending_review")


class ComposerTests(TestCase):
    def setUp(self):
        self.ws, self.approver, self.editor, _client, self.account = _world()

    def test_schedule_on_new_content_becomes_a_review_request(self):
        self.client.force_login(self.approver)
        when = timezone.localtime(timezone.now() + timedelta(days=2), timezone=None)
        url = reverse("composer:save_post", kwargs={"workspace_id": self.ws.id})
        resp = self.client.post(
            url,
            {
                "caption": "Fresh content",
                "action": "schedule",
                "selected_accounts": str(self.account.id),
                "scheduled_date": when.strftime("%Y-%m-%d"),
                "scheduled_time": "10:00",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertIn(resp.status_code, (200, 204, 302))
        pp = PlatformPost.objects.get(post__workspace=self.ws)
        self.assertEqual(pp.status, "pending_review")
        self.assertIsNotNone(pp.post.proposed_publish_at)


class ApprovalsQueueViewTests(TestCase):
    def setUp(self):
        self.ws, self.approver, self.editor, _client, self.account = _world()
        self.when = timezone.now() + timedelta(days=1)
        self.post = _pending(self.ws, self.editor, self.account, when=self.when)
        PlatformPost.objects.filter(post=self.post).update(platform_specific_caption="Facebook-only wording")
        self.client.force_login(self.approver)

    def test_queue_previews_each_destination(self):
        url = reverse("calendar:calendar", kwargs={"workspace_id": self.ws.id})
        resp = self.client.get(url, {"mode": "list", "tab": "approvals"})
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("Preview per destination", body)
        self.assertIn("Facebook-only wording", body)
        self.assertIn("Approve &amp; schedule", body)

    def test_approve_and_schedule_uses_the_proposed_time(self):
        url = reverse("approvals:approve", kwargs={"workspace_id": self.ws.id, "post_id": self.post.id})
        resp = self.client.post(url, {"schedule": "1"})
        self.assertEqual(resp.status_code, 204)
        pp = self.post.platform_posts.get()
        self.assertEqual(pp.status, "scheduled")
        self.assertEqual(pp.scheduled_at, self.when)
        self.assertEqual(pp.approved_publish_at, self.when)
        self.assertEqual(pp.approved_by, self.approver)

    def test_an_editor_is_told_why_nothing_happened(self):
        WorkspaceMembership.objects.filter(user=self.editor, workspace=self.ws).update(workspace_role="client")
        self.client.force_login(self.editor)
        url = reverse("approvals:approve", kwargs={"workspace_id": self.ws.id, "post_id": self.post.id})
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 204)
        self.assertIn("internal approver", resp.headers["HX-Trigger"])
        self.assertEqual(self.post.platform_posts.get().status, "pending_review")


class SettingsTests(TestCase):
    def setUp(self):
        self.ws, self.approver, self.editor, _client, _account = _world(enforced=False)

    def test_owner_can_require_dashboard_approval(self):
        self.client.force_login(self.approver)
        url = reverse("workspaces:approvals_settings", kwargs={"workspace_id": self.ws.id})
        resp = self.client.post(url, {"approval_workflow_mode": "none", "require_dashboard_approval": "on"})
        self.assertEqual(resp.status_code, 302)
        self.ws.refresh_from_db()
        self.assertTrue(self.ws.require_dashboard_approval)
        self.assertEqual(self.ws.approval_workflow_mode, "required_internal")

    def test_a_manager_cannot_switch_it_off(self):
        self.ws.require_dashboard_approval = True
        self.ws.save()
        WorkspaceMembership.objects.filter(user=self.editor, workspace=self.ws).update(workspace_role="manager")
        self.client.force_login(self.editor)
        url = reverse("workspaces:approvals_settings", kwargs={"workspace_id": self.ws.id})
        self.client.post(url, {"approval_workflow_mode": "none"})
        self.ws.refresh_from_db()
        self.assertTrue(self.ws.require_dashboard_approval)
