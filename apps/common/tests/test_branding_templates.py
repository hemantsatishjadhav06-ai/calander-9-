"""Branding guards for templates that render outside the request cycle.

Email templates go through ``render_to_string`` with no request, so the
``branding`` context processor never runs for them. Every brand string in an
email therefore has to be passed in explicitly by its sender, and a missed key
degrades silently: the template renders, the brand is simply blank. These tests
assert the brand actually reaches the output, and that the retired mascot
artwork has not come back.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.contrib.sites.models import Site
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

REPO_ROOT = Path(settings.BASE_DIR)

# The product shipped under a different name whose mascot artwork leaked into
# favicons, emails and auth pages. Nothing may reference it again.
RETIRED_BRAND = "brightbean"


class _FakeNotification:
    title = "Post approved"
    body = "Your post is live."
    data: dict = {}

    def __init__(self):
        self.created_at = timezone.now()


class EmailBrandingTests(TestCase):
    """Every email template must render the configured brand, not a blank."""

    def _assert_branded(self, template: str, context: dict) -> str:
        rendered = render_to_string(template, context)
        self.assertIn(
            settings.SITE_NAME,
            rendered,
            f"{template} rendered without the brand — its sender is missing a context key",
        )
        self.assertNotIn(RETIRED_BRAND, rendered.lower(), f"{template} references retired brand artwork")
        return rendered

    def test_notification_emails_carry_the_brand(self):
        context = {
            "notification": _FakeNotification(),
            "user": None,
            "app_url": "https://example.test",
            "SITE_NAME": settings.SITE_NAME,
            "workspace_name": "Acme",
        }
        self._assert_branded("notifications/email/notification.txt", context)
        self._assert_branded("notifications/email/notification.html", context)

    def test_digest_emails_carry_the_brand(self):
        context = {
            "heading": "3 updates",
            "notifications": [_FakeNotification()],
            "total": 3,
            "overflow": 0,
            "user": None,
            "date": timezone.now(),
            "app_url": "https://example.test",
            "SITE_NAME": settings.SITE_NAME,
        }
        self._assert_branded("notifications/email/digest.txt", context)
        self._assert_branded("notifications/email/digest.html", context)

    def test_invite_emails_carry_the_brand(self):
        context = {
            "invitation": None,
            "accept_url": "https://example.test/members/invite/abc/accept/",
            "org_name": "Acme",
            "invited_by": None,
            "app_url": "https://example.test",
            "SITE_NAME": settings.SITE_NAME,
        }
        self._assert_branded("members/email/invite.txt", context)
        self._assert_branded("members/email/invite.html", context)

    def test_allauth_confirmation_emails_use_the_site_name(self):
        """allauth renders these with ``current_site``, not our SITE_NAME key."""
        site = Site.objects.get_current()
        context = {
            "current_site": site,
            "user": None,
            "activate_url": "https://example.test/confirm/key/",
        }
        for template in (
            "account/email/email_confirmation_subject.txt",
            "account/email/email_confirmation_message.txt",
            "account/email/email_confirmation_signup_subject.txt",
            "account/email/email_confirmation_signup_message.txt",
        ):
            with self.subTest(template=template):
                rendered = render_to_string(template, context)
                self.assertIn(site.name, rendered)
                self.assertNotIn(RETIRED_BRAND, rendered.lower())


class RetiredBrandAssetTests(TestCase):
    """The mascot must not return — in a template, a static file or a page."""

    def test_no_template_references_the_retired_artwork(self):
        offenders = [
            str(path.relative_to(REPO_ROOT))
            for path in (REPO_ROOT / "templates").rglob("*")
            if path.is_file() and RETIRED_BRAND in path.read_text(errors="ignore").lower()
        ]
        self.assertEqual(offenders, [], f"templates still reference the retired brand: {offenders}")

    def test_no_retired_artwork_ships_in_static(self):
        offenders = [
            str(path.relative_to(REPO_ROOT))
            for path in (REPO_ROOT / "static").rglob("*")
            if path.is_file() and RETIRED_BRAND in path.name.lower()
        ]
        self.assertEqual(offenders, [], f"retired brand artwork still in static/: {offenders}")

    def test_auth_pages_render_the_brand_monogram(self):
        initial = settings.SITE_NAME[:1].upper()
        for url in (reverse("account_login"), reverse("account_signup")):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                body = response.content.decode()
                self.assertNotIn(RETIRED_BRAND, body.lower())
                self.assertIn(f">{initial}</div>", body)
