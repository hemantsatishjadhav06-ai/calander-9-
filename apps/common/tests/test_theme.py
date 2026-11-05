"""Appearance and the head script (Phase 3, T5; docs/specs/phase-3.md, spec D2).

- The head script (``templates/components/theme_script.html``) runs before the first paint: it sits
  in ``<head>``, before ``<body>``, inside a ``<script>`` that carries the response's CSP nonce, in
  ``base.html`` and in the client portal's base alike, word for word the same.
- The account menu offers *Appearance*: a group named by its legend with three labelled radios,
  System, Light and Dark (``account-appearance-<choice>``), that hand the choice to ``bbTheme``.
- A page not declared dark-ready (``screens.DARK_READY``) says so under the choice ("This page stays
  light for now."); a declared page does not.

How the script resolves the theme is tested in Node (``tests/js/theme_resolve.test.cjs``); that the
browser repaints, follows the device and keeps undeclared pages light, in
``tests/e2e/self/theme.spec.ts``. ``test_csp_headers.py`` stays unchanged and green beside this file.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.client_portal.models import MagicLinkToken
from apps.common import screens
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "templates" / "components" / "theme_script.html"
ACCOUNT = ("accounts", "settings")
NOTE = "This page stays light for now."
CHOICES = ("system", "light", "dark")


class _Page(HTMLParser):
    """The parts of a rendered page these tests read: inline scripts, the body's start, fieldsets."""

    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.html = html
        self.scripts: list[dict] = []  # {"attrs", "text", "offset"}
        self.body_offset: int | None = None
        self.head_offset: int | None = None
        self.fieldsets: list[dict] = []  # {"legend", "radios": [{"attrs", "label"}], "text"}
        self._script: dict | None = None
        self._fieldset: dict | None = None
        self._in_legend = False
        self._label: dict | None = None
        self.feed(html)

    def _offset(self) -> int:
        line, column = self.getpos()
        lines = self.html.split("\n")
        return sum(len(text) + 1 for text in lines[: line - 1]) + column

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "head" and self.head_offset is None:
            self.head_offset = self._offset()
        if tag == "body" and self.body_offset is None:
            self.body_offset = self._offset()
        if tag == "script":
            self._script = {"attrs": a, "text": "", "offset": self._offset()}
        if tag == "fieldset":
            self._fieldset = {"legend": "", "radios": [], "text": ""}
        if self._fieldset is not None:
            if tag == "legend":
                self._in_legend = True
            if tag == "label":
                self._label = {"text": "", "radios": []}
            if tag == "input" and a.get("type") == "radio":
                radio = {"attrs": a, "label": None}
                self._fieldset["radios"].append(radio)
                if self._label is not None:
                    self._label["radios"].append(radio)

    def handle_endtag(self, tag):
        if tag == "script" and self._script is not None:
            self.scripts.append(self._script)
            self._script = None
        if self._fieldset is not None:
            if tag == "legend":
                self._in_legend = False
            if tag == "label" and self._label is not None:
                for radio in self._label["radios"]:
                    radio["label"] = " ".join(self._label["text"].split())
                self._label = None
            if tag == "fieldset":
                self.fieldsets.append(self._fieldset)
                self._fieldset = None

    def handle_data(self, data):
        if self._script is not None:
            self._script["text"] += data
        if self._fieldset is not None:
            self._fieldset["text"] += data
            if self._in_legend:
                self._fieldset["legend"] += data
            if self._label is not None:
                self._label["text"] += data


def _person(email: str) -> User:
    """A user with no organisation of their own (sign-up may make one)."""
    user = User.objects.create_user(email=email, password="pw", name="P", tos_accepted_at=timezone.now())
    own = list(OrgMembership.objects.filter(user=user).values_list("organization_id", flat=True))
    WorkspaceMembership.objects.filter(user=user).delete()
    OrgMembership.objects.filter(user=user).delete()
    Organization.objects.filter(id__in=own).delete()
    return user


@pytest.fixture
def team(db):
    org = Organization.objects.create(name="Org")
    ws = Workspace.objects.create(organization=org, name="WS")
    owner = _person("owner@example.com")
    OrgMembership.objects.create(user=owner, organization=org, org_role="owner")
    WorkspaceMembership.objects.create(user=owner, workspace=ws, workspace_role="owner")
    client_user = _person("client@example.com")
    OrgMembership.objects.create(user=client_user, organization=org, org_role="member")
    WorkspaceMembership.objects.create(user=client_user, workspace=ws, workspace_role="client")
    return SimpleNamespace(org=org, ws=ws, owner=owner, client=client_user)


def _nonce(response) -> str:
    policy = response["Content-Security-Policy"]
    match = re.search(r"'nonce-([^']+)'", policy)
    assert match, policy
    return match.group(1)


def _theme_script(page: _Page) -> dict:
    found = [script for script in page.scripts if "window.bbTheme" in script["text"]]
    assert len(found) == 1, [script["text"][:80] for script in page.scripts]
    return found[0]


def _account_page(client, team):
    client.force_login(team.owner)
    response = client.get(reverse("accounts:settings"))
    assert response.status_code == 200
    return response


def _portal_page(client, team):
    token = MagicLinkToken.objects.create(user=team.client, workspace=team.ws)
    entry = client.post(reverse("client_portal:magic_link_entry", kwargs={"token": token.token}))
    assert entry.status_code == 302
    response = client.get(reverse("client_portal:dashboard"))
    assert response.status_code == 200
    return response


def _appearance(page: _Page) -> dict:
    groups = [fieldset for fieldset in page.fieldsets if " ".join(fieldset["legend"].split()) == "Appearance"]
    assert len(groups) == 1, [fieldset["legend"] for fieldset in page.fieldsets]
    return groups[0]


# ─────────────────────────────── The head script ───────────────────────────────


def test_the_head_script_is_plain_javascript():
    """The partial is pasted inside a nonce'd <script>; a template tag in it would print, not run."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "window.bbTheme" in text
    assert "{%" not in text and "{{" not in text and "{#" not in text
    assert "<script" not in text.lower() and "</script" not in text.lower()


@pytest.mark.django_db
@override_settings(CSP_REPORT_ONLY=False)
@pytest.mark.parametrize("which", ["base", "portal"])
def test_the_head_script_carries_the_nonce_and_precedes_the_body(client, team, which):
    response = _account_page(client, team) if which == "base" else _portal_page(client, team)
    page = _Page(response.content.decode())
    script = _theme_script(page)

    assert script["attrs"].get("nonce") == _nonce(response)
    assert "src" not in script["attrs"]
    assert page.head_offset is not None and page.body_offset is not None
    assert page.head_offset < script["offset"] < page.body_offset
    # Word for word the partial: both bases run the same script.
    assert SCRIPT.read_text(encoding="utf-8").strip() in script["text"]


# ─────────────────────────────── The account menu's Appearance ───────────────────────────────


@pytest.mark.django_db
def test_the_account_menu_has_three_labelled_appearance_radios(client, team):
    page = _Page(_account_page(client, team).content.decode())
    group = _appearance(page)

    radios = group["radios"]
    assert [radio["attrs"].get("value") for radio in radios] == list(CHOICES)
    assert {radio["attrs"].get("name") for radio in radios} == {"appearance"}
    assert [radio["attrs"].get("data-testid") for radio in radios] == [f"account-appearance-{c}" for c in CHOICES]
    assert [radio["label"] for radio in radios] == ["System", "Light", "Dark"]
    for radio in radios:
        # The choice goes to the head script, which keeps it on this device and repaints.
        assert "bbTheme.set(" in radio["attrs"].get("@change", ""), radio["attrs"]


@pytest.mark.django_db
def test_an_undeclared_page_says_it_stays_light(client, team, monkeypatch):
    monkeypatch.setattr(screens, "DARK_READY", frozenset())
    group = _appearance(_Page(_account_page(client, team).content.decode()))
    assert NOTE in " ".join(group["text"].split())


@pytest.mark.django_db
def test_the_stays_light_note_is_read_with_the_group(client, team, monkeypatch):
    # A screen reader moving through the radios hears the note: the group points at it.
    monkeypatch.setattr(screens, "DARK_READY", frozenset())
    html = _account_page(client, team).content.decode()
    group = re.search(r'<fieldset[^>]*\baria-describedby="([^"]+)"[^>]*>\s*<legend[^>]*>Appearance</legend>', html)
    assert group, "the Appearance group names no description"
    note = re.search(rf'<p[^>]*\bid="{re.escape(group.group(1))}"[^>]*>([^<]*)</p>', html)
    assert note and note.group(1).strip() == NOTE


@pytest.mark.django_db
def test_a_declared_page_does_not_say_it_stays_light(client, team, monkeypatch):
    monkeypatch.setattr(screens, "DARK_READY", frozenset({ACCOUNT}))
    response = _account_page(client, team)
    assert response.context["theme_ready"] is True
    group = _appearance(_Page(response.content.decode()))
    assert NOTE not in " ".join(group["text"].split())


@pytest.mark.django_db
def test_the_portal_has_no_appearance_menu_but_the_same_script(client, team):
    """The portal keeps its own header (no account menu); the script still follows a declared page."""
    page = _Page(_portal_page(client, team).content.decode())
    _theme_script(page)
    assert not [fieldset for fieldset in page.fieldsets if "Appearance" in fieldset["legend"]]
