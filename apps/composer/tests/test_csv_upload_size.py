"""Tests for the CSV upload size cap (DoS guard)."""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.composer.views import MAX_CSV_UPLOAD_BYTES
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace


class CSVUploadSizeCapTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="owner@example.com",
            password="testpass123",
            tos_accepted_at=timezone.now(),
        )
        self.org = Organization.objects.create(name="Test Org")
        self.workspace = Workspace.objects.create(organization=self.org, name="Test Workspace")
        OrgMembership.objects.create(
            user=self.user,
            organization=self.org,
            org_role=OrgMembership.OrgRole.OWNER,
        )
        WorkspaceMembership.objects.create(
            user=self.user,
            workspace=self.workspace,
            workspace_role=WorkspaceMembership.WorkspaceRole.OWNER,
        )
        self.client.force_login(self.user)
        self.url = reverse("composer:csv_upload", kwargs={"workspace_id": self.workspace.id})

    def test_oversized_csv_rejected_without_reading(self):
        # 1 byte over the cap. Use ASCII bytes so the size matches `len`.
        oversized = b"a" * (MAX_CSV_UPLOAD_BYTES + 1)
        upload = SimpleUploadedFile("big.csv", oversized, content_type="text/csv")
        response = self.client.post(self.url, data={"csv_file": upload})
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertIn("too large", body)

    def test_under_cap_csv_proceeds_to_mapping(self):
        small_csv = b"date,platform,caption\n2026-05-01,instagram,Hello\n"
        upload = SimpleUploadedFile("small.csv", small_csv, content_type="text/csv")
        response = self.client.post(self.url, data={"csv_file": upload})
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertNotIn("too large", body)


class CSVPreviewTests(CSVUploadSizeCapTests):
    """QA round 1 BUG-16: Validate & Preview crashed (500) on every file."""

    def _upload(self, body: bytes):
        upload = SimpleUploadedFile("plan.csv", body, content_type="text/csv")
        self.client.post(self.url, data={"csv_file": upload})
        return self.client.post(
            reverse("composer:csv_preview", kwargs={"workspace_id": self.workspace.id}),
            data={"map_date": "0", "map_platforms": "1", "map_caption": "2"},
        )

    def test_clean_row_previews_without_crashing(self):
        response = self._upload(b"date,platform,caption\n2026-05-01,bluesky,Hello\n")
        self.assertEqual(response.status_code, 200)
        # Bluesky is a known platform, just not connected in this workspace.
        self.assertContains(response, "not connected")
        self.assertNotContains(response, "Unknown platform")

    def test_bad_rows_get_row_level_errors(self):
        response = self._upload(b"date,platform,caption\nnot-a-date,myspace,\n")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid date format")
        self.assertContains(response, "Unknown platform")
        self.assertContains(response, "Caption is empty")
