"""The ``templates`` and ``queues`` switches inside the composer and the Ideas page (spec D6, R6).

``templates`` off hides the way into Templates (Use template, Save as template, the Ideas page's
Templates tab) and the Tags controls (the composer's tag picker, the Ideas page's tag filter and
the idea modals' tag pickers). A post keeps the tags it has: the composer carries them in a hidden
field, so a save never wipes them. CSV import, the Templates and Categories pages themselves, and
the composer's Category select (shown only when the workspace has categories) stay as they are.

``queues`` off hides Prioritise ("goes to the top of the queue"); Next available, the composer's
default, stays because it only means the next free slot of the posting schedule.

Every page still answers with the switches off.
"""

from __future__ import annotations

import re

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.composer.models import Post
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.studio.models import AgencySettings
from apps.workspaces.models import Workspace


class SwitchBase(TestCase):
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
            oauth_access_token="token",
        )
        self.post = Post.objects.create(
            workspace=self.ws, author=self.owner, caption="Hello", tags=["launch", "festive"]
        )
        self.kw = {"workspace_id": self.ws.id}
        self.client.force_login(self.owner)

    def switch(self, **features):
        AgencySettings.objects.update_or_create(workspace=self.ws, defaults={"features": features})

    def html(self, name, query="", **kwargs):
        response = self.client.get(reverse(name, kwargs={**self.kw, **kwargs}) + query)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def compose(self):
        return self.html("composer:compose")

    def compose_edit(self):
        return self.html("composer:compose_edit", post_id=self.post.id)


class ComposerTemplatesSwitchTests(SwitchBase):
    def test_off_the_composer_has_no_way_into_templates(self):
        picker = reverse("composer:template_picker", kwargs=self.kw)
        save_as = reverse("composer:save_as_template", kwargs={**self.kw, "post_id": self.post.id})

        self.assertNotIn(picker, self.compose())
        edit = self.compose_edit()
        self.assertNotIn(picker, edit)
        self.assertNotIn(save_as, edit)
        self.assertNotIn("Use template", edit)
        self.assertNotIn("Save as template", edit)

    def test_on_the_composer_offers_templates(self):
        self.switch(templates=True)
        picker = reverse("composer:template_picker", kwargs=self.kw)
        save_as = reverse("composer:save_as_template", kwargs={**self.kw, "post_id": self.post.id})

        self.assertIn(picker, self.compose())
        edit = self.compose_edit()
        self.assertIn(save_as, edit)
        self.assertIn("Use template", edit)

    # The composer's own tag picker; the sidebar's quick idea (templates/base.html) is not this page's.
    TAG_PICKER = ("Search or create a tag", "Choose tags…", 'id="compose-create-tag-title"')

    def test_off_the_tag_picker_is_hidden_and_the_post_keeps_its_tags(self):
        edit = self.compose_edit()

        for marker in self.TAG_PICKER:
            self.assertNotIn(marker, edit)
        self.assertIn('<input type="hidden" name="tags" value="launch,festive">', edit)

    def test_off_saving_what_the_composer_carries_keeps_the_tags(self):
        # The autosave posts the whole form; with the picker hidden, the hidden field is what it sends.
        match = re.search(r'<input type="hidden" name="tags" value="([^"]*)">', self.compose_edit())
        assert match is not None

        response = self.client.post(
            reverse("composer:autosave_edit", kwargs={**self.kw, "post_id": self.post.id}),
            {"caption": "Hello again", "tags": match.group(1)},
        )

        self.assertEqual(response.status_code, 200)
        self.post.refresh_from_db()
        self.assertEqual(self.post.caption, "Hello again")
        self.assertEqual(self.post.tags, ["launch", "festive"])

    def test_on_the_tag_picker_is_back(self):
        self.switch(templates=True)

        edit = self.compose_edit()

        for marker in self.TAG_PICKER:
            self.assertIn(marker, edit)
        self.assertNotIn('<input type="hidden" name="tags" value=', edit)


class ComposerQueuesSwitchTests(SwitchBase):
    def test_off_next_available_stays_and_prioritise_is_hidden(self):
        html = self.compose()

        self.assertIn('data-mode="add_to_queue"', html)
        self.assertIn("Next available", html)
        self.assertNotIn('data-mode="add_to_queue_priority"', html)
        self.assertNotIn("Goes to the top of the queue", html)

    def test_on_prioritise_is_back(self):
        self.switch(queues=True)

        html = self.compose()

        self.assertIn('data-mode="add_to_queue"', html)
        self.assertIn('data-mode="add_to_queue_priority"', html)


class IdeasPageTemplatesSwitchTests(SwitchBase):
    TAG_CONTROLS = (
        'placeholder="Search tags…"',  # the Ideas page's tag filter
        'x-ref="createTagSearchInput"',  # the New idea modal's tag picker
        'x-ref="editTagSearchInput"',  # the Edit idea modal's tag picker
    )

    def test_off_the_templates_tab_and_the_tag_controls_are_hidden(self):
        html = self.html("composer:create_landing")

        self.assertNotIn("activeTab = 'templates'", html)
        self.assertNotIn("Featured templates", html)
        for control in self.TAG_CONTROLS:
            self.assertNotIn(control, html)
        self.assertIn("activeTab = 'ideas'", html)

    def test_off_a_link_to_the_templates_tab_opens_ideas(self):
        response = self.client.get(reverse("composer:create_landing", kwargs=self.kw) + "?tab=templates")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["tab"], "ideas")

    def test_on_the_templates_tab_and_the_tag_controls_are_back(self):
        self.switch(templates=True)

        html = self.html("composer:create_landing")
        response = self.client.get(reverse("composer:create_landing", kwargs=self.kw) + "?tab=templates")

        self.assertIn("activeTab = 'templates'", html)
        self.assertIn("Featured templates", html)
        for control in self.TAG_CONTROLS:
            self.assertIn(control, html)
        self.assertEqual(response.context["tab"], "templates")


class PagesStillAnswerTests(SwitchBase):
    """Hidden, not removed: with every switch off each page answers, and CSV import stays."""

    def test_the_pages_answer_with_the_switches_off(self):
        self.switch(templates=False, queues=False)
        for name in (
            "composer:template_list",
            "composer:category_list",
            "composer:csv_upload",
            "calendar:queue_list",
            "calendar:posting_slots",
        ):
            with self.subTest(name=name):
                self.html(name)
