"""The rest of the audit's yellow list, each pinned by the thing a user sees.

- The sidebar only advertises platforms that can actually be connected.
- Six real pages (Drafts, Queues, Posting Schedule, Templates, Categories,
  CSV import) are reachable by clicking.
- The calendar's repeat-icon lookup no longer costs one query per chip.
- Logging out is a POST: a GET must not end the session.
- An external client does not get the org roster.
- The "Settings management coming soon" page is gone.
"""

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.calendar.models import RecurrenceRule
from apps.composer.models import PlatformPost, Post
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace

WR = WorkspaceMembership.WorkspaceRole


def _user(email):
    user = User.objects.create_user(
        email=email, password="pw", name=email.split("@")[0], tos_accepted_at=timezone.now()
    )
    auto_org_ids = list(OrgMembership.objects.filter(user=user).values_list("organization_id", flat=True))
    WorkspaceMembership.objects.filter(user=user).delete()
    OrgMembership.objects.filter(user=user).delete()
    Organization.objects.filter(id__in=auto_org_ids).delete()
    return user


class WorkspaceBase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Org")
        self.ws = Workspace.objects.create(organization=self.org, name="WS")
        self.owner = _user("owner@example.com")
        OrgMembership.objects.create(user=self.owner, organization=self.org, org_role="owner")
        WorkspaceMembership.objects.create(user=self.owner, workspace=self.ws, workspace_role=WR.OWNER)
        self.calendar_url = reverse("calendar:calendar", kwargs={"workspace_id": self.ws.id})


class SidebarTests(WorkspaceBase):
    def test_only_connectable_platforms_are_advertised(self):
        """No credentials configured in tests: the app-review platforms must not appear."""
        self.client.force_login(self.owner)
        response = self.client.get(self.calendar_url)
        self.assertEqual(response.status_code, 200)
        offered = {key for key, _label in response.context["sidebar_connectable_platforms"]}
        # Session / instance-OAuth platforms need no app credentials.
        self.assertIn("bluesky", offered)
        self.assertIn("mastodon", offered)
        for needs_app in ("instagram", "tiktok", "linkedin_company"):
            self.assertNotIn(needs_app, offered, f"{needs_app} is advertised but cannot be connected")

    def test_the_six_orphaned_pages_are_linked(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.calendar_url)
        kwargs = {"workspace_id": self.ws.id}
        for name in (
            "composer:drafts_list",
            "calendar:queue_list",
            "calendar:posting_slots",
            "composer:template_list",
            "composer:category_list",
            "composer:csv_upload",
        ):
            with self.subTest(name=name):
                self.assertContains(response, reverse(name, kwargs=kwargs))


class CalendarRecurrenceQueryTests(WorkspaceBase):
    def test_repeat_icon_lookup_is_joined_not_per_chip(self):
        account = SocialAccount.objects.create(
            workspace=self.ws,
            platform="bluesky",
            account_platform_id="did",
            account_name="a",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )
        now = timezone.now()
        for i in range(12):
            post = Post.objects.create(workspace=self.ws, author=self.owner, caption=f"p{i}", scheduled_at=now)
            PlatformPost.objects.create(
                post=post, social_account=account, status=PlatformPost.Status.SCHEDULED, scheduled_at=now
            )
            if i % 3 == 0:
                RecurrenceRule.objects.create(post=post, frequency=RecurrenceRule.Frequency.WEEKLY)

        self.client.force_login(self.owner)
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(self.calendar_url, {"mode": "calendar", "view": "month"})
        self.assertEqual(response.status_code, 200)

        standalone = [q["sql"] for q in ctx.captured_queries if 'FROM "calendar_recurrence_rule"' in q["sql"]]
        self.assertEqual(standalone, [], f"recurrence_rule fetched per chip: {len(standalone)} queries")


class LogoutIsAPostTests(WorkspaceBase):
    def test_a_get_does_not_end_the_session(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("accounts:logout"))
        self.assertEqual(response.status_code, 405)
        # Still signed in.
        self.assertEqual(self.client.get(self.calendar_url).status_code, 200)

    def test_a_post_does(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("accounts:logout"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get(self.calendar_url).status_code, 302)


class ClientRosterTests(WorkspaceBase):
    def _org_member_with_role(self, email, role):
        user = _user(email)
        OrgMembership.objects.create(user=user, organization=self.org, org_role="member")
        WorkspaceMembership.objects.create(user=user, workspace=self.ws, workspace_role=role)
        return user

    def test_an_external_client_gets_no_roster(self):
        client_user = self._org_member_with_role("client@example.com", WR.CLIENT)
        self.client.force_login(client_user)
        response = self.client.get(reverse("members:list"))
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, "owner@example.com", status_code=403)

    def test_a_contributor_still_sees_the_team(self):
        contributor = self._org_member_with_role("contrib@example.com", WR.CONTRIBUTOR)
        self.client.force_login(contributor)
        response = self.client.get(reverse("members:list"))
        self.assertEqual(response.status_code, 200)


class SettingsPlaceholderTests(WorkspaceBase):
    def test_the_coming_soon_page_is_gone(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get("/settings/").status_code, 404)
