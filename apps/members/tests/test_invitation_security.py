"""Previously read invitation objects cannot revive invalid credentials."""

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.members.models import Invitation, OrgMembership, WorkspaceMembership
from apps.members.services import accept_invitation
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace


class InvitationCredentialTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Private organization")
        self.workspace = Workspace.objects.create(organization=self.org, name="Private workspace")
        self.user = User.objects.create_user(email="invitee@example.com", password="password")
        self.invitation = Invitation.objects.create(
            organization=self.org,
            email=self.user.email,
            expires_at=timezone.now() + timezone.timedelta(days=7),
            workspace_assignments=[{"workspace_id": str(self.workspace.id), "role": "editor"}],
        )

    def _assert_refused(self):
        with self.assertRaises(ValueError):
            accept_invitation(self.invitation, self.user)
        self.assertFalse(OrgMembership.objects.filter(user=self.user, organization=self.org).exists())
        self.assertFalse(WorkspaceMembership.objects.filter(user=self.user, workspace=self.workspace).exists())

    def test_stale_object_cannot_accept_a_revoked_invitation(self):
        Invitation.objects.filter(pk=self.invitation.pk).update(
            expires_at=timezone.now() - timezone.timedelta(seconds=1)
        )
        self._assert_refused()

    def test_stale_object_cannot_accept_a_rotated_invitation(self):
        Invitation.objects.filter(pk=self.invitation.pk).update(token="replacement-token")
        self._assert_refused()

    def test_stale_object_cannot_accept_an_already_used_invitation(self):
        Invitation.objects.filter(pk=self.invitation.pk).update(accepted_at=timezone.now())
        self._assert_refused()

    def test_invitation_does_not_grant_access_to_an_archived_workspace(self):
        self.workspace.is_archived = True
        self.workspace.save(update_fields=["is_archived"])
        accept_invitation(self.invitation, self.user)
        self.assertTrue(OrgMembership.objects.filter(user=self.user, organization=self.org).exists())
        self.assertFalse(WorkspaceMembership.objects.filter(user=self.user, workspace=self.workspace).exists())
