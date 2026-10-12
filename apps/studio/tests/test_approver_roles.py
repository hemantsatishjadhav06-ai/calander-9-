"""Weekly staff notices use the same current internal role as publication."""

import pytest

from apps.accounts.models import User
from apps.members.models import CustomRole, WorkspaceMembership
from apps.organizations.models import Organization
from apps.studio import autopilot


@pytest.mark.parametrize("change", ["base_client", "client_facing", "foreign_role", "inactive"])
def test_week_ready_recipients_exclude_external_or_revoked_approvers(world, change):
    member = WorkspaceMembership.objects.get(workspace=world.workspace, user=world.owner)
    if change == "inactive":
        User.objects.filter(pk=world.owner.pk).update(is_active=False)
    else:
        org = Organization.objects.create(name="Other client") if change == "foreign_role" else world.org
        role = CustomRole.objects.create(
            organization=org,
            name="Custom review permission",
            permissions={"approve_posts": True, "client_facing": change == "client_facing"},
        )
        member.custom_role = role
        if change == "base_client":
            member.workspace_role = "client"
        member.save()
    recipients = {person.pk for person in autopilot._approvers(world.workspace)}
    assert world.owner.pk not in recipients
    assert world.manager.pk in recipients
