"""A portal link must be revocable without deleting the client.

A magic link is a bearer credential: anyone holding the URL is that client for
the rest of its lifetime. The service layer could expire one, but nothing was
wired to it — so a forwarded or leaked link could only be cut off by deleting
the client's membership, which takes their approval history with it.
"""

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.client_portal.models import MagicLinkToken
from apps.client_portal.services import generate_magic_link
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace


@pytest.fixture
def portal(db):
    org = Organization.objects.create(name="Org")
    workspace = Workspace.objects.create(organization=org, name="WS")
    manager = User.objects.create_user(
        email="manager@example.com", password="x", name="Manager", tos_accepted_at=timezone.now()
    )
    client_user = User.objects.create_user(
        email="client@example.com", password="x", name="Client", tos_accepted_at=timezone.now()
    )
    OrgMembership.objects.create(user=manager, organization=org, org_role="owner")
    WorkspaceMembership.objects.create(
        user=manager, workspace=workspace, workspace_role=WorkspaceMembership.WorkspaceRole.MANAGER
    )
    membership = WorkspaceMembership.objects.create(
        user=client_user, workspace=workspace, workspace_role=WorkspaceMembership.WorkspaceRole.CLIENT
    )
    return workspace, client_user, manager, membership


def revoke_url(workspace, membership):
    return reverse(
        "client_portal_admin:revoke_magic_link",
        kwargs={"workspace_id": workspace.id, "membership_id": membership.id},
    )


def active(client_user, workspace):
    return MagicLinkToken.objects.filter(user=client_user, workspace=workspace, expires_at__gt=timezone.now())


@pytest.mark.django_db
def test_revoking_expires_the_live_link_and_keeps_the_client(client, portal):
    workspace, client_user, manager, membership = portal
    generate_magic_link(workspace=workspace, client_user=client_user, created_by=manager)
    assert active(client_user, workspace).count() == 1

    client.force_login(manager)
    response = client.post(revoke_url(workspace, membership))

    assert response.status_code == 302
    assert response["Location"].endswith("/settings/clients/")
    assert active(client_user, workspace).count() == 0
    # The client is still a client — only the credential is gone.
    assert WorkspaceMembership.objects.filter(pk=membership.pk).exists()


@pytest.mark.django_db
def test_a_manager_of_another_workspace_cannot_revoke(client, portal):
    workspace, client_user, manager, membership = portal
    generate_magic_link(workspace=workspace, client_user=client_user, created_by=manager)

    other_org = Organization.objects.create(name="Other")
    other_ws = Workspace.objects.create(organization=other_org, name="Other WS")
    outsider = User.objects.create_user(
        email="outsider@example.com", password="x", name="Outsider", tos_accepted_at=timezone.now()
    )
    OrgMembership.objects.create(user=outsider, organization=other_org, org_role="owner")
    WorkspaceMembership.objects.create(
        user=outsider, workspace=other_ws, workspace_role=WorkspaceMembership.WorkspaceRole.MANAGER
    )

    client.force_login(outsider)
    response = client.post(revoke_url(workspace, membership))

    assert response.status_code == 403
    assert active(client_user, workspace).count() == 1


@pytest.mark.django_db
def test_revoking_twice_is_harmless(client, portal):
    workspace, client_user, manager, membership = portal
    generate_magic_link(workspace=workspace, client_user=client_user, created_by=manager)

    client.force_login(manager)
    client.post(revoke_url(workspace, membership))
    response = client.post(revoke_url(workspace, membership))

    assert response.status_code == 302
    assert active(client_user, workspace).count() == 0
