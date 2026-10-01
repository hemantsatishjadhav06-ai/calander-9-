"""media_library 0004 must apply to real folder data, and folder deletes must respect it.

The migration swaps the folder-name constraint for one that treats NULL as
equal (root folders, organisation-wide folders). Data the old constraint let
through has to be renamed first, or the index build fails and the deploy
aborts. Each case below is a shape that failed or misbehaved in review.
"""

from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.media_library.models import MediaFolder
from apps.media_library.services import create_folder
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace

APP = "media_library"
BEFORE = "0003_pendingupload"


def _migrate(target: str) -> None:
    MigrationExecutor(connection).migrate([(APP, target)])


def _head() -> str:
    return MigrationExecutor(connection).loader.graph.leaf_nodes(APP)[0][1]


@pytest.fixture
def rewound():
    _migrate(BEFORE)
    yield
    _migrate(_head())


def _names(**scope):
    return sorted(MediaFolder.objects.filter(**scope).values_list("name", flat=True))


@pytest.mark.django_db(transaction=True)
def test_migration_renames_every_kind_of_duplicate_to_a_free_name(rewound):
    org_a = Organization.objects.create(name="A")
    org_b = Organization.objects.create(name="B")
    ws = Workspace.objects.create(organization=org_a, name="W")

    # Root duplicates next to an existing "X (2)": the old code reused "X (2)".
    for name in ["X", "X", "X (2)"]:
        MediaFolder.objects.create(organization=org_a, workspace=ws, name=name)
    # Organisation-wide root folders with the same name in two tenants.
    shared_a = MediaFolder.objects.create(organization=org_a, workspace=None, name="Shared")
    shared_b = MediaFolder.objects.create(organization=org_b, workspace=None, name="Shared")
    # Organisation-wide subfolders with duplicate names under one parent.
    for _ in range(2):
        MediaFolder.objects.create(organization=org_a, workspace=None, parent_folder=shared_a, name="Sub")
    # Two different long names that only differ after character 240.
    long_1, long_2 = "L" * 245 + "one", "L" * 245 + "two"
    for name in [long_1, long_1, long_2, long_2]:
        MediaFolder.objects.create(organization=org_a, workspace=ws, name=name)

    _migrate(_head())

    roots = _names(organization=org_a, workspace=ws, parent_folder=None)
    assert {"X", "X (2)", "X (3)"} <= set(roots)
    assert len(roots) == len(set(roots)) == 7
    assert all(len(n) <= 255 for n in roots)
    # Neither tenant's folder was renamed because of the other's.
    shared_a.refresh_from_db()
    shared_b.refresh_from_db()
    assert (shared_a.name, shared_b.name) == ("Shared", "Shared")
    assert _names(parent_folder=shared_a) == ["Sub", "Sub (2)"]
    # The new constraint is really there.
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT indexdef FROM pg_indexes WHERE tablename = 'media_library_folder' "
            "AND indexname = 'unique_folder_name_per_parent'"
        )
        indexdef = cursor.fetchone()[0]
    assert "organization_id" in indexdef and "NULLS NOT DISTINCT" in indexdef


@pytest.fixture
def owner_client(db):
    user = User.objects.create_user(email="folders@example.com", password="pw", tos_accepted_at=timezone.now())
    org = Organization.objects.create(name="Org")
    ws = Workspace.objects.create(organization=org, name="W")
    OrgMembership.objects.get_or_create(user=user, organization=org, defaults={"org_role": "owner"})
    WorkspaceMembership.objects.create(user=user, workspace=ws, workspace_role=WorkspaceMembership.WorkspaceRole.OWNER)
    client = Client()
    client.force_login(user)
    return client, org, ws


def test_deleting_a_folder_promotes_children_without_name_clashes(owner_client):
    client, org, ws = owner_client
    brand = create_folder(org, ws, "Brand")
    create_folder(org, ws, "Logos")
    create_folder(org, ws, "Brand", parent_folder=brand)  # same name as its parent
    create_folder(org, ws, "Logos", parent_folder=brand)  # same name as a root sibling

    resp = client.post(reverse("media_library:folder_delete", kwargs={"workspace_id": ws.id, "folder_id": brand.id}))

    assert resp.status_code == 200
    assert _names(workspace=ws, parent_folder=None) == ["Brand", "Logos", "Logos (2)"]
    assert not MediaFolder.objects.filter(pk=brand.pk).exists()


def test_create_folder_scopes_duplicates_by_organisation(db):
    org_a = Organization.objects.create(name="A")
    org_b = Organization.objects.create(name="B")
    create_folder(org_a, None, "Shared")
    create_folder(org_b, None, "Shared")  # another tenant: allowed
    with pytest.raises(Exception, match="already exists"):
        create_folder(org_a, None, "Shared")


def test_deleting_a_folder_whose_id_is_a_sibling_name_still_works(owner_client):
    client, org, ws = owner_client
    doomed = create_folder(org, ws, "Doomed")
    create_folder(org, ws, "Child", parent_folder=doomed)
    create_folder(org, ws, str(doomed.pk))  # a sibling deliberately named after the doomed folder's id

    resp = client.post(reverse("media_library:folder_delete", kwargs={"workspace_id": ws.id, "folder_id": doomed.id}))

    assert resp.status_code == 200
    assert _names(workspace=ws, parent_folder=None) == sorted(["Child", str(doomed.pk)])


def test_promotion_renames_only_children_that_really_clash(owner_client):
    client, org, ws = owner_client
    create_folder(org, ws, "A")
    doomed = create_folder(org, ws, "F")
    clashing = create_folder(org, ws, "A", parent_folder=doomed)  # older, clashes with root "A"
    free = create_folder(org, ws, "A (2)", parent_folder=doomed)  # free at root: must keep its name

    client.post(reverse("media_library:folder_delete", kwargs={"workspace_id": ws.id, "folder_id": doomed.id}))

    free.refresh_from_db()
    clashing.refresh_from_db()
    assert free.name == "A (2)"
    assert clashing.name == "A (3)"


@pytest.mark.parametrize("view", ["folder_create", "folder_rename"])
def test_a_nul_byte_in_a_folder_name_is_a_400_not_a_500(owner_client, view):
    client, org, ws = owner_client
    kwargs = {"workspace_id": ws.id}
    if view == "folder_rename":
        kwargs["folder_id"] = create_folder(org, ws, "Plain").id
    resp = client.post(reverse(f"media_library:{view}", kwargs=kwargs), {"name": "a\x00b"})
    assert resp.status_code == 400


def test_a_double_submit_that_races_past_the_check_is_a_400(owner_client, monkeypatch):
    client, org, ws = owner_client
    create_folder(org, ws, "Brand")
    # The second request's existence check ran before the first one's insert.
    monkeypatch.setattr("django.db.models.query.QuerySet.exists", lambda self: False)
    resp = client.post(reverse("media_library:folder_create", kwargs={"workspace_id": ws.id}), {"name": "Brand"})
    assert resp.status_code == 400
    assert _names(workspace=ws, parent_folder=None) == ["Brand"]
