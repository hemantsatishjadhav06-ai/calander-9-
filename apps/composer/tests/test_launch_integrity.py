"""Tenant isolation and media preservation across every composer write path."""

import uuid
from datetime import time
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.calendar.models import PostingSlot, Queue, QueueEntry, RecurrenceRule
from apps.composer.models import ContentCategory, Idea, IdeaGroup, PlatformPost, Post, PostMedia
from apps.media_library.models import MediaAsset
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


class ComposerLaunchIntegrityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="launch-owner@example.com", password="pw", tos_accepted_at=timezone.now()
        )
        self.org = Organization.objects.create(name="Launch Org")
        self.workspace = Workspace.objects.create(organization=self.org, name="Workspace")
        OrgMembership.objects.create(user=self.user, organization=self.org, org_role="owner")
        WorkspaceMembership.objects.create(user=self.user, workspace=self.workspace, workspace_role="owner")
        self.account = SocialAccount.objects.create(
            workspace=self.workspace,
            platform="bluesky",
            account_platform_id="launch-account",
            account_name="Launch account",
            connection_status="connected",
        )
        self.client.force_login(self.user)

    def url(self, name, **kwargs):
        return reverse(f"composer:{name}", kwargs={"workspace_id": self.workspace.id, **kwargs})

    def post(self, status="draft"):
        post = Post.objects.create(workspace=self.workspace, author=self.user, caption="Original")
        PlatformPost.objects.create(post=post, social_account=self.account, status=status)
        return post

    def asset(self, *, shared=False):
        return MediaAsset.objects.create(
            organization=self.org,
            workspace=None if shared else self.workspace,
            uploaded_by=self.user,
            file="tests/launch.png",
            filename="launch.png",
            media_type="image",
            mime_type="image/png",
            file_size=1,
        )

    def pending(self, asset):
        session = self.client.session
        session[f"pending_media_{self.workspace.id}"] = [str(asset.id)]
        session.save()

    def test_client_autosave_id_cannot_edit_another_authors_post(self):
        post = self.post()
        contributor = User.objects.create_user(
            email="launch-contributor@example.com", password="pw", tos_accepted_at=timezone.now()
        )
        OrgMembership.objects.create(user=contributor, organization=self.org, org_role="member")
        WorkspaceMembership.objects.create(user=contributor, workspace=self.workspace, workspace_role="contributor")
        self.client.force_login(contributor)
        response = self.client.post(
            self.url("autosave"), {"_autosave_post_id": str(post.id), "caption": "Unauthorized"}
        )
        self.assertEqual(response.status_code, 403)
        post.refresh_from_db()
        self.assertEqual(post.caption, "Original")

    def test_client_autosave_id_preserves_published_content(self):
        post = self.post("published")
        response = self.client.post(self.url("autosave"), {"_autosave_post_id": str(post.id), "caption": "Changed"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Read-only", response.content.decode())
        post.refresh_from_db()
        self.assertEqual(post.caption, "Original")

    def test_client_autosave_id_reverts_changed_approved_content(self):
        post = self.post("approved")
        response = self.client.post(
            self.url("autosave"),
            {"_autosave_post_id": str(post.id), "caption": "Changed", "selected_accounts": str(self.account.id)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(post.platform_posts.get().status, "pending_review")

    def test_invalid_and_stale_client_ids_do_not_create_duplicate_drafts(self):
        for client_id, expected in (("broken", 400), (str(uuid.uuid4()), 404)):
            with self.subTest(client_id=client_id):
                response = self.client.post(
                    self.url("autosave"), {"_autosave_post_id": client_id, "caption": "Changed"}
                )
                self.assertEqual(response.status_code, expected)
        self.assertFalse(Post.objects.filter(workspace=self.workspace).exists())

    def test_category_from_another_workspace_is_rejected(self):
        other = Workspace.objects.create(organization=self.org, name="Other")
        foreign = ContentCategory.objects.create(workspace=other, name="Private category")
        response = self.client.post(self.url("save_post"), {"caption": "Draft", "category": str(foreign.id)})
        self.assertEqual(response.status_code, 400)
        self.assertIn("category", response.json()["errors"])
        self.assertFalse(Post.objects.filter(workspace=self.workspace).exists())

    def test_shared_library_selection_survives_save_and_autosave(self):
        asset = self.asset(shared=True)
        for endpoint in ("save_post", "autosave"):
            with self.subTest(endpoint=endpoint):
                self.pending(asset)
                response = self.client.post(self.url(endpoint), {"caption": endpoint})
                self.assertIn(response.status_code, (200, 302))
                post = Post.objects.get(workspace=self.workspace, caption=endpoint)
                self.assertTrue(PostMedia.objects.filter(post=post, media_asset=asset).exists())

    def test_approval_submission_keeps_selected_media(self):
        asset = self.asset()
        self.pending(asset)
        with patch("apps.approvals.services.submit_for_review"):
            response = self.client.post(
                self.url("save_post"),
                {"action": "submit_for_approval", "caption": "For review", "selected_accounts": str(self.account.id)},
            )
        self.assertEqual(response.status_code, 302)
        post = Post.objects.get(workspace=self.workspace)
        self.assertTrue(PostMedia.objects.filter(post=post, media_asset=asset).exists())

    def test_removing_pending_library_media_keeps_the_asset_and_existing_posts(self):
        asset = self.asset()
        post = self.post()
        attachment = PostMedia.objects.create(post=post, media_asset=asset)
        self.pending(asset)
        response = self.client.post(self.url("remove_pending_media", asset_id=asset.id))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(MediaAsset.objects.filter(pk=asset.id).exists())
        self.assertTrue(PostMedia.objects.filter(pk=attachment.id).exists())
        self.assertEqual(self.client.session[f"pending_media_{self.workspace.id}"], [])

    def test_media_mutation_endpoints_preserve_published_posts(self):
        post = self.post("published")
        asset = self.asset()
        attachment = PostMedia.objects.create(post=post, media_asset=asset)
        for name, kwargs, payload in (
            ("attach_media", {"post_id": post.id}, {"media_asset_id": str(asset.id)}),
            ("remove_media", {"post_id": post.id, "media_id": attachment.id}, {}),
        ):
            with self.subTest(endpoint=name):
                response = self.client.post(self.url(name, **kwargs), payload)
                self.assertEqual(response.status_code, 400)
        self.assertTrue(PostMedia.objects.filter(pk=attachment.id).exists())

    @override_settings(UNSPLASH_ACCESS_KEY="test-key")
    def test_unsplash_import_rejects_published_posts_before_network_access(self):
        post = self.post("published")
        with patch("apps.composer.views.httpx.Client") as client:
            response = self.client.post(
                self.url("unsplash_import_post", post_id=post.id),
                {"photos": [{"id": "photo"}]},
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 400)
        client.assert_not_called()

    def test_invalid_media_ids_return_client_errors(self):
        post = self.post()
        for endpoint, kwargs in (("attach_media", {"post_id": post.id}), ("attach_pending_media", {})):
            with self.subTest(endpoint=endpoint):
                response = self.client.post(self.url(endpoint, **kwargs), {"media_asset_id": "invalid"})
                self.assertEqual(response.status_code, 400)

    def test_autosave_rejects_overlong_titles_without_writing(self):
        response = self.client.post(self.url("autosave"), {"title": "x" * 256, "caption": "Draft"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Post.objects.filter(workspace=self.workspace).exists())

    def test_unavailable_channels_cannot_be_scheduled_or_queued(self):
        other = Workspace.objects.create(organization=self.org, name="Other")
        foreign = SocialAccount.objects.create(
            workspace=other,
            platform="bluesky",
            account_platform_id="foreign-account",
            account_name="Foreign account",
            connection_status="connected",
        )
        for action in ("schedule", "publish_now", "add_to_queue", "add_to_queue_priority"):
            for selected in (str(uuid.uuid4()), str(foreign.id), f"{self.account.id},{foreign.id}"):
                with self.subTest(action=action, selected=selected):
                    response = self.client.post(
                        self.url("save_post"),
                        {
                            "action": action,
                            "caption": "Draft",
                            "selected_accounts": selected,
                            "scheduled_date": "2030-01-01",
                            "scheduled_time": "12:00",
                        },
                    )
                    self.assertEqual(response.status_code, 400)
                    self.assertIn("channels", response.json()["errors"])
        self.assertFalse(Post.objects.filter(workspace=self.workspace).exists())

    def test_contributor_queue_actions_submit_for_review(self):
        contributor = User.objects.create_user(
            email="queue-contributor@example.com", password="pw", tos_accepted_at=timezone.now()
        )
        OrgMembership.objects.create(user=contributor, organization=self.org, org_role="member")
        WorkspaceMembership.objects.create(user=contributor, workspace=self.workspace, workspace_role="contributor")
        self.client.force_login(contributor)
        for action in ("add_to_queue", "add_to_queue_priority"):
            with self.subTest(action=action):
                response = self.client.post(
                    self.url("save_post"),
                    {"action": action, "caption": action, "selected_accounts": str(self.account.id)},
                )
                self.assertEqual(response.status_code, 302)
                post = Post.objects.get(workspace=self.workspace, caption=action)
                self.assertEqual(post.platform_posts.get().status, "pending_review")
                self.assertIsNone(post.scheduled_at)

    def test_changed_approved_content_cannot_bypass_review_through_queueing(self):
        post = self.post("approved")
        for action in ("add_to_queue", "add_to_queue_priority"):
            with self.subTest(action=action):
                response = self.client.post(
                    self.url("save_post_edit", post_id=post.id),
                    {"action": action, "caption": "Changed", "selected_accounts": str(self.account.id)},
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("approval", response.json()["errors"])
        post.refresh_from_db()
        self.assertEqual(post.caption, "Original")
        self.assertEqual(post.platform_posts.get().status, "approved")

    def test_approved_platform_overrides_require_review_before_scheduling(self):
        for field in ("title", "caption", "comment"):
            with self.subTest(field=field):
                post = self.post("approved")
                response = self.client.post(
                    self.url("save_post_edit", post_id=post.id),
                    {
                        "action": "schedule",
                        "caption": "Original",
                        "selected_accounts": str(self.account.id),
                        "scheduled_date": "2030-01-01",
                        "scheduled_time": "12:00",
                        f"override_{field}_{self.account.id}": "Changed platform content",
                    },
                )
                self.assertEqual(response.status_code, 302)
                self.assertEqual(post.platform_posts.get().status, "pending_review")

    def test_approved_platform_options_require_review_before_scheduling(self):
        self.account.platform = "youtube"
        self.account.save(update_fields=["platform"])
        post = self.post("approved")
        response = self.client.post(
            self.url("save_post_edit", post_id=post.id),
            {
                "action": "schedule",
                "caption": "Original",
                "selected_accounts": str(self.account.id),
                "scheduled_date": "2030-01-01",
                "scheduled_time": "12:00",
                f"yt_privacy_status_{self.account.id}": "private",
                f"yt_tags_{self.account.id}": "Changed video tags",
            },
        )
        self.assertEqual(response.status_code, 302)
        child = post.platform_posts.get()
        self.assertEqual(child.status, "pending_review")
        self.assertEqual(child.platform_extra["privacy_status"], "private")

    def test_queueing_changed_approved_overrides_rolls_back_every_write(self):
        queue = Queue.objects.create(workspace=self.workspace, social_account=self.account, name="Queue")
        for day in range(7):
            PostingSlot.objects.create(social_account=self.account, day_of_week=day, time=time(12))
        for action in ("add_to_queue", "add_to_queue_priority"):
            with self.subTest(action=action):
                post = self.post("approved")
                response = self.client.post(
                    self.url("save_post_edit", post_id=post.id),
                    {
                        "action": action,
                        "caption": "Original",
                        "queue_id": str(queue.id),
                        "selected_accounts": str(self.account.id),
                        f"override_caption_{self.account.id}": "Changed platform content",
                    },
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("approval", response.json()["errors"])
                child = post.platform_posts.get()
                self.assertEqual(child.status, "approved")
                self.assertIsNone(child.platform_specific_caption)
                self.assertIsNone(child.scheduled_at)
                self.assertFalse(QueueEntry.objects.filter(post=post).exists())

    def test_explicit_submission_reverts_changed_approved_overrides(self):
        post = self.post("approved")
        response = self.client.post(
            self.url("save_post_edit", post_id=post.id),
            {
                "action": "submit_for_approval",
                "caption": "Original",
                "selected_accounts": str(self.account.id),
                f"override_caption_{self.account.id}": "Changed platform content",
            },
        )
        self.assertEqual(response.status_code, 302)
        child = post.platform_posts.get()
        self.assertEqual(child.status, "pending_review")
        self.assertEqual(child.platform_specific_caption, "Changed platform content")

    def test_malformed_idea_references_are_rejected_before_uploads_or_edits(self):
        group = IdeaGroup.objects.create(workspace=self.workspace, name="Original group")
        idea = Idea.objects.create(workspace=self.workspace, author=self.user, title="Original idea", group=group)
        for endpoint, kwargs in (
            ("idea_create", {}),
            ("idea_edit", {"idea_id": idea.id}),
            ("idea_move", {"idea_id": idea.id}),
        ):
            for field in ("group", "media_asset_id"):
                with self.subTest(endpoint=endpoint, field=field):
                    with patch("apps.composer.views._store_idea_upload") as store:
                        response = self.client.post(
                            self.url(endpoint, **kwargs),
                            {
                                "title": "Changed idea",
                                field: "malformed",
                                "file": SimpleUploadedFile("upload.png", b"unused", content_type="image/png"),
                            },
                        )
                    self.assertEqual(response.status_code, 400)
                    store.assert_not_called()
                    idea.refresh_from_db()
                    self.assertEqual(idea.title, "Original idea")
                    self.assertEqual(idea.group_id, group.id)
        self.assertEqual(Idea.objects.filter(workspace=self.workspace).count(), 1)

    def test_idea_reorder_rejects_invalid_json_shapes_without_partial_writes(self):
        group = IdeaGroup.objects.create(workspace=self.workspace, name="Original group", position=3)
        for order in ("invalid", 2, [str(group.id), {}], [str(group.id), "broken"]):
            with self.subTest(order=order):
                response = self.client.post(
                    self.url("idea_group_reorder"), {"order": order}, content_type="application/json"
                )
                self.assertEqual(response.status_code, 400)
                group.refresh_from_db()
                self.assertEqual(group.position, 3)

    def test_invalid_recurrence_intervals_do_not_save_content_or_schedules(self):
        post = self.post()
        for frequency in ("daily", "weekly", "monthly"):
            for interval in ("-1", "0", "", "not-a-number", "1.5", "2147483647", "2147483648"):
                with self.subTest(frequency=frequency, interval=interval):
                    response = self.client.post(
                        self.url("save_post_edit", post_id=post.id),
                        {
                            "action": "schedule",
                            "caption": "Changed",
                            "selected_accounts": str(self.account.id),
                            "scheduled_date": "2030-01-01",
                            "scheduled_time": "12:00",
                            "make_recurring": "true",
                            "recurrence_frequency": frequency,
                            "recurrence_interval": interval,
                        },
                    )
                    self.assertEqual(response.status_code, 400)
                    self.assertIn("recurrence", response.json()["errors"])
                    post.refresh_from_db()
                    self.assertEqual(post.caption, "Original")
                    self.assertIsNone(post.scheduled_at)
                    self.assertEqual(post.platform_posts.get().status, "draft")
        self.assertFalse(RecurrenceRule.objects.filter(post=post).exists())

    def test_invalid_recurrence_options_do_not_create_a_post(self):
        for options in (
            {"recurrence_frequency": "yearly"},
            {"recurrence_end_date": "invalid"},
            {"recurrence_end_date": "2029-12-31"},
        ):
            with self.subTest(options=options):
                response = self.client.post(
                    self.url("save_post"),
                    {
                        "action": "schedule",
                        "caption": "Draft",
                        "selected_accounts": str(self.account.id),
                        "scheduled_date": "2030-01-01",
                        "scheduled_time": "12:00",
                        "make_recurring": "true",
                        **options,
                    },
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("recurrence", response.json()["errors"])
        self.assertFalse(Post.objects.filter(workspace=self.workspace).exists())

    def test_valid_recurrence_is_saved_with_normalized_values(self):
        response = self.client.post(
            self.url("save_post"),
            {
                "action": "schedule",
                "caption": "Draft",
                "selected_accounts": str(self.account.id),
                "scheduled_date": "2030-01-01",
                "scheduled_time": "12:00",
                "make_recurring": "true",
                "recurrence_frequency": "weekly",
                "recurrence_interval": "2",
                "recurrence_end_date": "2030-05-01",
            },
        )
        self.assertEqual(response.status_code, 302)
        rule = RecurrenceRule.objects.get(post__workspace=self.workspace)
        self.assertEqual(rule.interval, 2)
        self.assertEqual(rule.frequency, "weekly")
        self.assertEqual(rule.end_date.isoformat(), "2030-05-01")

    def test_duplicate_category_names_return_clear_errors_on_create_and_edit(self):
        existing = ContentCategory.objects.create(workspace=self.workspace, name="News")
        category = ContentCategory.objects.create(workspace=self.workspace, name="Updates")
        for endpoint, kwargs in (("category_create", {}), ("category_edit", {"category_id": category.id})):
            with self.subTest(endpoint=endpoint):
                response = self.client.post(self.url(endpoint, **kwargs), {"name": existing.name, "color": "#000000"})
                self.assertEqual(response.status_code, 400)
                self.assertIn("already exists", response.content.decode())
        category.refresh_from_db()
        self.assertEqual(category.name, "Updates")
        self.assertEqual(ContentCategory.objects.filter(workspace=self.workspace).count(), 2)

    def test_duplicate_category_race_uses_savepoint_and_keeps_database_usable(self):
        existing = ContentCategory.objects.create(workspace=self.workspace, name="News")
        category = ContentCategory.objects.create(workspace=self.workspace, name="Updates")
        # Bypass the initial duplicate read to simulate another request winning
        # between form validation and our INSERT/UPDATE. Let the real unique
        # constraint raise so this also verifies transaction recovery.
        with patch("apps.composer.forms.ContentCategoryForm.clean_name", return_value=existing.name):
            for endpoint, kwargs in (("category_create", {}), ("category_edit", {"category_id": category.id})):
                with self.subTest(endpoint=endpoint):
                    response = self.client.post(
                        self.url(endpoint, **kwargs), {"name": existing.name, "color": "#000000"}
                    )
                    self.assertEqual(response.status_code, 400)
                    self.assertIn("already exists", response.content.decode())
                    self.assertEqual(ContentCategory.objects.filter(workspace=self.workspace).count(), 2)
        category.refresh_from_db()
        self.assertEqual(category.name, "Updates")
