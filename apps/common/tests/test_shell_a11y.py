"""The app shell's keyboard and screen-reader promises (review findings on the redesign).

- Below 1024px the closed sidebar drawer was only moved off-screen, so twelve invisible controls sat
  in the tab order before the menu button, and opening it left focus behind the overlay. Closed, it
  is now inert; open, it is a modal dialog that traps focus and hands it back on close.
- Opening New idea from the open phone drawer left the drawer's trap active behind the dialog, so it
  pulled focus back from the dialog's title. The shell's New menu and its New idea dialog are gone
  (Phase 3 T19): the idea form lives in the New post sheet (Home and Calendar, for whoever may start
  posts), whose open() closes the drawer before it shows and then focuses the mode's first field (the
  idea's title for the idea form), however it is opened (the button, ``new-post:open``, ``#new-post``).
- The workspace switcher closed only on an outside click; Escape now closes it and returns focus to its
  button (and only stops the event while it is open, so Escape still closes the phone drawer). The New
  menu that did the same is gone; Escape closes the New post sheet and returns focus to its opener.
- The sidebar "New > Idea" modal's borderless title and notes fields showed no focus indicator. The
  sheet's idea fields are bordered ``ui-input`` fields whose focus rule shows a ring (and a system
  outline in forced-colours mode).
- The account button's second line dropped to 4.25:1 on hover (ink-500); it is ink-600.
- The page scroller clipped focus rings on anything flush with its edges; it has a 4px inner gutter.
- "More" labels were title case and did not match their pages. More is gone (plan T9), and so is the
  New menu that kept them (T19): the sheet's foot links and the Calendar page's header keep the labels.
"""

import re

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace

SHEET_SCRIPT = settings.BASE_DIR / "static" / "js" / "new-post-sheet.js"
STYLES = settings.BASE_DIR / "theme" / "static_src" / "src" / "styles.css"


def _between(text, start, end):
    at = text.index(start)
    return text[at : text.index(end, at)]


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
        self.script = SHEET_SCRIPT.read_text(encoding="utf-8")

    def _tag(self, marker, html=None):
        html = self.html if html is None else html
        start = html.rindex("<", 0, html.index(marker))
        return html[start : html.index(">", html.index(marker))]

    def _sheet(self):
        return self.html[self.html.index('data-testid="new-post-sheet"') :]

    def _approvals(self):
        """A page without the New post sheet (it is on Home and Calendar only)."""
        response = self.client.get(reverse("approvals:index", kwargs={"workspace_id": self.ws.id}))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertNotIn('data-testid="new-post-sheet"', html)
        return html

    def test_closed_drawer_is_inert_and_open_drawer_traps_focus(self):
        aside = self._tag('id="app-sidebar"')
        self.assertIn(':inert="!isDesktop && !mobileMenuOpen"', aside)
        self.assertIn('x-trap.noscroll="!isDesktop && mobileMenuOpen"', aside)
        self.assertIn(":role=\"isDesktop ? null : 'dialog'\"", aside)
        self.assertIn(":aria-modal=\"(!isDesktop && mobileMenuOpen) ? 'true' : null\"", aside)
        self.assertIn("isDesktop: window.matchMedia('(min-width: 1024px)').matches", self.html)
        toggle = self._tag('aria-label="Toggle menu"')
        self.assertIn('aria-controls="app-sidebar"', toggle)

    def test_the_sheet_closes_the_phone_drawer_before_it_opens_and_focuses_its_first_field(self):
        body = _between(self.script, "open: function (detail, source) {", "close: function () {")
        self.assertLess(body.index("this.mobileMenuOpen = false;"), body.index("this.sheetOpen = true;"))
        self.assertLess(body.index("this.sheetOpen = true;"), body.index("this.focusField(fromDrawer);"))
        # The first field of each mode: the idea for Ask the team, the idea's title for the idea form.
        self.assertIn("team: '[data-testid=\"new-post-team-idea\"]'", self.script)
        self.assertIn("idea: '[data-testid=\"idea-title\"]'", self.script)
        focus = _between(self.script, "focusField: function (afterDrawer) {", "_reclaimFocus: function")
        self.assertIn("root.querySelector(FIRST_FIELD[mode])", focus)
        self.assertIn("target.focus();", focus)
        # The sheet places the focus itself; its trap only keeps Tab inside.
        self.assertIn('x-trap.noscroll.noautofocus.noreturn="sheetOpen"', self._tag('data-testid="new-post-sheet"'))
        # Every way in (the button, a Calendar cell, #new-post) is new-post:open or the hash, through open().
        self.assertIn("window.addEventListener('new-post:open'", self.script)
        # The idea form is the sheet's alone: one title on the page, inside the sheet.
        self.assertEqual(self.html.count('data-testid="idea-title"'), 1)
        self.assertIn('data-testid="idea-title"', self._sheet())

    def test_no_page_keeps_the_shell_s_new_menu_or_its_new_idea_dialog(self):
        for html in (self.html, self._approvals()):
            for gone in ("sidebar-new-", "sidebarNewMenu", "openCreateModal", "newMenuOpen", 'x-ref="newBtn"'):
                self.assertNotIn(gone, html)
        self.assertNotIn('data-testid="idea-title"', self._approvals())

    def test_menus_close_on_escape_and_return_focus(self):
        self.assertIn(
            '@keydown.escape="if (wsOpen) { $event.stopPropagation(); wsOpen = false; $refs.wsBtn.focus() }"', self.html
        )
        self.assertIn('x-ref="wsBtn"', self.html)
        # The New post sheet: Escape closes it, and closing gives the focus back to whatever opened it.
        self.assertIn('@keydown.escape.prevent.stop="close()"', self._tag('data-testid="new-post-sheet"'))
        opening = _between(self.script, "open: function (detail, source) {", "close: function () {")
        self.assertIn("this.opener = element && element !== document.body ? element : null;", opening)
        closing = _between(self.script, "close: function () {", "setMode: function")
        self.assertIn("var opener = this.opener && document.contains(this.opener) ? this.opener", closing)
        self.assertIn("if (opener && typeof opener.focus === 'function') opener.focus();", closing)

    def test_the_sheet_s_idea_fields_show_focus(self):
        sheet = self._sheet()
        for hook in ("idea-title", "idea-description"):
            self.assertIn('class="ui-input"', self._tag(f'data-testid="{hook}"', sheet), hook)
        rule = re.search(r"\.ui-input:focus \{([^}]*)\}", STYLES.read_text(encoding="utf-8"))
        self.assertIsNotNone(rule)
        self.assertIn("box-shadow: 0 0 0 1px var(--focus-ring)", rule.group(1))
        self.assertIn("outline: 2px solid transparent", rule.group(1))

    def test_account_button_second_line_keeps_contrast_on_hover(self):
        self.assertIn('<p class="text-xs text-ink-600 truncate">Ana Owner</p>', self.html)

    def test_scroller_leaves_room_for_focus_rings(self):
        self.assertIn(
            'class="relative flex-1 min-h-0 flex flex-col overflow-y-auto overflow-x-hidden -m-2 p-2"', self.html
        )

    def _link_text(self, testid, html=None):
        html = self.html if html is None else html
        anchor = re.search(rf'data-testid="{testid}"[^>]*>(.*?)</a>', html, re.S)
        self.assertIsNotNone(anchor, testid)
        return re.sub(r"<[^>]+>", "", anchor.group(1)).strip()

    def test_more_labels_are_sentence_case_and_match_their_pages(self):
        moved = {
            "new-post-link-ideas": "Ideas",
            "new-post-link-drafts": "Drafts",
            "calendar-link-posting-schedule": "Posting schedule",
            "new-post-link-csv": "Import from CSV",
        }
        labels = [self._link_text(testid) for testid in moved]
        self.assertEqual(labels, list(moved.values()))
        # The old title-case labels are nowhere on the page (not only absent from these links);
        # HTML comments are markup notes nobody sees.
        page = re.sub(r"<!--.*?-->", "", self.html, flags=re.S)
        for old in ("Create Idea", "Posting Schedule", "Import CSV"):
            self.assertNotIn(old, page)
        # The idea form's heading is the sheet's title in its idea view; the shell's dialog heading is gone.
        self.assertIn("sheetMode === 'idea' ? 'New idea' : 'New post'", self._tag('id="new-post-title"'))
        for html in (self.html, self._approvals()):
            self.assertNotIn('<h2 class="text-h2 text-ink-950">New idea</h2>', html)
        kw = {"workspace_id": self.ws.id}
        pages = {
            "Ideas": reverse("composer:create_landing", kwargs=kw),
            "Posting schedule": reverse("calendar:posting_slots", kwargs=kw),
            "Import from CSV": reverse("composer:csv_upload", kwargs=kw),
        }
        for label, url in pages.items():
            page = self.client.get(url).content.decode()
            self.assertIn(f'<h1 class="ui-page-title">{label}</h1>', page, label)
        # Drafts goes to the Calendar's Drafts tab, which carries the same word.
        drafts = self.client.get(reverse("calendar:calendar", kwargs=kw) + "?mode=list&tab=drafts").content.decode()
        self.assertRegex(drafts, r'data-testid="publish-tab-drafts">\s*Drafts\b')
