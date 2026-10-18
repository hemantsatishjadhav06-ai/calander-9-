"""Invitation identity and configured password policy apply on every path."""

import io
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.signals import create_organization_on_signup
from apps.members.models import Invitation, OrgMembership
from apps.organizations.models import Organization


class SignupInvitationIdentityTests(TestCase):
    def test_signup_signal_cannot_join_using_another_addresses_invitation(self):
        org = Organization.objects.create(name="Private agency")
        invitation = Invitation.objects.create(
            organization=org, email="intended@example.com", expires_at=timezone.now() + timezone.timedelta(days=7)
        )
        user = User.objects.create_user(email="someone-else@example.com", password="original-password")
        request = RequestFactory().post("/accounts/signup/")
        request.session = {"pending_invite_token": invitation.token}
        create_organization_on_signup(sender=User, request=request, user=user)
        self.assertFalse(OrgMembership.objects.filter(user=user, organization=org).exists())
        invitation.refresh_from_db()
        self.assertIsNone(invitation.accepted_at)


@override_settings(
    AUTH_PASSWORD_VALIDATORS=[
        {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
        {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    ]
)
class AccountPasswordPolicyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="owner@example.com", password="original-password", tos_accepted_at=timezone.now()
        )
        self.client.force_login(self.user)

    def _change(self, password):
        return self.client.post(
            reverse("accounts:settings"),
            {
                "action": "update_password",
                "current_password": "original-password",
                "password": password,
                "password_confirm": password,
            },
        )

    def test_short_password_is_rejected_using_configured_minimum(self):
        self._change("eight888")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("original-password"))

    def test_numeric_password_is_rejected_using_configured_validator(self):
        self._change("1234567890123456")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("original-password"))

    def test_valid_password_changes_without_ending_current_session(self):
        self._change("long-new-password!")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("long-new-password!"))
        self.assertEqual(self.client.get(reverse("accounts:settings")).status_code, 200)


class ProfileUploadSafetyTests(TestCase):
    def setUp(self):
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        storage = override_settings(MEDIA_ROOT=media.name)
        storage.enable()
        self.addCleanup(storage.disable)
        self.user = User.objects.create_user(
            email="image-owner@example.com", password="original-password", tos_accepted_at=timezone.now()
        )
        self.workspace = self.user.workspace_memberships.get().workspace
        self.client.force_login(self.user)

    def _image_with_html_name(self):
        from PIL import Image

        data = io.BytesIO()
        Image.new("RGB", (180, 180), "red").save(data, "PNG")
        return SimpleUploadedFile("active.html", data.getvalue(), content_type="image/png")

    def test_workspace_logo_rejects_html_with_forged_image_content_type(self):
        forged = SimpleUploadedFile("active.html", b"<script>alert(document.cookie)</script>", content_type="image/png")
        response = self.client.post(
            reverse("workspaces:settings", kwargs={"workspace_id": self.workspace.id}), {"icon": forged}
        )
        self.assertEqual(response.status_code, 302)
        self.workspace.refresh_from_db()
        self.assertFalse(self.workspace.icon)

    def test_avatar_uses_verified_image_suffix(self):
        self.client.post(
            reverse("accounts:settings"), {"action": "update_photo", "avatar": self._image_with_html_name()}
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.avatar.name.endswith(".png"))
        self.assertNotIn("active.html", self.user.avatar.name)

    def test_workspace_logo_uses_verified_image_suffix(self):
        self.client.post(
            reverse("workspaces:settings", kwargs={"workspace_id": self.workspace.id}),
            {"icon": self._image_with_html_name()},
        )
        self.workspace.refresh_from_db()
        self.assertTrue(self.workspace.icon.name.endswith(".png"))

    def test_names_cannot_overflow_database_fields_or_inject_email_headers(self):
        response = self.client.post(reverse("accounts:settings"), {"action": "update_name", "name": "A" * 300})
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(len(self.user.name), 255)
        response = self.client.post(
            reverse("workspaces:settings", kwargs={"workspace_id": self.workspace.id}),
            {"name": "B" * 100 + "\r\nBcc: attacker@example.com"},
        )
        self.assertEqual(response.status_code, 302)
        self.workspace.refresh_from_db()
        self.assertEqual(self.workspace.name, "B" * 100)
