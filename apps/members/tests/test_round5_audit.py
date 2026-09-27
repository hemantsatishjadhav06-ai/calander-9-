"""Round-5 members / analytics / onboarding findings.

- An org admin could remove an owner or another admin.
- Accepting an invitation to a since-deleted workspace was a 500 that left
  the org membership half-applied.
- A failed resend invalidated the link the invitee already had.
- A user in two orgs got a random one per request.
- Assigning a built-in workspace role left a custom role's grants in force.
- The analytics pages ignored ``view_analytics``.
- The checklist's "Invite your team" only ticked for a client.
- A revoked connection link could still page every owner and manager.
"""

from unittest.mock import patch

from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.members import services
from apps.members.middleware import RBACMiddleware
from apps.members.models import CustomRole, Invitation, OrgMembership, WorkspaceMembership
from apps.onboarding.checklist import get_checklist_items
from apps.onboarding.models import ConnectionLink
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace

WR = WorkspaceMembership.WorkspaceRole


def _user(email):
    user = User.objects.create_user(email=email, password="pw", name="u", tos_accepted_at=timezone.now())
    auto = list(OrgMembership.objects.filter(user=user).values_list("organization_id", flat=True))
    WorkspaceMembership.objects.filter(user=user).delete()
    OrgMembership.objects.filter(user=user).delete()
    Organization.objects.filter(id__in=auto).delete()
    return user


class OrgBase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Org")
        self.ws = Workspace.objects.create(organization=self.org, name="WS")
        self.owner = _user("owner@example.com")
        self.owner2 = _user("owner2@example.com")
        self.admin = _user("admin@example.com")
        self.member = _user("member@example.com")
        self.m_owner = OrgMembership.objects.create(user=self.owner, organization=self.org, org_role="owner")
        self.m_owner2 = OrgMembership.objects.create(user=self.owner2, organization=self.org, org_role="owner")
        self.m_admin = OrgMembership.objects.create(user=self.admin, organization=self.org, org_role="admin")
        self.m_member = OrgMembership.objects.create(user=self.member, organization=self.org, org_role="member")
        for user in (self.owner, self.owner2, self.admin):
            WorkspaceMembership.objects.create(user=user, workspace=self.ws, workspace_role=WR.OWNER)


class RemoveMemberHierarchyTests(OrgBase):
    def test_an_admin_cannot_remove_an_owner_even_when_two_exist(self):
        with self.assertRaises(ValueError):
            services.remove_member(self.org, self.m_owner, self.admin)
        self.assertTrue(OrgMembership.objects.filter(pk=self.m_owner.pk).exists())

    def test_an_admin_cannot_remove_another_admin(self):
        other_admin = OrgMembership.objects.create(
            user=_user("a2@example.com"), organization=self.org, org_role="admin"
        )
        with self.assertRaises(ValueError):
            services.remove_member(self.org, other_admin, self.admin)

    def test_an_admin_can_remove_a_member_and_an_owner_can_remove_an_admin(self):
        services.remove_member(self.org, self.m_member, self.admin)
        self.assertFalse(OrgMembership.objects.filter(pk=self.m_member.pk).exists())
        services.remove_member(self.org, self.m_admin, self.owner)
        self.assertFalse(OrgMembership.objects.filter(pk=self.m_admin.pk).exists())

    def test_the_view_refuses_too(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("members:remove", kwargs={"membership_id": self.m_owner.pk}))
        self.assertEqual(response.status_code, 422)
        self.assertTrue(OrgMembership.objects.filter(pk=self.m_owner.pk).exists())


class AcceptInvitationTests(OrgBase):
    def _invitation(self, assignments):
        return Invitation.objects.create(
            organization=self.org,
            email="new@example.com",
            org_role="member",
            workspace_assignments=assignments,
            invited_by=self.owner,
            expires_at=timezone.now() + timezone.timedelta(days=7),
        )

    def test_a_deleted_workspace_in_the_assignments_is_skipped(self):
        gone = Workspace.objects.create(organization=self.org, name="Gone")
        invitation = self._invitation(
            [{"workspace_id": str(gone.id), "role": "editor"}, {"workspace_id": str(self.ws.id), "role": "viewer"}]
        )
        gone.delete()
        newcomer = _user("new@example.com")

        services.accept_invitation(invitation, newcomer)

        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.accepted_at)
        self.assertTrue(OrgMembership.objects.filter(user=newcomer, organization=self.org).exists())
        self.assertEqual(WorkspaceMembership.objects.filter(user=newcomer).count(), 1)
        newcomer.refresh_from_db()
        self.assertEqual(newcomer.last_workspace_id, self.ws.id)

    def test_a_failed_resend_keeps_the_old_link_valid(self):
        invitation = self._invitation([])
        old_token = invitation.token
        with (
            patch("apps.members.services._send_invite_email", return_value=False),
            self.assertRaises(ValueError),
        ):
            services.resend_invitation(invitation)
        invitation.refresh_from_db()
        self.assertEqual(invitation.token, old_token)

    def test_a_successful_resend_rotates_the_token(self):
        invitation = self._invitation([])
        old_token = invitation.token
        with patch("apps.members.services._send_invite_email", return_value=True):
            services.resend_invitation(invitation)
        invitation.refresh_from_db()
        self.assertNotEqual(invitation.token, old_token)

    def test_a_malformed_address_is_refused(self):
        with self.assertRaises(ValueError):
            services.create_invitation(self.org, "not-an-email", "member", [], self.owner, inviter=self.owner)
        self.assertFalse(Invitation.objects.filter(email="not-an-email").exists())


class OrgResolutionTests(OrgBase):
    def test_the_org_owning_the_current_workspace_wins(self):
        other_org = Organization.objects.create(name="Other")
        other_ws = Workspace.objects.create(organization=other_org, name="Other WS")
        OrgMembership.objects.create(user=self.member, organization=other_org, org_role="owner")
        WorkspaceMembership.objects.create(user=self.member, workspace=other_ws, workspace_role=WR.OWNER)
        self.member.last_workspace_id = other_ws.id
        self.member.save(update_fields=["last_workspace_id"])

        request = RequestFactory().get("/members/")
        request.user = self.member
        RBACMiddleware(lambda r: None)(request)
        self.assertEqual(request.org, other_org)

        self.member.last_workspace_id = None
        self.member.save(update_fields=["last_workspace_id"])
        request = RequestFactory().get("/members/")
        request.user = self.member
        RBACMiddleware(lambda r: None)(request)
        # No current workspace: the oldest membership, every time.
        self.assertEqual(request.org, self.org)


class CustomRoleTests(OrgBase):
    def test_assigning_a_builtin_role_clears_a_custom_role(self):
        role = CustomRole.objects.create(
            organization=self.org, name="Power", permissions={"manage_workspace_settings": True}
        )
        membership = WorkspaceMembership.objects.create(
            user=self.member, workspace=self.ws, workspace_role=WR.VIEWER, custom_role=role
        )
        services.update_workspace_assignments(
            self.org, self.member, [{"workspace_id": str(self.ws.id), "role": "editor"}], inviter=self.owner
        )
        membership.refresh_from_db()
        self.assertEqual(membership.workspace_role, WR.EDITOR)
        self.assertIsNone(membership.custom_role)


class AnalyticsPermissionTests(OrgBase):
    def test_a_contributor_is_refused(self):
        WorkspaceMembership.objects.create(user=self.member, workspace=self.ws, workspace_role=WR.CONTRIBUTOR)
        self.client.force_login(self.member)
        response = self.client.get(reverse("analytics:index", kwargs={"workspace_id": self.ws.id}))
        self.assertEqual(response.status_code, 403)

    def test_a_manager_is_not(self):
        WorkspaceMembership.objects.create(user=self.member, workspace=self.ws, workspace_role=WR.MANAGER)
        self.client.force_login(self.member)
        response = self.client.get(reverse("analytics:index", kwargs={"workspace_id": self.ws.id}))
        self.assertEqual(response.status_code, 200)


class OnboardingTests(OrgBase):
    def test_inviting_an_editor_completes_the_team_item(self):
        item = next(i for i in get_checklist_items(self.ws) if i["key"] == "invite_members")
        self.assertFalse(item["completed"])
        WorkspaceMembership.objects.create(user=self.member, workspace=self.ws, workspace_role=WR.EDITOR)
        item = next(i for i in get_checklist_items(self.ws) if i["key"] == "invite_members")
        self.assertTrue(item["completed"])

    def test_a_revoked_link_cannot_page_the_team(self):
        link = ConnectionLink.objects.create(
            workspace=self.ws,
            created_by=self.owner,
            expires_at=timezone.now() - timezone.timedelta(days=1),
        )
        with patch("apps.onboarding.views.notify") as notify:
            response = self.client.post(reverse("onboarding:connection_done", kwargs={"token": link.token}))
        self.assertEqual(response.status_code, 404)
        notify.assert_not_called()

    def test_junk_expiry_days_falls_back(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("onboarding:create_link", kwargs={"workspace_id": self.ws.id}), {"expiry_days": "soon"}
        )
        self.assertIn(response.status_code, (200, 302))
        self.assertTrue(ConnectionLink.objects.filter(workspace=self.ws).exists())


class ChecklistActivationTests(OrgBase):
    def test_a_draft_does_not_count_as_scheduling_a_post(self):
        from apps.composer.models import PlatformPost, Post
        from apps.social_accounts.models import SocialAccount

        account = SocialAccount.objects.create(
            workspace=self.ws, platform="bluesky", account_platform_id="d", account_name="a"
        )
        post = Post.objects.create(workspace=self.ws, author=self.owner, caption="draft")
        pp = PlatformPost.objects.create(post=post, social_account=account, status=PlatformPost.Status.DRAFT)
        item = next(i for i in get_checklist_items(self.ws) if i["key"] == "create_post")
        self.assertFalse(item["completed"])
        PlatformPost.objects.filter(pk=pp.pk).update(status=PlatformPost.Status.SCHEDULED)
        item = next(i for i in get_checklist_items(self.ws) if i["key"] == "create_post")
        self.assertTrue(item["completed"])

    def test_connecting_a_channel_refreshes_the_cached_checklist(self):
        from django.core.cache import cache

        from apps.onboarding.context_processors import _cached_checklist_items
        from apps.social_accounts.models import SocialAccount

        cache.clear()
        before = next(i for i in _cached_checklist_items(self.ws) if i["key"] == "connect_accounts")
        self.assertFalse(before["completed"])
        SocialAccount.objects.create(workspace=self.ws, platform="bluesky", account_platform_id="d", account_name="a")
        after = next(i for i in _cached_checklist_items(self.ws) if i["key"] == "connect_accounts")
        self.assertTrue(after["completed"])
        cache.clear()
