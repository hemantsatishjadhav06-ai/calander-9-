import os
import uuid
from datetime import timedelta

import pytest
from django.core.files.base import ContentFile
from django.utils import timezone

from apps.approvals import gate
from apps.approvals.actor import acting_as
from apps.composer.models import PlatformPost, Post
from apps.organizations.models import Organization
from apps.studio.tests.conftest import jpeg_bytes
from apps.workspaces.models import Workspace


def _post(world, key, asset_id):
    world.workspace.require_dashboard_approval = True
    world.workspace.save(update_fields=["require_dashboard_approval"])
    post = Post.objects.create(workspace=world.workspace, author=world.editor, caption="Reviewed final content")
    return PlatformPost.objects.create(
        post=post,
        social_account=world.linkedin,
        status="pending_review",
        scheduled_at=timezone.now() + timedelta(days=1),
        platform_extra={key: str(asset_id)},
    )


def _approve(world, row):
    with acting_as(world.owner):
        row.transition_to("approved")
        row.save()
    assert row.approved_fingerprint == gate.fingerprint(row)


@pytest.mark.parametrize("key", ["thumbnail_asset_id", "cover_image_asset_id"])
def test_same_key_bytes_changed_after_approval_are_blocked(world, photo, key):
    asset = photo(data=jpeg_bytes(100, 100))
    row = _post(world, key, asset.pk)
    _approve(world, row)
    before = gate.fingerprint(row)
    path = asset.file.path
    stat = os.stat(path)
    with asset.file.storage.open(asset.file.name, "rb") as source:
        content = bytearray(source.read())
    content[-3] ^= 1
    with asset.file.storage.open(asset.file.name, "wb") as target:
        target.write(content)
    # Byte identity must matter even if the key, length, version and filesystem
    # timestamp are unchanged. A remote object has no local stat identity.
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    asset.refresh_from_db()
    assert asset.file_size == len(content)
    assert gate.fingerprint(row) != before
    assert "changed after approval" in gate.publish_blocker(row)


@pytest.mark.parametrize("key", ["thumbnail_asset_id", "cover_image_asset_id"])
def test_editing_a_referenced_visual_withdraws_approval_without_postmedia(
    world, photo, key, django_capture_on_commit_callbacks
):
    asset = photo(data=jpeg_bytes(100, 100))
    with django_capture_on_commit_callbacks(execute=True):
        row = _post(world, key, asset.pk)
        _approve(world, row)
        asset.file.save("reviewed-visual-edited.jpg", ContentFile(jpeg_bytes(100, 100, (200, 30, 40))), save=True)
    row.refresh_from_db()
    assert row.status == "pending_review" and row.approved_fingerprint == ""


@pytest.mark.parametrize("key", ["thumbnail_asset_id", "cover_image_asset_id"])
@pytest.mark.parametrize("kind", ["foreign_workspace", "foreign_shared_org", "missing_id", "missing_file"])
def test_unavailable_or_foreign_reference_cannot_receive_human_approval(world, photo, key, kind):
    asset = photo()
    if kind == "foreign_workspace":
        asset.workspace = Workspace.objects.create(organization=world.org, name="Another brand")
        asset.save(update_fields=["workspace"])
    elif kind == "foreign_shared_org":
        asset.workspace = None
        asset.organization = Organization.objects.create(name="Another tenant")
        asset.save(update_fields=["workspace", "organization"])
    elif kind == "missing_file":
        asset.file.delete(save=False)
    row = _post(world, key, uuid.uuid4() if kind == "missing_id" else asset.pk)
    with acting_as(world.owner), pytest.raises(gate.ApprovalRequired, match="unavailable"):
        row.transition_to("approved")
    row.refresh_from_db()
    assert row.status == "pending_review" and row.approved_fingerprint == ""


@pytest.mark.parametrize("key", ["thumbnail_asset_id", "cover_image_asset_id"])
def test_org_shared_reference_is_visible_and_bound_to_approval(world, photo, key):
    asset = photo()
    asset.workspace = None
    asset.save(update_fields=["workspace"])
    row = _post(world, key, asset.pk)
    _approve(world, row)
    assert gate.publish_blocker(row) is None


@pytest.mark.parametrize("key", ["thumbnail_asset_id", "cover_image_asset_id"])
def test_deleted_reference_cannot_keep_approval(world, photo, key, django_capture_on_commit_callbacks):
    asset = photo()
    with django_capture_on_commit_callbacks(execute=True):
        row = _post(world, key, asset.pk)
        _approve(world, row)
        asset.delete()
    row.refresh_from_db()
    assert row.status == "pending_review" and row.approved_fingerprint == ""
