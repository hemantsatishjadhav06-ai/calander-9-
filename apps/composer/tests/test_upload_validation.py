"""Composer and Idea uploads go through the media library's create_asset.

They used to write MediaAsset rows straight from the request, trusting the
client's Content-Type and keeping the client's filename: an SVG with script,
or HTML renamed .png, was stored as-is and served back from the app's own
origin (stored XSS). They also skipped the quota and never queued thumbnail
processing, so composer-uploaded videos had no poster.
"""

import io
import shutil
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.accounts.models import User
from apps.media_library.models import MediaAsset
from apps.media_library.quotas import StorageQuotaExceededError
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace

TEMP_MEDIA_ROOT = tempfile.mkdtemp(prefix="bb-test-composer-upload-")

SVG_XSS = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(document.domain)"></svg>'
HTML_XSS = b"<html><body><script>alert(document.domain)</script></body></html>"


def tearDownModule():
    shutil.rmtree(TEMP_MEDIA_ROOT, ignore_errors=True)


def _png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "blue").save(buf, format="PNG")
    return buf.getvalue()


@override_settings(MEDIA_ROOT=TEMP_MEDIA_ROOT)
class ComposerUploadValidationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="owner@example.com", password="pw", tos_accepted_at=timezone.now())
        self.org = Organization.objects.create(name="Org")
        self.ws = Workspace.objects.create(organization=self.org, name="WS")
        OrgMembership.objects.create(user=self.user, organization=self.org, org_role=OrgMembership.OrgRole.OWNER)
        WorkspaceMembership.objects.create(
            user=self.user, workspace=self.ws, workspace_role=WorkspaceMembership.WorkspaceRole.OWNER
        )
        self.client.force_login(self.user)
        kw = {"workspace_id": self.ws.id}
        self.urls = {
            "upload_media": reverse("composer:upload_media", kwargs=kw),
            "thumbnail_upload": reverse("composer:thumbnail_upload", kwargs=kw),
            "idea_upload_media": reverse("composer:idea_upload_media", kwargs=kw),
        }

    def _post(self, name, filename, content, content_type):
        return self.client.post(self.urls[name], {"file": SimpleUploadedFile(filename, content, content_type)})

    def test_script_payloads_are_rejected_with_a_reason(self):
        for name in self.urls:
            for filename, content, ctype in (
                ("logo.svg", SVG_XSS, "image/svg+xml"),
                ("photo.png", HTML_XSS, "image/png"),
            ):
                with self.subTest(endpoint=name, filename=filename):
                    response = self._post(name, filename, content, ctype)
                    self.assertEqual(response.status_code, 400)
                    self.assertTrue(response.json()["error"])
        self.assertFalse(MediaAsset.objects.exists())

    def test_upload_media_stores_the_sniffed_type_and_queues_processing(self):
        with patch("apps.media_library.tasks.process_media_asset") as enqueue:
            # Client claims a video; the bytes are a PNG.
            response = self._post("upload_media", "clip.mp4", _png_bytes(), "video/mp4")

        self.assertEqual(response.status_code, 200)
        asset = MediaAsset.objects.get()
        self.assertEqual(response["X-Uploaded-Asset-Id"], str(asset.id))
        self.assertEqual(asset.mime_type, "image/png")
        self.assertEqual(asset.media_type, MediaAsset.MediaType.IMAGE)
        self.assertTrue(asset.file.name.endswith(".png"))
        self.assertEqual(asset.filename, "clip.mp4")
        # Still a composer scratch upload, so the orphan sweep can reclaim it.
        self.assertEqual(asset.source, "upload")
        enqueue.assert_called_once_with(str(asset.id))

    def test_thumbnail_upload_checks_the_bytes_not_the_header(self):
        response = self._post("thumbnail_upload", "thumb.png", b"%PDF-1.4 not an image", "image/png")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Only image files are allowed")

        with patch("apps.media_library.tasks.process_media_asset") as enqueue:
            response = self._post("thumbnail_upload", "thumb.png", _png_bytes(), "application/octet-stream")
        self.assertEqual(response.status_code, 200)
        asset = MediaAsset.objects.get(pk=response.json()["asset_id"])
        self.assertEqual(asset.mime_type, "image/png")
        enqueue.assert_called_once_with(str(asset.id))

    def test_idea_upload_returns_the_asset_and_queues_processing(self):
        with patch("apps.media_library.tasks.process_media_asset") as enqueue:
            response = self._post("idea_upload_media", "idea.png", _png_bytes(), "image/png")

        self.assertEqual(response.status_code, 200)
        asset = MediaAsset.objects.get(pk=response.json()["asset_id"])
        self.assertEqual(asset.source, "upload")
        enqueue.assert_called_once_with(str(asset.id))

    def test_over_quota_is_a_400_with_the_quota_message(self):
        with patch(
            "apps.media_library.quotas.enforce_storage_quota",
            side_effect=StorageQuotaExceededError(used=900, limit=1000, attempted=200),
        ):
            for name in self.urls:
                with self.subTest(endpoint=name):
                    response = self._post(name, "a.png", _png_bytes(), "image/png")
                    self.assertEqual(response.status_code, 400)
                    self.assertIn("quota", response.json()["error"].lower())
        self.assertFalse(MediaAsset.objects.exists())
