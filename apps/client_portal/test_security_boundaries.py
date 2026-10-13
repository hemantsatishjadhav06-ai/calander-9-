"""An approval link must remain scoped, revocable, and client-only."""

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.approvals.models import PostComment
from apps.client_portal.models import MagicLinkToken
from apps.client_portal.services import consume_magic_link, peek_magic_link, revoke_magic_link
from apps.composer.models import PlatformPost, Post
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


class PortalSecurityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="client@example.com", password="original-password", tos_accepted_at=timezone.now()
        )
        self.org = Organization.objects.create(name="Agency")
        self.workspace = Workspace.objects.create(organization=self.org, name="Client workspace")
        OrgMembership.objects.create(user=self.user, organization=self.org, org_role="member")
        self.membership = WorkspaceMembership.objects.create(
            user=self.user, workspace=self.workspace, workspace_role="client"
        )
        self.token = MagicLinkToken.objects.create(user=self.user, workspace=self.workspace)

    def _login(self):
        response = self.client.post(reverse("client_portal:magic_link_entry", kwargs={"token": self.token.token}))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.client.session.get("is_portal_session"))

    def _assert_portal_revoked(self):
        response = self.client.get(reverse("client_portal:dashboard"))
        self.assertRedirects(response, reverse("client_portal:magic_link_expired") + "?reason=signed_out")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_link_does_not_authenticate_after_membership_removal(self):
        self.membership.delete()
        self.assertIsNone(peek_magic_link(self.token.token))
        self.assertEqual(consume_magic_link(self.token.token), (None, None, False))
        self.token.refresh_from_db()
        self.assertFalse(self.token.is_consumed)

    def test_link_does_not_authenticate_an_inactive_account(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        response = self.client.post(reverse("client_portal:magic_link_entry", kwargs={"token": self.token.token}))
        self.assertRedirects(response, reverse("client_portal:magic_link_expired") + "?reason=invalid")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_old_link_cannot_become_a_staff_login(self):
        self.membership.workspace_role = "owner"
        self.membership.save(update_fields=["workspace_role"])
        self.assertEqual(consume_magic_link(self.token.token), (None, None, False))

    def test_revoking_consumed_link_ends_active_session(self):
        self._login()
        self.assertEqual(self.client.get(reverse("client_portal:dashboard")).status_code, 200)
        revoke_magic_link(self.token.id, self.workspace)
        self._assert_portal_revoked()

    def test_role_change_ends_active_session(self):
        self._login()
        self.membership.workspace_role = "editor"
        self.membership.save(update_fields=["workspace_role"])
        self._assert_portal_revoked()

    def test_archiving_workspace_ends_active_session(self):
        self._login()
        self.workspace.is_archived = True
        self.workspace.save(update_fields=["is_archived"])
        self._assert_portal_revoked()

    def test_approval_link_cannot_change_account_or_authorize_oauth(self):
        self._login()
        response = self.client.post(reverse("accounts:settings"), {"action": "update_name", "name": "changed"})
        self.assertEqual(response.status_code, 403)
        self.user.refresh_from_db()
        self.assertEqual(self.user.name, "")
        self.assertEqual(self.client.get("/oauth/authorize/").status_code, 403)

    def test_approval_link_cannot_access_another_workspace_the_account_owns(self):
        owned = self.user.workspace_memberships.get(workspace_role="owner").workspace
        self._login()
        response = self.client.get(reverse("calendar:calendar", kwargs={"workspace_id": owned.id}))
        self.assertEqual(response.status_code, 403)
        self.assertRedirects(self.client.get("/"), reverse("client_portal:dashboard"))

    def test_internal_replies_are_not_exposed_below_external_comments(self):
        account = SocialAccount.objects.create(
            workspace=self.workspace, platform="bluesky", account_platform_id="client-account", account_name="Agency"
        )
        post = Post.objects.create(workspace=self.workspace, author=self.user, caption="Review me")
        PlatformPost.objects.create(post=post, social_account=account, status="pending_client")
        comment = PostComment.objects.create(
            post=post, author=self.user, body="External discussion", visibility="external"
        )
        PostComment.objects.create(
            post=post,
            author=self.user,
            parent_comment=comment,
            body="Private pricing discussion",
            visibility="internal",
        )
        PostComment.objects.create(
            post=post, author=self.user, parent_comment=comment, body="Client-visible reply", visibility="external"
        )
        self._login()
        response = self.client.get(reverse("client_portal:approval_queue"))
        self.assertContains(response, "External discussion")
        self.assertContains(response, "Client-visible reply")
        self.assertNotContains(response, "Private pricing discussion")
