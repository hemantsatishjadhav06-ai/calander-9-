"""The ``templates`` and ``queues`` switches inside the Calendar and Approvals pages (spec D6, R6).

``templates`` off hides the tag filter of the Calendar's list and of the Approvals screen (they
share ``calendar/partials/_publish_filters.html``); the channel and timezone filters stay. With
``queues`` off the Calendar, its list Queue tab (every scheduled post, not the Queues feature),
the posting schedule and the Queues page itself all still answer, and an existing queue is listed.
"""

from __future__ import annotations

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.calendar.models import Queue
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.studio.models import AgencySettings
from apps.workspaces.models import Workspace

TAG_FILTER = 'data-testid="ui-select-activeTag"'
CHANNEL_FILTER = 'data-testid="ui-select-selectedChannels"'


class CalendarSwitchTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Org")
        self.ws = Workspace.objects.create(organization=self.org, name="WS")
        self.owner = User.objects.create_user(
            email="owner@example.com", password="pw", name="Owner", tos_accepted_at=timezone.now()
        )
        OrgMembership.objects.create(user=self.owner, organization=self.org, org_role="owner")
        WorkspaceMembership.objects.create(user=self.owner, workspace=self.ws, workspace_role="owner")
        self.account = SocialAccount.objects.create(
            workspace=self.ws,
            platform="linkedin_company",
            account_platform_id="li-1",
            account_name="Our page",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )
        self.kw = {"workspace_id": self.ws.id}
        self.client.force_login(self.owner)

    def switch(self, **features):
        AgencySettings.objects.update_or_create(workspace=self.ws, defaults={"features": features})

    def html(self, name, query=""):
        response = self.client.get(reverse(name, kwargs=self.kw) + query)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def list_pages(self):
        return {
            "calendar list": self.html("calendar:calendar", "?mode=list"),
            "approvals": self.html("approvals:index"),
        }

    def test_templates_off_the_tag_filter_is_hidden(self):
        for page, html in self.list_pages().items():
            with self.subTest(page=page):
                self.assertNotIn(TAG_FILTER, html)
                self.assertIn(CHANNEL_FILTER, html)

    def test_templates_on_the_tag_filter_is_back(self):
        self.switch(templates=True)

        for page, html in self.list_pages().items():
            with self.subTest(page=page):
                self.assertIn(TAG_FILTER, html)

    def test_queues_off_the_pages_still_answer_and_existing_queues_are_listed(self):
        self.switch(queues=False)
        Queue.objects.create(workspace=self.ws, social_account=self.account, name="Weekday mornings")

        self.assertIn('data-testid="publish-tab-queue"', self.html("calendar:calendar", "?mode=list"))
        self.html("calendar:posting_slots")
        self.assertIn("Weekday mornings", self.html("calendar:queue_list"))
