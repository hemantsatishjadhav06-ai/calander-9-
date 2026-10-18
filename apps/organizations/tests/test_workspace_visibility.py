"""Organization membership alone does not reveal every workspace roster."""

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace


class WorkspaceVisibilityTests(TestCase):
    def test_member_sees_only_assigned_workspaces_but_admin_sees_all(self):
        user = User.objects.create_user(email="member@example.com", password="password", tos_accepted_at=timezone.now())
        org = Organization.objects.create(name="Agency")
        allowed = Workspace.objects.create(organization=org, name="Assigned brand")
        Workspace.objects.create(organization=org, name="Private unassigned brand")
        membership = OrgMembership.objects.create(user=user, organization=org, org_role="member")
        WorkspaceMembership.objects.create(user=user, workspace=allowed, workspace_role="client")
        user.last_workspace_id = allowed.id
        user.save(update_fields=["last_workspace_id"])
        self.client.force_login(user)
        response = self.client.get(reverse("organizations:workspaces"))
        self.assertContains(response, "Assigned brand")
        self.assertNotContains(response, "Private unassigned brand")

        membership.org_role = "admin"
        membership.save(update_fields=["org_role"])
        self.assertContains(self.client.get(reverse("organizations:workspaces")), "Private unassigned brand")
