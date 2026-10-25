"""The composer's channel pills are toggle buttons.

Golden path 4 (select LinkedIn and Instagram) found that each pill was a ``<label>`` with a click
handler and no control inside it: no tab stop, nothing Enter or Space could press, and no selected
state for a screen reader (WCAG 2.1.1 and 4.1.2). Each pill is now a ``<button type="button">`` whose
``aria-pressed`` follows the selection, holding only phrasing content, so it looks as it did.
"""

from html.parser import HTMLParser

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _Element(HTMLParser):
    """The first element with the given data-testid: its tag, its attributes and the tags inside it."""

    def __init__(self, testid: str) -> None:
        super().__init__()
        self.testid = testid
        self.tag: str | None = None
        self.attrs: dict[str, str | None] = {}
        self.inside: list[str] = []
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        if self.tag is None:
            found = dict(attrs)
            if found.get("data-testid") == self.testid:
                self.tag, self.attrs, self._depth = tag, found, 1
            return
        if self._depth:
            self.inside.append(tag)
            if tag not in _VOID:
                self._depth += 1

    def handle_startendtag(self, tag, attrs):
        if self._depth:
            self.inside.append(tag)

    def handle_endtag(self, tag):
        if self._depth and tag not in _VOID:
            self._depth -= 1


class ChannelPillTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="owner@example.com", password="testpass123", tos_accepted_at=timezone.now()
        )
        self.org = Organization.objects.create(name="Org")
        self.ws = Workspace.objects.create(organization=self.org, name="WS", timezone="Asia/Kolkata")
        self.account = SocialAccount.objects.create(
            workspace=self.ws,
            platform="linkedin_company",
            account_platform_id="li-company-1",
            account_name="Neopolis",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )
        OrgMembership.objects.create(user=self.user, organization=self.org, org_role=OrgMembership.OrgRole.OWNER)
        WorkspaceMembership.objects.create(
            user=self.user, workspace=self.ws, workspace_role=WorkspaceMembership.WorkspaceRole.OWNER
        )
        self.client.force_login(self.user)

    def _pill(self) -> _Element:
        response = self.client.get(reverse("composer:compose", kwargs={"workspace_id": self.ws.id}))
        self.assertEqual(response.status_code, 200)
        pill = _Element(f"compose-account-{self.account.id}")
        pill.feed(response.content.decode())
        self.assertIsNotNone(pill.tag, "the composer renders a pill for the connected account")
        return pill

    def test_each_pill_is_a_toggle_button_with_its_state(self):
        pill = self._pill()

        self.assertEqual(pill.tag, "button", "a pill must be a control a keyboard can reach and press")
        self.assertEqual(pill.attrs.get("type"), "button", "a pill inside the form must not submit it")
        pressed = pill.attrs.get(":aria-pressed") or ""
        self.assertIn(f"selectedAccounts.includes('{self.account.id}')", pressed, "aria-pressed follows the selection")
        self.assertIn(f"toggleAccount('{self.account.id}')", pill.attrs.get("@click") or "")
        self.assertIn("acct-pill", pill.attrs.get("class") or "")

    def test_a_pill_holds_only_phrasing_content(self):
        pill = self._pill()

        blocks = sorted({tag for tag in pill.inside if tag in {"div", "p", "label", "button", "a", "input"}})
        self.assertEqual(blocks, [], "a button may hold phrasing content only")
        self.assertIn("span", pill.inside)
