"""Accessibility fixes from the redesign review, pinned by what the page sends.

- Focus rings inside horizontally scrolling tracks (tabs, segments, filter pills and selects) are drawn
  just inside the item, because overflow-x:auto clips them otherwise.
- Toggles stay visible, and on stays apart from off, in Windows forced-colours mode.
- On phones a calendar chip hides its title from sight only, so the link keeps the post's name.
- Name fields in a column-then-row form grow only in the row layout (flex-1 in a column collapsed them
  to 22px tall).
- The analytics post drawer traps focus and returns it to its row.
- Approval rows that cannot be selected keep a checkbox-size spacer, so the columns line up.
- The inbox footer names LinkedIn correctly (no |title).
- Approval error toasts stay until dismissed; others pause while hovered or focused; all can be dismissed.
"""

from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.composer.models import PlatformPost, Post
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace

ROOT = Path(settings.BASE_DIR)


def _source(relative):
    return (ROOT / relative).read_text()


class StylesheetTests(TestCase):
    def test_focus_ring_is_drawn_inside_items_in_scrolling_tracks(self):
        css = _source("theme/static_src/src/styles.css")
        self.assertIn(
            ".ui-tab:focus-visible, .ui-segment:focus-visible, .ui-filter-chip:focus-visible,\n"
            "  .ml-filter-pill:focus-visible, .cal-filter-select:focus-visible { outline-offset: -2px; }",
            css,
        )

    def test_toggles_survive_forced_colours(self):
        css = _source("theme/static_src/src/styles.css")
        block = css[css.index("@media (forced-colors: active)") :]
        self.assertIn(".bb-toggle-track { border: 1px solid ButtonText; background: Canvas; }", block)
        self.assertIn(".bb-toggle input:checked + .bb-toggle-track { background: Highlight;", block)
        self.assertIn(".bb-toggle-track::after { background: ButtonText;", block)

    def test_analytics_drawer_traps_focus(self):
        html = _source("templates/analytics/index.html")
        drawer = html[html.index('<div class="a-drawer"') : html.index('id="drawer-host"')]
        self.assertIn('x-trap.noscroll="drawerOpen"', drawer)
        self.assertIn('role="dialog" aria-modal="true"', drawer)

    def test_inbox_footer_keeps_the_platform_name_as_written(self):
        html = _source("templates/inbox/partials/_reply_composer.html")
        line = next(line for line in html.splitlines() if "Posts on" in line)
        self.assertNotIn("|title", line)


class PageTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Org")
        self.ws = Workspace.objects.create(organization=self.org, name="WS")
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
        self.client.force_login(self.owner)
        self.kw = {"workspace_id": self.ws.id}

    def _post(self, status, caption):
        post = Post.objects.create(workspace=self.ws, author=self.owner, caption=caption)
        PlatformPost.objects.create(post=post, social_account=self.account, status=status)
        return post

    def test_phone_calendar_chips_keep_their_title_for_screen_readers(self):
        html = self.client.get(reverse("calendar:calendar", kwargs=self.kw)).content.decode()
        phone = html[html.index("@media (max-width: 639px)", html.index(".post-chip {")) :]
        phone = phone[: phone.index("\n    }")]
        self.assertIn(
            ".cal-day .post-chip > .truncate, .cal-day .post-chip > svg, .cal-day .cal-event .truncate {", phone
        )
        self.assertIn("clip: rect(0, 0, 0, 0)", phone)
        self.assertNotIn(".post-chip > .truncate, .cal-day .post-chip .chip-thumb", phone)

    def test_name_fields_grow_only_in_the_row_layout(self):
        pages = [
            reverse("workspaces:list"),
            reverse("workspaces:settings", kwargs=self.kw),
            reverse("organizations:settings"),
            reverse("accounts:settings"),
        ]
        for url in pages:
            response = self.client.get(url)
            if response.status_code != 200:
                continue
            html = response.content.decode()
            self.assertNotIn('class="ui-input flex-1"', html, url)
        self.assertIn('class="ui-input sm:flex-1"', self.client.get(reverse("workspaces:list")).content.decode())

    def test_unselectable_approval_rows_keep_the_checkbox_column(self):
        self._post(PlatformPost.Status.PENDING_REVIEW, "Waiting one")
        self._post(PlatformPost.Status.APPROVED, "Approved one")
        html = self.client.get(reverse("calendar:publish_tab_approvals", kwargs=self.kw)).content.decode()
        self.assertEqual(html.count('aria-label="Select post"'), 1)
        self.assertEqual(html.count("data-select-spacer"), 1)

    def test_approval_error_toasts_persist_and_every_toast_can_be_dismissed(self):
        html = self.client.get(reverse("calendar:calendar", kwargs=self.kw)).content.decode()
        script = html[html.index("window.__bbToastInit") :]
        script = script[: script.index("</script>")]
        self.assertNotIn("detail.duration || 3400", script)
        self.assertIn("var persists = detail.tone === 'error' || detail.tone === 'warn';", script)
        self.assertIn("if (detail.tone === 'error') el.setAttribute('role', 'alert');", script)
        self.assertIn('aria-label="Dismiss"', script)
        self.assertIn("el.addEventListener('mouseenter', pause);", script)
        self.assertIn("el.addEventListener('focusin', pause);", script)


class FormFieldTests(TestCase):
    """Fields built in Python use the design system's .ui-input (16px and 44px tall on phones, so
    iOS does not zoom; the edge-plus-halo focus; the select chevron) instead of text-sm utilities."""

    def test_blog_and_studio_fields_use_ui_input(self):
        from apps.blog.forms import BlogPostForm
        from apps.composer.forms import PlatformOverrideForm
        from apps.studio import forms as studio_forms

        self.assertEqual(studio_forms._FIELD, "ui-input")
        for name in ("title", "excerpt", "seo_title", "site", "focus_keyword"):
            classes = BlogPostForm._meta.widgets[name].attrs["class"].split()
            self.assertIn("ui-input", classes, name)
            self.assertNotIn("text-sm", classes, name)
        for name in ("platform_specific_caption", "platform_specific_first_comment"):
            self.assertEqual(PlatformOverrideForm.base_fields[name].widget.attrs["class"], "ui-input")


class PublishingPagesAlignTests(PageTests):
    """Drafts, Queues, Posting schedule, Templates, Categories and Import from CSV were centred while every
    other app page sits left, so the title jumped about 120px sideways when moving between them."""

    def test_publishing_sub_pages_sit_left_like_the_rest(self):
        names = [
            "composer:drafts_list",
            "calendar:queue_list",
            "calendar:posting_slots",
            "composer:template_list",
            "composer:category_list",
            "composer:csv_upload",
        ]
        for name in names:
            response = self.client.get(reverse(name, kwargs=self.kw))
            self.assertEqual(response.status_code, 200, name)
            html = response.content.decode()
            self.assertNotIn("max-w-[880px] mx-auto", html, name)
            self.assertIn("w-full max-w-[880px] min-w-0", html, name)
