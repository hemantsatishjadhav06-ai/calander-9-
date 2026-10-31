"""The app shell's keyboard and screen-reader promises (review findings on the redesign).

- Below 1024px the closed sidebar drawer was only moved off-screen, so twelve invisible controls sat
  in the tab order before the menu button, and opening it left focus behind the overlay. Closed, it
  is now inert; open, it is a modal dialog that traps focus and hands it back on close.
- Opening New idea from the open phone drawer left the drawer's trap active behind the dialog, so it
  pulled focus back from the dialog's title. Opening New idea now closes the drawer first; the drawer
  hands focus back to the menu button itself (Escape, the backdrop, the button, a link) instead of
  through its trap, so that close cannot steal focus from the dialog.
- The workspace switcher and the New menu closed only on an outside click; Escape now closes them and
  returns focus to their button (and only stops the event while a menu is open, so Escape still
  closes the phone drawer).
- The sidebar "New > Idea" modal's borderless title and notes fields showed no focus indicator.
- The account button's second line dropped to 4.25:1 on hover (ink-500); it is ink-600.
- The page scroller clipped focus rings on anything flush with its edges; it has a 4px inner gutter.
- "More" labels were title case and did not match their pages.
"""

import re

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace


class ShellA11yTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Org")
        self.ws = Workspace.objects.create(organization=self.org, name="WS")
        self.owner = User.objects.create_user(
            email="owner@example.com", password="pw", name="Ana Owner", tos_accepted_at=timezone.now()
        )
        OrgMembership.objects.get_or_create(user=self.owner, organization=self.org, defaults={"org_role": "owner"})
        WorkspaceMembership.objects.get_or_create(
            user=self.owner, workspace=self.ws, defaults={"workspace_role": WorkspaceMembership.WorkspaceRole.OWNER}
        )
        self.client.force_login(self.owner)
        response = self.client.get(reverse("calendar:calendar", kwargs={"workspace_id": self.ws.id}))
        self.assertEqual(response.status_code, 200)
        self.html = response.content.decode()

    def _tag(self, marker):
        start = self.html.rindex("<", 0, self.html.index(marker))
        return self.html[start : self.html.index(">", self.html.index(marker))]

    def test_closed_drawer_is_inert_and_open_drawer_traps_focus(self):
        aside = self._tag('id="app-sidebar"')
        self.assertIn(':inert="!isDesktop && !mobileMenuOpen"', aside)
        self.assertIn('x-trap.noscroll.noreturn="!isDesktop && mobileMenuOpen"', aside)
        self.assertIn(":role=\"isDesktop ? null : 'dialog'\"", aside)
        self.assertIn(":aria-modal=\"(!isDesktop && mobileMenuOpen) ? 'true' : null\"", aside)
        self.assertIn("isDesktop: window.matchMedia('(min-width: 1024px)').matches", self.html)
        toggle = self._tag('aria-label="Toggle menu"')
        self.assertIn('aria-controls="app-sidebar"', toggle)

    def test_closing_the_drawer_hands_focus_back_to_the_menu_button(self):
        give_back = "$nextTick(() => $refs.menuToggle && $refs.menuToggle.focus())"
        toggle = self._tag('aria-label="Toggle menu"')
        self.assertIn('x-ref="menuToggle"', toggle)
        self.assertIn(
            '@click="mobileMenuOpen = !mobileMenuOpen; if (!mobileMenuOpen) $nextTick(() => $el.focus())"', self.html
        )
        self.assertIn(
            f'@keydown.escape.window="if (mobileMenuOpen) {{ mobileMenuOpen = false; {give_back} }}"', self.html
        )
        self.assertIn(f'@click="mobileMenuOpen = false; {give_back}"', self.html)
        self.assertIn(f"$event.target.closest('a')) {{ mobileMenuOpen = false; {give_back} }}", self.html)

    def test_new_idea_closes_the_phone_drawer_before_taking_focus(self):
        start = self.html.index("openCreateModal() {")
        body = self.html[start : self.html.index("closeCreateModal() {", start)]
        self.assertLess(body.index("this.mobileMenuOpen = false;"), body.index("this.showCreateModal = true;"))
        self.assertIn("this.$refs.sidebarIdeaTitle.focus()", body)

    def test_menus_close_on_escape_and_return_focus(self):
        self.assertIn(
            '@keydown.escape="if (wsOpen) { $event.stopPropagation(); wsOpen = false; $refs.wsBtn.focus() }"', self.html
        )
        self.assertIn('x-ref="wsBtn"', self.html)
        self.assertIn(
            '@keydown.escape="if (newMenuOpen) { $event.stopPropagation(); newMenuOpen = false; $refs.newBtn.focus() }"',
            self.html,
        )
        self.assertIn('x-ref="newBtn"', self.html)

    def test_idea_modal_fields_show_focus(self):
        rule = re.search(
            r"\.idea-modal-body input\.idea-title-input:focus-visible,\s*"
            r"\.idea-modal-body textarea\.idea-desc-input:focus-visible \{([^}]*)\}",
            self.html,
        )
        self.assertIsNotNone(rule)
        self.assertIn("box-shadow: 0 2px 0 0 var(--focus-ring)", rule.group(1))
        self.assertIn("outline: 2px solid transparent", rule.group(1))

    def test_account_button_second_line_keeps_contrast_on_hover(self):
        self.assertIn('<p class="text-xs text-ink-600 truncate">Ana Owner</p>', self.html)

    def test_scroller_leaves_room_for_focus_rings(self):
        self.assertIn(
            'class="relative flex-1 min-h-0 flex flex-col overflow-y-auto overflow-x-hidden -m-1 p-1"', self.html
        )

    def test_more_labels_are_sentence_case_and_match_their_pages(self):
        labels = re.findall(r'sidebar-nav-label">([^<]+)<', self.html)
        for label in ("Ideas", "Posting schedule", "Import from CSV"):
            self.assertIn(label, labels)
        for old in ("Create Idea", "Posting Schedule", "Import CSV"):
            self.assertNotIn(old, labels)
        self.assertIn('<h2 class="text-h2 text-ink-950">New idea</h2>', self.html)
        kw = {"workspace_id": self.ws.id}
        pages = {
            "Ideas": reverse("composer:create_landing", kwargs=kw),
            "Posting schedule": reverse("calendar:posting_slots", kwargs=kw),
            "Import from CSV": reverse("composer:csv_upload", kwargs=kw),
        }
        for label, url in pages.items():
            page = self.client.get(url).content.decode()
            self.assertIn(f'<h1 class="ui-page-title">{label}</h1>', page, label)
