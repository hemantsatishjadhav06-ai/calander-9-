"""Round-5 media-library findings, each pinned by what the user lost or saw.

- The orphan sweep deleted library uploads after 14 days; it now only touches
  composer scratch uploads.
- A folder name with a quote ran as script in every member's browser.
- An upload over the storage quota was a 500 on the library page.
- Junk ``?folder=`` / ``?uploader=`` values were 500s; junk trim ranges too.
- Two root folders could share a name.
- An image edit never reached the file that gets published.
"""

from datetime import timedelta
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.media_library.models import MediaAsset, MediaFolder
from apps.media_library.quotas import StorageQuotaExceededError
from apps.media_library.services import create_folder, sweep_orphaned_media
from apps.members.models import OrgMembership, WorkspaceMembership
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


class MediaBase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Org")
        self.ws = Workspace.objects.create(organization=self.org, name="WS")
        self.owner = _user("owner@example.com")
        OrgMembership.objects.create(user=self.owner, organization=self.org, org_role="owner")
        WorkspaceMembership.objects.create(user=self.owner, workspace=self.ws, workspace_role=WR.OWNER)
        self.client.force_login(self.owner)

    def _asset(self, *, source="", workspace="ws", **extra):
        asset = MediaAsset.objects.create(
            organization=self.org,
            workspace=self.ws if workspace == "ws" else None,
            uploaded_by=self.owner,
            file=ContentFile(b"x" * 10, name="a.jpg"),
            filename="a.jpg",
            media_type=MediaAsset.MediaType.IMAGE,
            mime_type="image/jpeg",
            file_size=10,
            source=source,
            **extra,
        )
        MediaAsset.objects.filter(pk=asset.pk).update(created_at=timezone.now() - timedelta(days=30))
        return asset


class OrphanSweepScopeTests(MediaBase):
    def test_library_uploads_are_never_swept(self):
        library = self._asset()  # create_asset leaves source blank
        shared = self._asset(source="upload", workspace=None)
        starred = self._asset(source="upload", is_starred=True)
        folder = create_folder(self.org, self.ws, "Keep")
        filed = self._asset(source="upload", folder=folder)
        tagged = self._asset(source="upload", tags=["brand"])

        result = sweep_orphaned_media(min_age_days=14)

        self.assertEqual(result["deleted"], 0)
        for asset in (library, shared, starred, filed, tagged):
            self.assertTrue(MediaAsset.objects.filter(pk=asset.pk).exists())

    def test_composer_scratch_uploads_are_swept(self):
        scratch = self._asset(source="upload")
        result = sweep_orphaned_media(min_age_days=14)
        self.assertEqual(result["deleted"], 1)
        self.assertFalse(MediaAsset.objects.filter(pk=scratch.pk).exists())


class FolderNameInjectionTests(MediaBase):
    def test_a_quote_in_a_folder_name_never_enters_an_alpine_expression(self):
        create_folder(self.org, self.ws, "x'; alert(1); '")
        response = self.client.get(reverse("media_library:index", kwargs={"workspace_id": self.ws.id}))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertNotIn("x-text=\"'", html)
        self.assertNotIn("folderDeleteName = '", html)
        self.assertIn('data-name="x&#x27;; alert(1); &#x27;"', html)

    def test_two_root_folders_cannot_share_a_name(self):
        create_folder(self.org, self.ws, "Brand")
        response = self.client.post(
            reverse("media_library:folder_create", kwargs={"workspace_id": self.ws.id}), {"name": "Brand"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(MediaFolder.objects.filter(workspace=self.ws, name="Brand").count(), 1)


class UploadAndFilterEdgeTests(MediaBase):
    def test_over_quota_is_reported_not_a_500(self):
        url = reverse("media_library:upload", kwargs={"workspace_id": self.ws.id})
        with patch(
            "apps.media_library.views.create_asset",
            side_effect=StorageQuotaExceededError(used=900, limit=1000, attempted=200),
        ):
            response = self.client.post(url, {"files": SimpleUploadedFile("a.jpg", b"\xff\xd8\xff", "image/jpeg")})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["status"], "error")
        self.assertIn("quota", response.json()["results"][0]["errors"][0].lower())

    def test_junk_filter_values_are_ignored(self):
        url = reverse("media_library:index", kwargs={"workspace_id": self.ws.id})
        self.assertEqual(self.client.get(url, {"folder": "not-a-uuid"}).status_code, 200)
        self.assertEqual(self.client.get(url, {"uploader": "not-a-uuid"}).status_code, 200)

    def test_a_nonsense_trim_range_is_a_400(self):
        asset = MediaAsset.objects.create(
            organization=self.org,
            workspace=self.ws,
            uploaded_by=self.owner,
            file=ContentFile(b"v" * 10, name="v.mp4"),
            filename="v.mp4",
            media_type=MediaAsset.MediaType.VIDEO,
            mime_type="video/mp4",
            file_size=10,
            duration=30,
        )
        url = reverse("media_library:asset_edit", kwargs={"workspace_id": self.ws.id, "asset_id": asset.id})
        for start, end in (("nan", "5"), ("-1", "5"), ("9", "5"), ("abc", "5"), ("0", "500")):
            with self.subTest(start=start, end=end):
                response = self.client.post(url, {"trim_start": start, "trim_end": end})
                self.assertEqual(response.status_code, 400)
        self.assertFalse(asset.versions.exists())


class EditsReachThePublishedFileTests(MediaBase):
    def test_an_image_edit_replaces_the_asset_file_and_keeps_the_original_as_a_version(self):
        from apps.media_library.tasks import process_image_edit

        asset = self._asset(source="upload")
        original_name = asset.file.name
        url = reverse("media_library:asset_edit", kwargs={"workspace_id": self.ws.id, "asset_id": asset.id})

        edited = ContentFile(b"edited-bytes", name="edited.jpg")
        with (
            patch("apps.media_library.views.process_image_edit") as enqueue,
            patch("apps.media_library.tasks.apply_image_edits", return_value=(edited, (10, 10))),
            patch("apps.media_library.tasks.generate_image_thumbnail", return_value=None),
        ):
            response = self.client.post(url, {"rotate": "90"})
            self.assertEqual(response.status_code, 302)
            version_id = enqueue.call_args[0][0]
            process_image_edit.task_function(version_id, {"rotate": 90})

        asset.refresh_from_db()
        self.assertNotEqual(asset.file.name, original_name, "the published file must be the edited one")
        self.assertEqual(asset.file_size, len(b"edited-bytes"))
        versions = list(asset.versions.order_by("version_number"))
        self.assertEqual([v.change_description for v in versions][:1], ["Original upload"])
        self.assertEqual(versions[0].file.name, original_name)
        self.assertEqual(asset.current_version_id, versions[-1].pk)
