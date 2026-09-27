"""QA round: uploads that fail must say so, and the library UI must not break.

- A rejected upload came back 200 (an empty HTMX body, or JSON the uploader
  never read), so the UI showed "Done" and reloaded; now it is a 400 carrying
  each file's reason.
- The processing-status poll swapped raw JSON over the card it was polling.
- The video player used the plain file URL (no Range support locally, no
  poster), so it sat at 0:00.
- Caddy served all of MEDIA_ROOT, not just the public prefixes Django routes.
- Upload times rendered in UTC instead of the workspace's zone.
"""

import io
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.accounts.models import User
from apps.media_library.models import MediaAsset
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace
from config.urls import PUBLIC_MEDIA_PREFIXES

TEMP_MEDIA_ROOT = tempfile.mkdtemp(prefix="bb-test-upload-feedback-")
WR = WorkspaceMembership.WorkspaceRole


def tearDownModule():
    shutil.rmtree(TEMP_MEDIA_ROOT, ignore_errors=True)


def _png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buf, format="PNG")
    return buf.getvalue()


def _user(email):
    user = User.objects.create_user(email=email, password="pw", name="u", tos_accepted_at=timezone.now())
    auto = list(OrgMembership.objects.filter(user=user).values_list("organization_id", flat=True))
    WorkspaceMembership.objects.filter(user=user).delete()
    OrgMembership.objects.filter(user=user).delete()
    Organization.objects.filter(id__in=auto).delete()
    return user


@override_settings(MEDIA_ROOT=TEMP_MEDIA_ROOT)
class UploadFeedbackBase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Org")
        self.ws = Workspace.objects.create(organization=self.org, name="WS")
        self.owner = _user("owner@example.com")
        OrgMembership.objects.create(user=self.owner, organization=self.org, org_role="owner")
        WorkspaceMembership.objects.create(user=self.owner, workspace=self.ws, workspace_role=WR.OWNER)
        self.client.force_login(self.owner)
        self.upload_url = reverse("media_library:upload", kwargs={"workspace_id": self.ws.id})

    def _asset(self, **extra):
        defaults = {
            "organization": self.org,
            "workspace": self.ws,
            "uploaded_by": self.owner,
            "file": ContentFile(b"v" * 10, name="clip.mp4"),
            "filename": "clip.mp4",
            "media_type": MediaAsset.MediaType.VIDEO,
            "mime_type": "video/mp4",
            "file_size": 10,
        }
        defaults.update(extra)
        return MediaAsset.objects.create(**defaults)


class RejectedUploadTests(UploadFeedbackBase):
    def test_a_rejected_file_is_a_400_with_its_reason(self):
        html = SimpleUploadedFile("evil.png", b"<html><script>alert(1)</script></html>", "image/png")
        response = self.client.post(self.upload_url, {"files": html})

        self.assertEqual(response.status_code, 400)
        result = response.json()["results"][0]
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["filename"], "evil.png")
        self.assertIn("unsupported", result["error"].lower())
        self.assertFalse(MediaAsset.objects.exists())

    def test_an_all_rejected_htmx_batch_is_not_an_empty_200(self):
        html = SimpleUploadedFile("evil.png", b"<svg onload=alert(1)>", "image/png")
        response = self.client.post(self.upload_url, {"files": html}, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["results"][0]["status"], "error")

    def test_a_mixed_batch_reports_both_outcomes(self):
        good = SimpleUploadedFile("ok.png", _png_bytes(), "image/png")
        bad = SimpleUploadedFile("bad.png", b"not an image", "image/png")
        with patch("apps.media_library.views.process_media_asset") as enqueue:
            response = self.client.post(self.upload_url, {"files": [good, bad]})

        self.assertEqual(response.status_code, 400)
        statuses = [r["status"] for r in response.json()["results"]]
        self.assertEqual(statuses, ["ok", "error"])
        self.assertEqual(MediaAsset.objects.count(), 1)
        enqueue.assert_called_once()

    def test_an_accepted_file_is_a_200_and_queued_for_processing(self):
        with patch("apps.media_library.views.process_media_asset") as enqueue:
            response = self.client.post(
                self.upload_url, {"files": SimpleUploadedFile("ok.png", _png_bytes(), "image/png")}
            )

        self.assertEqual(response.status_code, 200)
        asset = MediaAsset.objects.get()
        self.assertEqual(response.json()["results"], [{"id": str(asset.id), "filename": "ok.png", "status": "ok"}])
        enqueue.assert_called_once_with(str(asset.id))

    def test_shared_upload_rejection_is_a_400(self):
        url = reverse("media_library_org:shared_upload")
        response = self.client.post(url, {"files": SimpleUploadedFile("x.png", b"nope", "image/png")})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["results"][0]["filename"], "x.png")
        self.assertTrue(response.json()["results"][0]["error"])


class ProcessingStatusPollTests(UploadFeedbackBase):
    def _poll(self, asset):
        url = reverse("media_library:processing_status", kwargs={"workspace_id": self.ws.id, "asset_id": asset.id})
        return self.client.get(url, HTTP_HX_REQUEST="true")

    def test_pending_returns_the_card_still_polling(self):
        asset = self._asset(processing_status=MediaAsset.ProcessingStatus.PENDING)
        response = self._poll(asset)

        self.assertEqual(response["Content-Type"].split(";")[0], "text/html")
        self.assertContains(response, "ml-asset-card")
        self.assertContains(response, 'hx-trigger="every 3s"')

    def test_failed_returns_a_card_that_stops_polling(self):
        asset = self._asset(processing_status=MediaAsset.ProcessingStatus.FAILED)
        response = self._poll(asset)

        self.assertContains(response, "ml-asset-card")
        self.assertContains(response, "FAILED")
        self.assertNotContains(response, 'hx-trigger="every 3s"')

    def test_non_htmx_callers_still_get_json(self):
        asset = self._asset(processing_status=MediaAsset.ProcessingStatus.PENDING)
        url = reverse("media_library:processing_status", kwargs={"workspace_id": self.ws.id, "asset_id": asset.id})
        self.assertEqual(self.client.get(url).json()["status"], "pending")


class VideoPreviewTests(UploadFeedbackBase):
    def test_detail_player_streams_with_range_support_and_a_poster(self):
        asset = self._asset(
            processing_status=MediaAsset.ProcessingStatus.COMPLETED,
            thumbnail=ContentFile(b"jpg", name="thumb.jpg"),
        )
        url = reverse("media_library:asset_detail", kwargs={"workspace_id": self.ws.id, "asset_id": asset.id})
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        stream = reverse("composer:media_stream", kwargs={"workspace_id": self.ws.id, "asset_id": asset.id})
        self.assertContains(response, f'<source src="{stream}"')
        self.assertContains(response, f'poster="{asset.thumbnail.url}"')

    def test_grid_card_without_a_thumbnail_previews_the_first_frame(self):
        asset = self._asset(processing_status=MediaAsset.ProcessingStatus.COMPLETED)
        response = self.client.get(reverse("media_library:index", kwargs={"workspace_id": self.ws.id}))

        stream = reverse("composer:media_stream", kwargs={"workspace_id": self.ws.id, "asset_id": asset.id})
        self.assertContains(response, f'<video src="{stream}#t=0.1"')
        self.assertContains(response, 'preload="metadata"')


class LocalTimeTests(UploadFeedbackBase):
    def test_upload_time_is_shown_in_the_workspace_zone(self):
        self.ws.timezone = "Asia/Kolkata"
        self.ws.save(update_fields=["timezone"])
        asset = self._asset()
        MediaAsset.objects.filter(pk=asset.pk).update(created_at=datetime(2026, 1, 5, 20, 0, tzinfo=UTC))

        url = reverse("media_library:asset_detail", kwargs={"workspace_id": self.ws.id, "asset_id": asset.id})
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        # 20:00 UTC is 01:30 the next day in India.
        self.assertContains(response, "Jan 6, 2026 1:30 AM")
        self.assertNotContains(response, "Jan 5, 2026 8:00 PM")


def test_caddy_serves_only_the_public_media_prefixes():
    caddyfile = (Path(settings.BASE_DIR) / "Caddyfile").read_text()
    match = re.search(r"@public_media path (.+)", caddyfile)
    assert match, "Caddyfile must restrict /media/ to a @public_media matcher"
    served = {p.strip("/*") + "/" for p in match.group(1).split()}
    assert served == set(PUBLIC_MEDIA_PREFIXES)
