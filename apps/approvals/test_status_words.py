"""One post, one set of words: status labels, honest headings and 24-hour times (redesign review).

- STATUS_META used "Pending review", "Pending client", "Partially published" and "Hold requested",
  while the Agency side and the design system's fixed list say "Ready for approval", "Waiting for
  client", "Partly published" and "On hold". The brief page printed the raw title-case model label.
- The client portal titled approved and on-hold posts "Approved and scheduled", and dated an approved
  post with the calendar icon although nothing was scheduled.
- Publishing pages showed "9:24 AM" where Agency and the toasts say "09:24".
"""

from datetime import UTC, datetime
from pathlib import Path

from django.conf import settings
from django.template import Context, Template
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.approvals.templatetags.approval_extras import STATUS_META
from apps.client_portal.models import MagicLinkToken
from apps.composer.models import PlatformPost, Post
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


class StatusWordTests(TestCase):
    def test_the_fixed_status_words(self):
        expected = {
            "pending_review": "Ready for approval",
            "pending_client": "Waiting for client",
            "partially_published": "Partly published",
            "on_hold": "On hold",
            "approved": "Approved",
            "scheduled": "Scheduled",
            "changes_requested": "Changes requested",
        }
        for status, word in expected.items():
            self.assertEqual(STATUS_META[status]["label"], word, status)
        for meta in STATUS_META.values():
            # Sentence case: only the first letter may be a capital.
            self.assertEqual(meta["label"], meta["label"][0] + meta["label"][1:].lower())

    def test_status_label_filter_and_badge_override(self):
        html = Template(
            "{% load approval_extras %}{{ 'pending_review'|status_label }}|{{ 'odd_value'|status_label }}|"
            "{% status_badge 'pending_client' label='Waiting for you' %}"
        ).render(Context())
        self.assertIn("Ready for approval|Odd value|", html)
        self.assertIn("Waiting for you", html)
        self.assertIn("ui-pill-warning", html)


class PageWordTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Org")
        self.ws = Workspace.objects.create(organization=self.org, name="WS", timezone="Asia/Kolkata")
        self.owner = User.objects.create_user(
            email="owner@example.com", password="pw", name="Owner", tos_accepted_at=timezone.now()
        )
        OrgMembership.objects.get_or_create(user=self.owner, organization=self.org, defaults={"org_role": "owner"})
        WorkspaceMembership.objects.get_or_create(
            user=self.owner, workspace=self.ws, defaults={"workspace_role": WorkspaceMembership.WorkspaceRole.OWNER}
        )
        self.account = SocialAccount.objects.create(
            workspace=self.ws,
            platform="linkedin_company",
            account_platform_id="li-1",
            account_name="Neopolis",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )
        self.kw = {"workspace_id": self.ws.id}

    def _post(self, status, caption, **fields):
        post = Post.objects.create(workspace=self.ws, author=self.owner, caption=caption, **fields)
        PlatformPost.objects.create(post=post, social_account=self.account, status=status)
        return post

    def test_approvals_tab_uses_the_fixed_words_and_24_hour_times(self):
        # 03:54 UTC is 09:24 in India.
        self._post(
            PlatformPost.Status.PENDING_REVIEW,
            "Same tower",
            proposed_publish_at=datetime(2026, 10, 26, 3, 54, tzinfo=UTC),
        )
        self.client.force_login(self.owner)
        html = self.client.get(reverse("calendar:publish_tab_approvals", kwargs=self.kw)).content.decode()
        self.assertIn("Ready for approval", html)
        self.assertIn("Waiting for client", html)
        self.assertNotIn("Pending review", html)
        self.assertNotIn("Hold requested", html)
        self.assertIn("Proposed Mon 26 Oct, 09:24", html)
        self.assertNotIn(" AM", html)

    def test_client_portal_says_decided_and_dates_only_what_is_scheduled(self):
        client_user = User.objects.create_user(
            email="client@example.com", password="pw", name="Client", tos_accepted_at=timezone.now()
        )
        WorkspaceMembership.objects.create(
            user=client_user, workspace=self.ws, workspace_role=WorkspaceMembership.WorkspaceRole.CLIENT
        )
        when = datetime(2026, 10, 26, 4, 40, tzinfo=UTC)
        self._post(PlatformPost.Status.APPROVED, "Approved only", scheduled_at=when)
        self._post(PlatformPost.Status.SCHEDULED, "Really scheduled", scheduled_at=when)
        self._post(PlatformPost.Status.PENDING_CLIENT, "Yours to check")
        token = MagicLinkToken.objects.create(user=client_user, workspace=self.ws)
        self.client.post(reverse("client_portal:magic_link_entry", kwargs={"token": token.token}))

        html = self.client.get(reverse("client_portal:approval_queue")).content.decode()

        self.assertIn(">Decided</h2>", html)
        self.assertNotIn("Approved and scheduled", html)
        self.assertIn("Waiting for you", html)
        scheduled = html[html.index("Really scheduled") - 3000 : html.index("Really scheduled")]
        # The really scheduled post carries the info "Scheduled" pill and its calendar date; the approved
        # one says its time is a proposal.
        self.assertIn("ui-pill-info", scheduled)
        self.assertIn("Proposed for Mon 26 Oct, 10:10", html)
        self.assertIn("Mon 26 Oct, 10:10", scheduled)

    def test_brief_page_channel_rows_use_the_status_pill(self):
        source = (Path(settings.BASE_DIR) / "templates/studio/detail.html").read_text()
        self.assertNotIn("{{ pp.get_status_display }}", source)
        self.assertIn("{% status_badge pp.status %}", source)

    def test_calendar_chip_uses_the_fixed_words(self):
        source = (Path(settings.BASE_DIR) / "templates/calendar/partials/_post_chip.html").read_text()
        self.assertNotIn("get_status_display", source)
        self.assertIn('<span class="sr-only">{{ pp.status|status_label }}:</span>', source)
