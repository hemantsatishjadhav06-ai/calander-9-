"""Security regression tests for approvals comments (V9)."""

from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.approvals import comments
from apps.approvals.models import PostComment
from apps.composer.models import Post
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace


def _make_user(email):
    user = User.objects.create_user(
        email=email,
        password="testpass123",
        tos_accepted_at=timezone.now(),
    )
    # The accounts post_save signal auto-provisions a default Organization +
    # Workspace + OrgMembership for every new User. Tests that want to attach
    # the user to a specific org must start from a clean slate, otherwise the
    # RBAC middleware (which does OrgMembership.objects.filter(...).first())
    # may pick the auto-org instead of the test org.
    from apps.members.models import OrgMembership, WorkspaceMembership
    from apps.organizations.models import Organization

    auto_org_ids = list(OrgMembership.objects.filter(user=user).values_list("organization_id", flat=True))
    WorkspaceMembership.objects.filter(user=user).delete()
    OrgMembership.objects.filter(user=user).delete()
    Organization.objects.filter(id__in=auto_org_ids).delete()
    return user


class EditCommentWorkspaceScopeTests(TestCase):
    """V9: edit_comment must reject cross-workspace post_id."""

    def setUp(self):
        self.org = Organization.objects.create(name="Test Org")
        self.ws_a = Workspace.objects.create(organization=self.org, name="WS-A")
        self.ws_b = Workspace.objects.create(organization=self.org, name="WS-B")
        self.user = _make_user("user@example.com")
        OrgMembership.objects.create(user=self.user, organization=self.org, org_role="owner")
        WorkspaceMembership.objects.create(user=self.user, workspace=self.ws_a, workspace_role="editor")
        WorkspaceMembership.objects.create(user=self.user, workspace=self.ws_b, workspace_role="editor")

        self.post_b = Post.objects.create(workspace=self.ws_b, author=self.user, caption="b")
        self.comment = PostComment.objects.create(
            post=self.post_b,
            author=self.user,
            body="hi",
            visibility=PostComment.Visibility.INTERNAL,
        )

    def test_cross_workspace_edit_returns_404(self):
        self.client.force_login(self.user)
        # Edit a comment that lives in WS-B, but POST through WS-A's URL.
        url = reverse(
            "approvals:edit_comment",
            kwargs={
                "workspace_id": self.ws_a.id,
                "post_id": self.post_b.id,
                "comment_id": self.comment.id,
            },
        )
        response = self.client.post(url, data={"body": "rewritten"})
        self.assertEqual(response.status_code, 404)
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.body, "hi")

    def test_same_workspace_edit_succeeds(self):
        self.client.force_login(self.user)
        url = reverse(
            "approvals:edit_comment",
            kwargs={
                "workspace_id": self.ws_b.id,
                "post_id": self.post_b.id,
                "comment_id": self.comment.id,
            },
        )
        response = self.client.post(url, data={"body": "rewritten"})
        self.assertLess(response.status_code, 400)
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.body, "rewritten")


class CommentVisibilityTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Org")
        self.ws = Workspace.objects.create(organization=self.org, name="WS")
        self.author = _make_user("editor@example.com")
        self.client_user = _make_user("client@example.com")
        WorkspaceMembership.objects.create(user=self.author, workspace=self.ws, workspace_role="editor")
        WorkspaceMembership.objects.create(user=self.client_user, workspace=self.ws, workspace_role="client")
        self.post = Post.objects.create(workspace=self.ws, author=self.author, caption="post")
        self.external = PostComment.objects.create(
            post=self.post, author=self.author, body="External", visibility=PostComment.Visibility.EXTERNAL
        )
        self.internal_reply = PostComment.objects.create(
            post=self.post,
            author=self.author,
            parent_comment=self.external,
            body="Private team reply",
            visibility=PostComment.Visibility.INTERNAL,
        )

    def test_client_cannot_see_internal_replies_on_external_comments(self):
        visible = list(comments.get_comments_for_post(self.post, self.client_user))
        self.assertEqual([comment.id for comment in visible], [self.external.id])
        self.assertEqual(list(visible[0].replies.all()), [])

    def test_team_member_can_see_internal_replies(self):
        visible = list(comments.get_comments_for_post(self.post, self.author))
        self.assertEqual(list(visible[0].replies.all()), [self.internal_reply])

    def test_internal_mentions_do_not_notify_clients(self):
        with patch("apps.approvals.comments.notify") as notify:
            comments.create_comment(
                self.post, self.author, "@client confidential note", PostComment.Visibility.INTERNAL
            )
        notify.assert_not_called()

    def test_external_mentions_still_notify_clients(self):
        with patch("apps.approvals.comments.notify") as notify:
            comments.create_comment(self.post, self.author, "@client please review", PostComment.Visibility.EXTERNAL)
        self.assertEqual(notify.call_args.kwargs["user"], self.client_user)

    def test_client_cannot_create_an_internal_comment(self):
        with self.assertRaises(ValueError):
            comments.create_comment(self.post, self.client_user, "hidden", PostComment.Visibility.INTERNAL)

    def test_unknown_visibility_is_rejected(self):
        with self.assertRaises(ValueError):
            comments.create_comment(self.post, self.author, "hidden", "unknown")

    def test_client_cannot_reply_to_an_internal_comment(self):
        with self.assertRaises(ValueError):
            comments.create_comment(
                self.post,
                self.client_user,
                "response",
                PostComment.Visibility.EXTERNAL,
                parent_id=self.internal_reply.id,
            )
