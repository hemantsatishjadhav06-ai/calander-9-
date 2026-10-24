"""The composer's layout promises: history beside the form, a hidden closed drawer, honest copy.

Review findings pinned here:
- The approval history and comments sat after </form> inside the same flex column and took their whole
  height out of the form, with no side padding. They are now a footer panel of their own (a
  disclosure with a status line, padded, scrolling inside its own box), outside #composer-form because
  they hold forms and hx-post buttons of their own.
- Below 1024px the closed preview drawer was only moved off-screen, so its Close button and the
  focusable preview region were invisible tab stops. Closed, it is now visibility:hidden.
- Disabled publish actions faded to translucent Pine; they now use the design's grey disabled style.
- "The time you picked is kept as a proposal" showed for Publish now and the queue actions, which send
  no time at all; only Schedule mentions a time, and only when the server says it kept it.
"""

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.approvals.models import ApprovalAction
from apps.composer.models import PlatformPost, Post
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


class ComposerLayoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="owner@example.com", password="testpass123", tos_accepted_at=timezone.now()
        )
        self.org = Organization.objects.create(name="Org")
        self.ws = Workspace.objects.create(organization=self.org, name="WS", timezone="Europe/Berlin")
        self.account = SocialAccount.objects.create(
            workspace=self.ws,
            platform="linkedin_personal",
            account_platform_id="li-1",
            account_name="Primary",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )
        OrgMembership.objects.create(user=self.user, organization=self.org, org_role=OrgMembership.OrgRole.OWNER)
        WorkspaceMembership.objects.create(
            user=self.user, workspace=self.ws, workspace_role=WorkspaceMembership.WorkspaceRole.OWNER
        )
        self.client.force_login(self.user)

    def _post(self, status, *, history=()):
        post = Post.objects.create(workspace=self.ws, author=self.user, caption="caption")
        PlatformPost.objects.create(post=post, social_account=self.account, status=status)
        for action, comment in history:
            ApprovalAction.objects.create(post=post, user=self.user, action=action, comment=comment)
        return post

    def _body(self, post):
        url = reverse("composer:compose_edit", kwargs={"workspace_id": self.ws.id, "post_id": post.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_history_is_a_padded_panel_outside_the_form(self):
        post = self._post(PlatformPost.Status.PENDING_REVIEW, history=[("submitted", "")])
        body = self._body(post)

        form_end = body.index("</form>", body.index('id="composer-form"'))
        panel = body.index('id="composer-approval-panel"')
        self.assertGreater(panel, form_end, "the history panel must sit outside #composer-form")
        panel_html = body[panel : body.index("</details>", panel)]
        self.assertIn("flex-shrink-0", body[panel - 200 : panel + 200])
        self.assertIn("px-4 sm:px-6", panel_html)
        self.assertIn("max-h-[40vh] overflow-y-auto", panel_html)
        self.assertIn("Awaiting internal review", panel_html)
        self.assertIn("Approval history", panel_html)
        self.assertIn('id="composer-comments"', panel_html)
        # Collapsed unless there is feedback to address.
        self.assertNotIn(
            'id="composer-approval-panel" class="group flex-shrink-0 border-t border-ink-200 bg-white" open', body
        )

    def test_feedback_to_address_opens_the_panel(self):
        post = self._post(
            PlatformPost.Status.CHANGES_REQUESTED,
            history=[("submitted", ""), ("changes_requested", "Use the new photo")],
        )
        body = self._body(post)
        self.assertIn(
            'id="composer-approval-panel" class="group flex-shrink-0 border-t border-ink-200 bg-white" open', body
        )
        self.assertIn("Use the new photo", body)

    def test_no_history_means_no_panel(self):
        body = self._body(self._post(PlatformPost.Status.DRAFT))
        self.assertNotIn('id="composer-approval-panel"', body)

    def test_closed_preview_drawer_is_hidden_from_the_keyboard(self):
        body = self._body(self._post(PlatformPost.Status.DRAFT))
        css = body[body.index(".panel-right  {") : body.index(".panel-right-backdrop")]
        self.assertIn("visibility: hidden;", css)
        self.assertIn(".panel-right.is-open { transform: translateX(0); visibility: visible;", css)
        # Desktop keeps the panel visible in the layout.
        self.assertIn("visibility: visible;\n            box-shadow: none;", css)

    def test_disabled_publish_actions_use_the_grey_disabled_style(self):
        body = self._body(self._post(PlatformPost.Status.DRAFT))
        start = body.index('id="publish-action-btn"')
        button = body[start : body.index(">", start)]
        self.assertNotIn("opacity-50", button)
        self.assertIn("disabled:bg-ink-100", button)
        self.assertIn("disabled:text-ink-500", button)
        self.assertIn("disabled:shadow-none", button)

    def test_only_schedule_mentions_a_picked_time(self):
        body = self._body(self._post(PlatformPost.Status.DRAFT))
        start = body.index("this.saveToastText = sentForReview")
        logic = body[start : start + 500]
        self.assertIn("review === 'proposal'", logic)
        self.assertIn("The time you picked is kept as a proposal", logic)
        self.assertIn("Sent for approval. Nothing goes out until someone approves it.", logic)

    def test_the_review_toast_follows_what_the_server_says_it_did(self):
        # Inferred from the channel statuses, it claimed a submission and a kept proposal after a
        # Schedule that did neither. save_post now says so in X-Sent-For-Review.
        body = self._body(self._post(PlatformPost.Status.DRAFT))
        start = body.index("onFormSaved(event) {")
        handler = body[start : body.index("\n        },\n", start)]
        self.assertIn("getResponseHeader('X-Sent-For-Review')", handler)
        self.assertNotIn("X-Platform-Statuses", handler)
        self.assertIn("review === 'not_sent'", handler)
        self.assertIn("Saved. Nothing was scheduled or sent for approval.", handler)

    def test_new_workspaces_get_sentence_case_idea_columns(self):
        from apps.composer.models import IdeaGroup

        self.client.get(reverse("composer:create_landing", kwargs={"workspace_id": self.ws.id}))
        names = list(IdeaGroup.objects.filter(workspace=self.ws).order_by("position").values_list("name", flat=True))
        self.assertEqual(names, ["Unassigned", "To do", "In progress", "Done"])

    def test_scroll_tracks_draw_focus_inside(self):
        body = self._body(self._post(PlatformPost.Status.DRAFT))
        start = body.index('id="preview-panel"')
        self.assertIn("focus-visible:outline-offset-[-2px]", body[start : body.index(">", start)])
