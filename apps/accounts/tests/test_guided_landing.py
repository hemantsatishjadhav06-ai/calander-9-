"""The first signed-in screen matches what that member can actually do."""

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["owner", "manager", "editor", "viewer", "client"])
def test_signed_in_landing_preserves_role_boundaries(client, role):
    person = User.objects.create_user(
        email=f"landing-{role}@example.com", password="test-password-123", tos_accepted_at=timezone.now()
    )
    organization = Organization.objects.create(name="Landing agency")
    workspace = Workspace.objects.create(organization=organization, name="Landing client")
    OrgMembership.objects.create(user=person, organization=organization, org_role="member")
    WorkspaceMembership.objects.create(user=person, workspace=workspace, workspace_role=role)
    person.last_workspace_id = workspace.pk
    person.save(update_fields=["last_workspace_id"])
    client.force_login(person)

    response = client.get("/")
    route = "calendar:calendar" if role in {"viewer", "client"} else "studio:index"
    assert response.status_code == 302
    assert response["Location"] == reverse(route, kwargs={"workspace_id": workspace.pk})
    landed = client.get(response["Location"])
    assert landed.status_code == 200
    if role not in {"viewer", "client"}:
        # Home: the conversation with the team, with the Today card first.
        assert b"data-home-today" in landed.content and b"data-home-thread" in landed.content
    else:
        assert client.get(reverse("studio:workflow", kwargs={"workspace_id": workspace.pk})).status_code == 403


@pytest.mark.django_db
def test_last_workspace_in_a_deleted_organization_does_not_trap_the_user(client):
    person = User.objects.create_user(
        email="landing-deleted@example.com", password="test-password-123", tos_accepted_at=timezone.now()
    )
    organization = Organization.objects.create(name="Old agency", deleted_at=timezone.now())
    workspace = Workspace.objects.create(organization=organization, name="Old client")
    WorkspaceMembership.objects.create(user=person, workspace=workspace, workspace_role="owner")
    person.last_workspace_id = workspace.pk
    person.save(update_fields=["last_workspace_id"])
    client.force_login(person)

    response = client.get("/", follow=True)
    assert response.status_code == 200
    person.refresh_from_db()
    assert person.last_workspace_id != workspace.pk
    assert all(str(workspace.pk) not in url for url, _status in response.redirect_chain)


@pytest.mark.django_db
@pytest.mark.parametrize("change", ["organization_access_removed", "deletion_requested"])
def test_landing_skips_a_workspace_with_revoked_current_authority(client, change):
    person = User.objects.create_user(
        email=f"landing-revoked-{change}@example.com", password="test-password-123", tos_accepted_at=timezone.now()
    )
    organization = Organization.objects.create(name="Unavailable agency")
    workspace = Workspace.objects.create(organization=organization, name="Unavailable client")
    access = OrgMembership.objects.create(user=person, organization=organization, org_role="member")
    WorkspaceMembership.objects.create(user=person, workspace=workspace, workspace_role="editor")
    if change == "organization_access_removed":
        access.delete()
    else:
        organization.deletion_requested_at = timezone.now()
        organization.save(update_fields=["deletion_requested_at"])
    person.last_workspace_id = workspace.pk
    person.save(update_fields=["last_workspace_id"])
    client.force_login(person)

    response = client.get("/", follow=True)
    assert response.status_code == 200
    person.refresh_from_db()
    assert person.last_workspace_id != workspace.pk
    assert all(str(workspace.pk) not in url for url, _status in response.redirect_chain)
