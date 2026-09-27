"""Authorization boundaries that a status code alone would not catch.

Every test here diffs the row it is trying to protect, because the finding
that motivated the file returned a clean 404 to an automated sweep while the
delete had already committed: the view's ``get_object_or_404`` ran after the
service call. A 403 is only half the assertion; the other half is that the
victim row is byte-for-byte unchanged.

Two tenants (alpha, beta), each with its own workspace. Beta's owner has no
relationship whatsoever to alpha.
"""

from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.approvals.models import PostComment
from apps.calendar.models import Queue, QueueEntry
from apps.composer.models import ContentCategory, PlatformPost, Post, PostTemplate
from apps.media_library.models import MediaAsset
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace

WR = WorkspaceMembership.WorkspaceRole


def _user(email):
    user = User.objects.create_user(
        email=email, password="pw", name=email.split("@")[0], tos_accepted_at=timezone.now()
    )
    # Signup auto-provisions an org; tear it down so membership is explicit.
    auto_org_ids = list(OrgMembership.objects.filter(user=user).values_list("organization_id", flat=True))
    WorkspaceMembership.objects.filter(user=user).delete()
    OrgMembership.objects.filter(user=user).delete()
    Organization.objects.filter(id__in=auto_org_ids).delete()
    return user


def _tenant(slug):
    org = Organization.objects.create(name=slug)
    ws = Workspace.objects.create(organization=org, name=f"{slug}-ws")
    owner = _user(f"{slug}-owner@example.com")
    OrgMembership.objects.create(user=owner, organization=org, org_role="owner")
    WorkspaceMembership.objects.create(user=owner, workspace=ws, workspace_role=WR.OWNER)
    account = SocialAccount.objects.create(
        workspace=ws,
        platform="bluesky",
        account_platform_id=f"{slug}-did",
        account_name=slug,
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
    )
    post = Post.objects.create(workspace=ws, author=owner, caption=f"{slug} post")
    pp = PlatformPost.objects.create(post=post, social_account=account, status=PlatformPost.Status.APPROVED)
    return {"org": org, "ws": ws, "owner": owner, "account": account, "post": post, "pp": pp}


def _member(tenant, role, email):
    user = _user(email)
    OrgMembership.objects.create(user=user, organization=tenant["org"], org_role="member")
    WorkspaceMembership.objects.create(user=user, workspace=tenant["ws"], workspace_role=role)
    return user


class CrossTenantCommentDeleteTests(TestCase):
    """Beta's owner, with their own workspace and post in the URL, names alpha's comment id."""

    def setUp(self):
        self.alpha = _tenant("alpha")
        self.beta = _tenant("beta")
        self.victim = PostComment.objects.create(
            post=self.alpha["post"], author=self.alpha["owner"], body="alpha internal note"
        )

    def _attack(self, attacker):
        self.client.force_login(attacker)
        url = reverse(
            "approvals:delete_comment",
            kwargs={
                "workspace_id": self.beta["ws"].id,
                "post_id": self.beta["post"].id,
                "comment_id": self.victim.id,
            },
        )
        return self.client.post(url)

    def test_another_tenants_owner_cannot_delete_it(self):
        response = self._attack(self.beta["owner"])
        self.victim.refresh_from_db()
        self.assertNotEqual(response.status_code, 200)
        self.assertIsNone(self.victim.deleted_at)

    def test_another_tenants_client_cannot_delete_it(self):
        """``client`` carries ``approve_posts`` — the permission the service checks."""
        attacker = _member(self.beta, WR.CLIENT, "beta-client@example.com")
        response = self._attack(attacker)
        self.victim.refresh_from_db()
        self.assertNotEqual(response.status_code, 200)
        self.assertIsNone(self.victim.deleted_at)

    def test_the_owner_of_the_comments_workspace_still_can(self):
        self.client.force_login(self.alpha["owner"])
        url = reverse(
            "approvals:delete_comment",
            kwargs={
                "workspace_id": self.alpha["ws"].id,
                "post_id": self.alpha["post"].id,
                "comment_id": self.victim.id,
            },
        )
        response = self.client.post(url)
        self.victim.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(self.victim.deleted_at)


class ViewerCannotDestroyTests(TestCase):
    """A workspace viewer has create_posts, edit_others_posts and delete_media all False."""

    def setUp(self):
        self.t = _tenant("gamma")
        self.viewer = _member(self.t, WR.VIEWER, "gamma-viewer@example.com")
        self.client.force_login(self.viewer)
        self.ws = self.t["ws"]

    def _url(self, name, **kwargs):
        return reverse(name, kwargs={"workspace_id": self.ws.id, **kwargs})

    def test_cannot_delete_a_post(self):
        response = self.client.post(self._url("composer:post_delete", post_id=self.t["post"].id))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Post.objects.filter(pk=self.t["post"].pk).exists())
        self.assertTrue(PlatformPost.objects.filter(pk=self.t["pp"].pk).exists())

    def test_cannot_move_a_post_back_to_draft(self):
        response = self.client.post(
            self._url("composer:transition_platform_post", post_id=self.t["post"].id, platform_post_id=self.t["pp"].id),
            {"target_status": "draft"},
        )
        self.assertEqual(response.status_code, 403)
        self.t["pp"].refresh_from_db()
        self.assertEqual(self.t["pp"].status, PlatformPost.Status.APPROVED)

    def test_cannot_delete_a_category_or_template(self):
        category = ContentCategory.objects.create(workspace=self.ws, name="Launches")
        template = PostTemplate.objects.create(workspace=self.ws, name="Weekly", created_by=self.t["owner"])

        r1 = self.client.post(self._url("composer:category_delete", category_id=category.id))
        r2 = self.client.post(self._url("composer:template_delete", template_id=template.id))

        self.assertEqual((r1.status_code, r2.status_code), (403, 403))
        self.assertTrue(ContentCategory.objects.filter(pk=category.pk).exists())
        self.assertTrue(PostTemplate.objects.filter(pk=template.pk).exists())

    def test_cannot_create_or_delete_a_queue(self):
        queue = Queue.objects.create(workspace=self.ws, name="Main", social_account=self.t["account"])
        entry = QueueEntry.objects.create(queue=queue, post=self.t["post"])

        r_create = self.client.post(
            self._url("calendar:queue_create"), {"name": "Evil", "social_account_id": str(self.t["account"].id)}
        )
        r_delete = self.client.post(self._url("calendar:queue_delete", queue_id=queue.id))

        self.assertEqual((r_create.status_code, r_delete.status_code), (403, 403))
        self.assertEqual(Queue.objects.filter(workspace=self.ws).count(), 1)
        self.assertTrue(QueueEntry.objects.filter(pk=entry.pk).exists())

    def test_cannot_rename_the_workspace(self):
        response = self.client.post(
            reverse("workspaces:settings", kwargs={"workspace_id": self.ws.id}), {"name": "OWNED"}
        )
        self.ws.refresh_from_db()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.ws.name, "gamma-ws")

    def test_cannot_delete_media_through_the_composer_bypass(self):
        asset = MediaAsset.objects.create(
            organization=self.t["org"],
            workspace=self.ws,
            uploaded_by=self.t["owner"],
            file=ContentFile(b"png-bytes", name="logo.png"),
            filename="logo.png",
            media_type=MediaAsset.MediaType.IMAGE,
            mime_type="image/png",
            file_size=9,
            source="upload",
        )
        response = self.client.post(self._url("composer:remove_pending_media", asset_id=asset.id))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(MediaAsset.objects.filter(pk=asset.pk).exists())


class PendingMediaIsScopedToTheSessionTests(TestCase):
    """Even with upload rights, only an asset in the caller's own pending list is deleted."""

    def setUp(self):
        self.t = _tenant("delta")
        self.editor = _member(self.t, WR.EDITOR, "delta-editor@example.com")
        self.client.force_login(self.editor)
        self.asset = MediaAsset.objects.create(
            organization=self.t["org"],
            workspace=self.t["ws"],
            uploaded_by=self.t["owner"],
            file=ContentFile(b"png-bytes", name="hero.png"),
            filename="hero.png",
            media_type=MediaAsset.MediaType.IMAGE,
            mime_type="image/png",
            file_size=9,
            source="upload",
        )

    def test_an_asset_outside_the_pending_list_survives(self):
        url = reverse(
            "composer:remove_pending_media", kwargs={"workspace_id": self.t["ws"].id, "asset_id": self.asset.id}
        )
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(MediaAsset.objects.filter(pk=self.asset.pk).exists())


class ContributorCannotMoveOthersQueuedPostsTests(TestCase):
    def setUp(self):
        self.t = _tenant("epsilon")
        self.contributor = _member(self.t, WR.CONTRIBUTOR, "epsilon-contrib@example.com")
        self.queue = Queue.objects.create(workspace=self.t["ws"], name="Main", social_account=self.t["account"])
        # The owner's post, not the contributor's.
        self.entry = QueueEntry.objects.create(queue=self.queue, post=self.t["post"])
        self.client.force_login(self.contributor)

    def test_removing_someone_elses_entry_is_refused(self):
        url = reverse(
            "calendar:queue_entry_remove",
            kwargs={"workspace_id": self.t["ws"].id, "queue_id": self.queue.id, "entry_id": self.entry.id},
        )
        response = self.client.post(url)
        self.assertEqual(response.status_code, 403)
        self.assertTrue(QueueEntry.objects.filter(pk=self.entry.pk).exists())

    def test_their_own_entry_is_fine(self):
        own_post = Post.objects.create(workspace=self.t["ws"], author=self.contributor, caption="mine")
        own_entry = QueueEntry.objects.create(queue=self.queue, post=own_post)
        url = reverse(
            "calendar:queue_entry_remove",
            kwargs={"workspace_id": self.t["ws"].id, "queue_id": self.queue.id, "entry_id": own_entry.id},
        )
        response = self.client.post(url)
        self.assertIn(response.status_code, (200, 204))
        self.assertFalse(QueueEntry.objects.filter(pk=own_entry.pk).exists())
