"""Channel-less drafts are saved, visible and titled everywhere drafts are listed.

QA: Save Draft with no channel looked like it discarded the post — the Publish
Drafts tab and its badge only listed PlatformPost rows, so a Post with no
children never appeared there. An idea turned into a post kept its text only
in ``title``, which the composer hides for most platforms and the Drafts page
did not render. With no channels connected every Publish tab was replaced by
the same big "Welcome — connect a channel" block, so Drafts could not show
drafts. The sidebar also lit "Create Idea" on New Post and "Queues" on any
view whose name was a substring of "queue_list,queue_detail".
"""

import re

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.composer.models import Idea, PlatformPost, Post
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


class ChannellessDraftBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="owner@example.com", password="pw", name="Owner", tos_accepted_at=timezone.now()
        )
        self.org = Organization.objects.create(name="Org")
        self.ws = Workspace.objects.create(organization=self.org, name="WS")
        OrgMembership.objects.create(user=self.user, organization=self.org, org_role="owner")
        WorkspaceMembership.objects.create(
            user=self.user, workspace=self.ws, workspace_role=WorkspaceMembership.WorkspaceRole.OWNER
        )
        self.client.force_login(self.user)
        self.kw = {"workspace_id": self.ws.id}

    def _connect_account(self):
        return SocialAccount.objects.create(
            workspace=self.ws,
            platform="bluesky",
            account_platform_id="did",
            account_name="acct",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )


class SaveDraftResponseTests(ChannellessDraftBase):
    def test_htmx_save_draft_returns_the_edit_url_to_stay_on(self):
        response = self.client.post(
            reverse("composer:save_post", kwargs=self.kw),
            {"action": "save_draft", "caption": "Channel-less draft"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 204)
        post = Post.objects.get()
        self.assertEqual(
            response["X-Post-Edit-Url"],
            reverse("composer:compose_edit", kwargs={**self.kw, "post_id": post.id}),
        )
        self.assertIn("postSaved", response["HX-Trigger"])

    def test_composer_reads_the_action_from_the_request_not_the_publish_button(self):
        """The toast/redirect decision used #publish-action-btn's value, which is
        always the publish mode, so a successful Save Draft redirected away."""
        html = self.client.get(reverse("composer:compose", kwargs=self.kw)).content.decode()
        start = html.index("onFormSaved(event) {")
        body = html[start : start + 2500]
        self.assertNotIn("getElementById('publish-action-btn')", body)
        self.assertIn("requestConfig", body)
        self.assertIn("Draft saved", body)


class PublishDraftsTabTests(ChannellessDraftBase):
    def setUp(self):
        super().setUp()
        self.draft = Post.objects.create(
            workspace=self.ws, author=self.user, title="Idea headline", caption="", tags=["launch"]
        )

    def test_drafts_tab_lists_a_post_with_no_channel(self):
        response = self.client.get(reverse("calendar:publish_tab_drafts", kwargs=self.kw))
        self.assertContains(response, "Idea headline")
        self.assertContains(response, "No channel yet")
        self.assertContains(response, reverse("composer:compose_edit", kwargs={**self.kw, "post_id": self.draft.id}))
        self.assertEqual(response.context["drafts_count"], 1)

    def test_drafts_badge_counts_channelless_drafts_alongside_platform_drafts(self):
        account = self._connect_account()
        other = Post.objects.create(workspace=self.ws, author=self.user, caption="with channel")
        PlatformPost.objects.create(post=other, social_account=account, status=PlatformPost.Status.DRAFT)
        response = self.client.get(reverse("calendar:calendar", kwargs=self.kw) + "?mode=list&tab=drafts")
        self.assertEqual(response.context["drafts_count"], 2)
        self.assertContains(response, "Idea headline")
        self.assertContains(response, "with channel")

    def test_channel_filter_hides_channelless_drafts(self):
        account = self._connect_account()
        url = reverse("calendar:publish_tab_drafts", kwargs=self.kw) + f"?channel={account.id}"
        response = self.client.get(url)
        self.assertNotContains(response, "Idea headline")
        self.assertEqual(response.context["drafts_count"], 0)

    def test_tag_filter_applies_to_channelless_drafts(self):
        url = reverse("calendar:publish_tab_drafts", kwargs=self.kw)
        self.assertContains(self.client.get(url + "?tag=launch"), "Idea headline")
        self.assertNotContains(self.client.get(url + "?tag=other"), "Idea headline")

    def test_a_post_with_a_non_draft_child_is_not_a_channelless_draft(self):
        account = self._connect_account()
        PlatformPost.objects.create(post=self.draft, social_account=account, status=PlatformPost.Status.SCHEDULED)
        response = self.client.get(reverse("calendar:publish_tab_drafts", kwargs=self.kw))
        self.assertNotContains(response, "No channel yet")


class NoChannelsBannerTests(ChannellessDraftBase):
    def test_banner_shows_once_and_drafts_tab_keeps_its_drafts(self):
        Post.objects.create(workspace=self.ws, author=self.user, caption="Draft kept visible")
        response = self.client.get(reverse("calendar:calendar", kwargs=self.kw) + "?mode=list&tab=drafts")
        html = response.content.decode()
        self.assertEqual(html.count("No channels connected yet"), 1)
        self.assertNotIn("Welcome &#x1F44B;", html)
        self.assertIn("Draft kept visible", html)
        self.assertIn(reverse("social_accounts:connect", kwargs=self.kw), html)

    def test_tabs_keep_their_own_empty_states(self):
        for name, text in (
            ("publish_tab_queue", "No queued posts"),
            ("publish_tab_drafts", "No drafts"),
            ("publish_tab_sent", "No sent posts yet"),
        ):
            with self.subTest(tab=name):
                response = self.client.get(reverse(f"calendar:{name}", kwargs=self.kw))
                self.assertContains(response, text)
                self.assertNotContains(response, "Welcome &#x1F44B;")

    def test_no_banner_when_a_channel_is_connected(self):
        self._connect_account()
        response = self.client.get(reverse("calendar:calendar", kwargs=self.kw) + "?mode=list")
        self.assertNotContains(response, "No channels connected yet")


class DraftTitleTests(ChannellessDraftBase):
    def test_drafts_page_shows_the_title_of_a_caption_less_draft(self):
        Post.objects.create(workspace=self.ws, author=self.user, title="Only a title", caption="")
        response = self.client.get(reverse("composer:drafts_list", kwargs=self.kw))
        self.assertContains(response, "Only a title")
        self.assertNotContains(response, "(No caption)")

    def test_idea_create_post_seeds_an_empty_caption_with_the_title(self):
        idea = Idea.objects.create(workspace=self.ws, author=self.user, title="Idea title", description="")
        url = reverse("composer:idea_create_post", kwargs={**self.kw, "idea_id": idea.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        post = Post.objects.get(id=response.json()["post_id"])
        self.assertEqual(post.title, "Idea title")
        self.assertEqual(post.caption, "Idea title")
        # With no channel connected it is still listed as a draft.
        drafts = self.client.get(reverse("calendar:publish_tab_drafts", kwargs=self.kw))
        self.assertContains(drafts, "Idea title")

    def test_idea_create_post_keeps_the_description_as_caption(self):
        idea = Idea.objects.create(workspace=self.ws, author=self.user, title="T", description="Body text")
        url = reverse("composer:idea_create_post", kwargs={**self.kw, "idea_id": idea.id})
        post = Post.objects.get(id=self.client.post(url).json()["post_id"])
        self.assertEqual(post.caption, "Body text")


class SidebarActiveStateTests(ChannellessDraftBase):
    def _active_labels(self, response):
        html = response.content.decode()
        return re.findall(r'sidebar-nav-item active".*?sidebar-nav-label">([^<]+)<', html, re.S)

    def test_new_post_does_not_light_create_idea(self):
        response = self.client.get(reverse("composer:compose", kwargs=self.kw))
        self.assertNotIn("Create Idea", self._active_labels(response))

    def test_queues_only_lights_on_queue_views(self):
        # "list" is a substring of "queue_list,queue_detail" — the old ``in`` test lit Queues here.
        channels = self.client.get(reverse("social_accounts:list", kwargs=self.kw))
        self.assertEqual(channels.resolver_match.url_name, "list")
        self.assertNotIn("Queues", self._active_labels(channels))
        self.assertIn("Queues", self._active_labels(self.client.get(reverse("calendar:queue_list", kwargs=self.kw))))
