"""One primary per view, in its place (Phase 3, T8; docs/specs/phase-3.md; spec D5).

The counter reads a page's rendered HTML (``primary_findings``) and checks two things.

**At most one primary per view and breakpoint.** A primary is an element carrying ``ui-btn-primary``
or ``ui-fab`` (in ``class`` or a bound ``:class``/``x-bind:class``: a state that turns a button
primary still counts), or a solid ``bg-brand-700`` button or link (``<a>``, ``<button>``, a submit
input, ``role="button"``) that is not a control showing its checked state (``role`` switch, checkbox,
radio, tab or option; ``aria-pressed``, ``aria-checked`` or ``aria-selected``), where Pine marks the
choice, not an act (DESIGN_SYSTEM.md 3.2). The views are the page (everything outside
``role="dialog"`` and ``role="alertdialog"`` subtrees and ``<template>``) and each dialog (its own
subtree, nested dialogs and templates left out); a dialog with ``data-view`` panels is one view per
panel, each panel with whatever in the dialog sits outside every panel. The breakpoints are phones
(below 1024 px) and desktop (from 1024 px): an element counts at both unless it or an ancestor hides
it at one, ``lg:hidden`` (or ``sm:``/``md:hidden``) on desktop, ``max-lg:hidden`` or ``hidden`` with
an ``lg:`` display utility (``hidden lg:flex``) on phones. Anything else, hidden at rest included,
counts: a script may show it.

**Each primary in its place** (D5, with the owner's defaults: item and form decisions sit at the end
of the item or form on a desktop; Activity and Analytics have none):

* the screen-level primary is the floating button ``components/primary_action.html`` renders
  (``.ui-fab``): below 1024 px it carries the ``ABOVE_THE_BAR`` placement (``fixed right-4`` and the
  bottom above the phone bar, never ``max-sm:bottom-4``), and from 1024 px it is ``lg:static`` inside
  the page header's slot, an element marked ``data-primary-slot="header"``. A dialog has no
  screen-level primary;
* a decision's primary (about one item: the post page, an Approvals card, a portal card, the Inbox
  reply; or a form's Save or Send) sits inside its ``data-decision-bar``, the bar within thumb reach on
  a phone that sits at the end of the item or form on a desktop, in any view;
* from 1024 px a primary that shows on desktop only may also sit in the header slot;
* a primary anywhere else fails, so a departure the owner has not accepted cannot slip in.

Then every ``gated`` screen (``apps/common/screens.py``) is rendered page by page for each of its
roles and must have no finding. No screen is gated until screen 1's gate, so the counter is proved
here on fixture HTML, the wiring with a stand-in renderer, and the renderer on a real page.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from html.parser import HTMLParser
from types import SimpleNamespace

import pytest
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.common import screens
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace

# Above the phone bar: the same class string test_navigation_render.py pins for the toasts and the bars.
ABOVE_THE_BAR = "bottom-[calc(4.5rem+env(safe-area-inset-bottom))]"
#: The floating button's phone placement: fixed, 16 px from the right, above the phone bar.
FAB_ON_PHONES = frozenset({"fixed", "right-4", ABOVE_THE_BAR})
HEADER_SLOT = "header"

PHONE = "below 1024px"
DESKTOP = "from 1024px"
BREAKPOINTS = (PHONE, DESKTOP)

VOID = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
)
DIALOG_ROLES = frozenset({"dialog", "alertdialog"})
#: Controls whose Pine fill shows a checked state, not an act.
STATE_ROLES = frozenset({"switch", "checkbox", "radio", "tab", "option", "menuitemcheckbox", "menuitemradio"})
STATE_ATTRS = ("aria-pressed", "aria-checked", "aria-selected")
DESKTOP_HIDDEN = frozenset({"sm:hidden", "md:hidden", "lg:hidden"})
DISPLAYS = r"(?:block|flex|grid|inline|inline-block|inline-flex|inline-grid|table|contents|flow-root)"
SHOWN_FROM_DESKTOP = re.compile(rf"(?:lg|xl|2xl):{DISPLAYS}")
SHOWN_ON_PHONES = re.compile(rf"(?:sm|md):{DISPLAYS}")


# ── A small tree of the rendered HTML ──────────────────────────────────────────────────────────


@dataclass(eq=False)
class Node:
    tag: str
    attrs: dict[str, str]
    line: int
    parent: Node | None = None
    children: list[Node] = field(default_factory=list)

    @property
    def classes(self) -> frozenset[str]:
        """The words of its static ``class``: what it looks like at rest."""
        return frozenset(self.attrs.get("class", "").split())

    @property
    def bound_classes(self) -> frozenset[str]:
        """The class names a bound ``:class`` or ``x-bind:class`` may add."""
        words = f"{self.attrs.get(':class', '')} {self.attrs.get('x-bind:class', '')}".split()
        return frozenset(word.strip("'\"{}()[],:?!") for word in words)

    def ancestors(self) -> Iterator[Node]:
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    def lineage(self) -> Iterator[Node]:
        yield self
        yield from self.ancestors()

    def text(self) -> str:
        parts = [child.attrs["#text"] if child.tag == "#text" else child.text() for child in self.children]
        return " ".join(" ".join(parts).split())

    def name(self) -> str:
        for key in ("data-testid", "aria-label", "aria-labelledby", "id"):
            if self.attrs.get(key):
                return self.attrs[key]
        return self.text()[:40] or self.tag


class _Tree(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#document", {}, 0)
        self.stack = [self.root]

    def _node(self, tag: str, attrs: list[tuple[str, str | None]]) -> Node:
        node = Node(tag, {key: value or "" for key, value in attrs}, self.getpos()[0], parent=self.stack[-1])
        self.stack[-1].children.append(node)
        return node

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = self._node(tag, attrs)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._node(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.stack[-1].children.append(Node("#text", {"#text": data}, self.getpos()[0], parent=self.stack[-1]))


def parse(html: str) -> Node:
    tree = _Tree()
    tree.feed(html)
    tree.close()
    return tree.root


def elements(node: Node) -> Iterator[Node]:
    """Every element under *node*, depth first, text left out (dialogs and templates included)."""
    for child in node.children:
        if child.tag != "#text":
            yield child
            yield from elements(child)


def _is_dialog(node: Node) -> bool:
    return node.attrs.get("role") in DIALOG_ROLES


def _members(top: Node) -> Iterator[Node]:
    """The elements of *top*'s own view: no nested dialog and nothing inside a ``<template>``."""
    for child in top.children:
        if child.tag in ("#text", "template") or _is_dialog(child):
            continue
        yield child
        yield from _members(child)


def _dialogs(node: Node) -> Iterator[Node]:
    for child in node.children:
        if child.tag in ("#text", "template"):
            continue
        if _is_dialog(child):
            yield child
        yield from _dialogs(child)


@dataclass
class View:
    name: str
    members: list[Node]
    is_page: bool


def views(html: str) -> list[View]:
    """The page, then each dialog (one view per ``data-view`` panel when it has panels)."""
    root = parse(html)
    found = [View("the page", list(_members(root)), True)]
    for dialog in _dialogs(root):
        members = list(_members(dialog))
        panels = [member for member in members if "data-view" in member.attrs]
        if not panels:
            found.append(View(f"dialog {dialog.name()!r}", members, False))
            continue

        def panel_of(member: Node, dialog: Node = dialog) -> Node | None:
            for node in member.lineage():
                if node is dialog:
                    return None
                if "data-view" in node.attrs:
                    return node
            return None

        for panel in panels:
            found.append(
                View(
                    f"dialog {dialog.name()!r}, panel {panel.attrs['data-view']!r}",
                    [member for member in members if panel_of(member) in (None, panel)],
                    False,
                )
            )
    return found


# ── What counts, where it shows, where it sits ─────────────────────────────────────────────────


def _is_action(node: Node) -> bool:
    if node.tag in ("a", "button") or node.attrs.get("role") in ("button", "link"):
        return True
    return node.tag == "input" and node.attrs.get("type", "").lower() in ("submit", "button")


def is_primary(node: Node) -> bool:
    words = node.classes | node.bound_classes
    if "ui-btn-primary" in words or "ui-fab" in words:
        return True
    if "bg-brand-700" not in words or not _is_action(node):
        return False
    return node.attrs.get("role") not in STATE_ROLES and not any(attr in node.attrs for attr in STATE_ATTRS)


def shown_at(node: Node) -> tuple[str, ...]:
    """The breakpoints at which neither *node* nor an ancestor hides it."""
    phone = desktop = True
    for each in node.lineage():
        classes = each.classes
        if classes & DESKTOP_HIDDEN:
            desktop = False
        if "max-lg:hidden" in classes:
            phone = False
        if (
            "hidden" in classes
            and any(SHOWN_FROM_DESKTOP.fullmatch(word) for word in classes)
            and not any(SHOWN_ON_PHONES.fullmatch(word) for word in classes)
        ):
            phone = False
    return tuple(breakpoint for breakpoint, shown in ((PHONE, phone), (DESKTOP, desktop)) if shown)


def _in_decision_bar(node: Node) -> bool:
    return any("data-decision-bar" in each.attrs for each in node.lineage())


def _in_header_slot(node: Node) -> bool:
    return any(each.attrs.get("data-primary-slot") == HEADER_SLOT for each in node.lineage())


def place_problem(node: Node, breakpoint: str, *, on_the_page: bool) -> str | None:
    """Why *node*, a primary shown at *breakpoint*, is out of its place (D5), or None."""
    if "ui-fab" in node.classes:
        if not on_the_page:
            return "a floating button inside a dialog (a dialog has no screen-level primary)"
        if breakpoint == PHONE:
            if not node.classes >= FAB_ON_PHONES or "max-sm:bottom-4" in node.classes:
                return f"the floating button is not fixed 16px from the right above the phone bar ({ABOVE_THE_BAR})"
            return None
        if "lg:static" not in node.classes:
            return "the floating button still floats from 1024px (it is lg:static in the page header)"
        if not _in_header_slot(node):
            return "from 1024px the screen's primary sits in the page header's data-primary-slot=\"header\""
        return None
    if _in_decision_bar(node):
        return None
    if breakpoint == DESKTOP and on_the_page and _in_header_slot(node):
        return None
    return (
        "not in its place: the screen's primary is the floating button (components/primary_action.html), "
        "a decision's primary sits in its data-decision-bar"
    )


@dataclass(frozen=True)
class Finding:
    view: str
    breakpoint: str
    line: int
    reason: str

    def __str__(self) -> str:
        return f"{self.view}, {self.breakpoint}, line {self.line}: {self.reason}"


def primary_findings(html: str) -> list[Finding]:
    """Every view and breakpoint with more than one primary, and every primary out of its place."""
    findings: list[Finding] = []
    for view in views(html):
        primaries = [node for node in view.members if is_primary(node)]
        for breakpoint in BREAKPOINTS:
            shown = [node for node in primaries if breakpoint in shown_at(node)]
            if len(shown) > 1:
                names = ", ".join(f"{node.name()!r} (line {node.line})" for node in shown)
                findings.append(Finding(view.name, breakpoint, shown[1].line, f"{len(shown)} primaries: {names}"))
            for node in shown:
                problem = place_problem(node, breakpoint, on_the_page=view.is_page)
                if problem:
                    findings.append(Finding(view.name, breakpoint, node.line, f"{node.name()!r}: {problem}"))
    return findings


# ── The gated screens, page by page and role by role ───────────────────────────────────────────

Render = Callable[[screens.Page, str], str]


def gated_pages(registry: Mapping[str, screens.Screen] | None = None) -> list[tuple[str, screens.Page, str]]:
    """``(screen, page, role)`` for every page of every gated screen and every role that may open it."""
    found: list[tuple[str, screens.Page, str]] = []
    for name, screen in (screens.SCREENS if registry is None else registry).items():
        if screen.gated:
            found += [(name, page, role) for page in screen.pages for role in screen.roles]
    return found


def screen_findings(render: Render, registry: Mapping[str, screens.Screen] | None = None) -> list[str]:
    findings: list[str] = []
    for name, page, role in gated_pages(registry):
        findings += [
            f"{name}: {page[0]}:{page[1]} as {role}: {finding}" for finding in primary_findings(render(page, role))
        ]
    return findings


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
    """One workspace and a member per built-in role, made when first asked for."""
    org = Organization.objects.create(name="Org")
    ws = Workspace.objects.create(organization=org, name="WS")
    people: dict[str, User] = {}

    def member(role: str) -> User:
        if role not in people:
            user = _person(f"{role}@example.com")
            OrgMembership.objects.create(user=user, organization=org, org_role="owner" if role == "owner" else "member")
            WorkspaceMembership.objects.create(user=user, workspace=ws, workspace_role=role)
            people[role] = user
        return people[role]

    return SimpleNamespace(org=org, ws=ws, member=member)


@pytest.fixture
def render(client, team) -> Render:
    """Render a page of the team's workspace as a member with *role*; it must open (200)."""

    def page_html(page: screens.Page, role: str) -> str:
        client.force_login(team.member(role))
        response = client.get(reverse(f"{page[0]}:{page[1]}", kwargs={"workspace_id": team.ws.id}))
        assert response.status_code == 200, (page, role, response.status_code)
        return response.content.decode()

    return page_html


def test_gated_screens_have_one_primary_per_view_in_its_place(render):
    findings = screen_findings(render)
    assert not findings, "A gated screen breaks one primary per view, in its place (spec D5):\n" + "\n".join(findings)


def test_the_guard_renders_every_page_of_a_gated_screen_for_each_role_and_nothing_else():
    rendered: list[tuple[screens.Page, str]] = []
    pages = {
        ("studio", "index"): '<main><button class="ui-btn ui-btn-primary">Send</button></main>',
        ("calendar", "calendar"): '<main><a class="ui-btn ui-btn-tinted">Open</a></main>',
    }

    def fake(page: screens.Page, role: str) -> str:
        rendered.append((page, role))
        return pages[page]

    registry = {
        "rebuilt": screens.Screen(
            templates=("studio/index.html",),
            pages=(("studio", "index"), ("calendar", "calendar")),
            roles=("owner", "viewer"),
            gated=True,
        ),
        "next": screens.Screen(templates=("approvals/index.html",), pages=(("approvals", "index"),), roles=("owner",)),
    }

    findings = screen_findings(fake, registry)

    assert rendered == [
        (("studio", "index"), "owner"),
        (("studio", "index"), "viewer"),
        (("calendar", "calendar"), "owner"),
        (("calendar", "calendar"), "viewer"),
    ]
    assert len(findings) == 4  # Home's stray Send, at both breakpoints, for both roles
    assert findings[0].startswith(
        "rebuilt: studio:index as owner: the page, below 1024px, line 1: 'Send': not in its place"
    )


@pytest.mark.django_db
def test_the_renderer_reads_a_real_page_and_its_shell_dialogs(render):
    found = views(render(("studio", "index"), "owner"))
    assert found[0].is_page and len(found[0].members) > 50
    dialogs = {view.name for view in found[1:]}
    assert "dialog 'notifications-drawer'" in dialogs and "dialog 'palette-dialog'" in dialogs, dialogs


# ── The count, on fixture HTML ─────────────────────────────────────────────────────────────────

FAB = f'<button class="ui-btn ui-btn-primary ui-fab fixed right-4 {ABOVE_THE_BAR} z-20 lg:static">New post</button>'
SLOT_WITH_FAB = f'<header><h1>Home</h1><div data-primary-slot="header">{FAB}</div></header>'


def _counts(html: str) -> dict[str, dict[str, int]]:
    return {
        view.name: {bp: sum(1 for n in view.members if is_primary(n) and bp in shown_at(n)) for bp in BREAKPOINTS}
        for view in views(html)
    }


@pytest.mark.parametrize(
    "html",
    [
        '<button class="ui-btn ui-btn-primary">Save</button>',
        '<a class="ui-btn ui-fab">New post</a>',
        '<a href="/x" class="inline-flex bg-brand-700 text-on-fill">Approve</a>',
        '<button class="bg-brand-700 text-on-fill">Send</button>',
        '<input type="submit" class="bg-brand-700" value="Send">',
        '<span role="button" class="bg-brand-700">Send</span>',
        "<button class=\"ui-btn\" :class=\"ready ? 'ui-btn-primary' : 'ui-btn-secondary'\">Send</button>",
        '<button class="ui-btn" x-bind:class="{ \'ui-btn-primary\': ready }">Send</button>',
        '<button class="ui-btn ui-btn-primary hidden">Shown by a script</button>',
        '<div x-show="open" x-cloak><button class="ui-btn ui-btn-primary">Later</button></div>',
    ],
)
def test_a_primary_is_counted(html):
    assert _counts(html)["the page"] == {PHONE: 1, DESKTOP: 1}, html


@pytest.mark.parametrize(
    "html",
    [
        '<button class="ui-btn ui-btn-tinted">Approve &amp; schedule</button>',
        '<button class="ui-btn ui-btn-secondary hover:bg-brand-700">Run now</button>',
        '<span class="ui-badge ui-badge-turn bg-brand-700">3</span>',
        '<div class="h-1 bg-brand-700"></div>',
        '<button class="bg-brand-700/10 text-brand-700">Tinted by hand</button>',
        '<button role="switch" aria-checked="true" class="bg-brand-700">Autopilot</button>',
        '<button aria-pressed="true" class="bg-brand-700">Monday</button>',
        '<a role="tab" aria-selected="true" class="bg-brand-700">Week</a>',
        '<template x-if="open"><button class="ui-btn ui-btn-primary">Not rendered</button></template>',
        '<div role="dialog" aria-label="Sheet"><button class="ui-btn ui-btn-primary">Send</button></div>',
        '<div role="alertdialog" aria-label="Sure?"><button class="ui-btn ui-btn-primary">Go</button></div>',
        "<script>var html = '<button class=\"ui-btn ui-btn-primary\">x</button>';</script>",
    ],
)
def test_what_is_not_a_primary_of_the_page(html):
    assert _counts(html)["the page"] == {PHONE: 0, DESKTOP: 0}, html


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ('<button class="ui-btn ui-btn-primary hidden lg:inline-flex">x</button>', {PHONE: 0, DESKTOP: 1}),
        ('<div class="hidden lg:block"><button class="ui-btn ui-btn-primary">x</button></div>', {PHONE: 0, DESKTOP: 1}),
        ('<div class="hidden xl:flex"><button class="ui-btn ui-btn-primary">x</button></div>', {PHONE: 0, DESKTOP: 1}),
        ('<button class="ui-btn ui-btn-primary max-lg:hidden">x</button>', {PHONE: 0, DESKTOP: 1}),
        ('<button class="ui-btn ui-btn-primary lg:hidden">x</button>', {PHONE: 1, DESKTOP: 0}),
        (
            '<div class="lg:hidden"><p><button class="ui-btn ui-btn-primary">x</button></p></div>',
            {PHONE: 1, DESKTOP: 0},
        ),
        ('<button class="ui-btn ui-btn-primary md:hidden">x</button>', {PHONE: 1, DESKTOP: 0}),
        ('<button class="ui-btn ui-btn-primary hidden sm:inline-flex">x</button>', {PHONE: 1, DESKTOP: 1}),
        ('<button class="ui-btn ui-btn-primary hidden sm:flex lg:hidden">x</button>', {PHONE: 1, DESKTOP: 0}),
        ('<button class="ui-btn ui-btn-primary xl:hidden">x</button>', {PHONE: 1, DESKTOP: 1}),
    ],
)
def test_breakpoint_classes_decide_where_a_primary_counts(html, expected):
    assert _counts(html)["the page"] == expected


def test_a_phone_primary_and_a_desktop_primary_are_one_per_breakpoint():
    html = (
        '<div data-decision-bar class="lg:hidden"><button class="ui-btn ui-btn-primary">Approve &amp; schedule</button></div>'
        '<div data-decision-bar class="hidden lg:block"><button class="ui-btn ui-btn-primary">Approve &amp; schedule</button></div>'
    )
    assert _counts(html)["the page"] == {PHONE: 1, DESKTOP: 1}
    assert primary_findings(html) == []


def test_two_primaries_in_one_view_fail_and_name_both():
    html = f'{SLOT_WITH_FAB}<form data-decision-bar><button class="ui-btn ui-btn-primary">Save</button></form>'
    findings = primary_findings(html)
    assert [(f.view, f.breakpoint) for f in findings] == [("the page", PHONE), ("the page", DESKTOP)]
    assert "2 primaries: 'New post' (line 1), 'Save' (line 1)" in findings[0].reason


def test_each_dialog_and_each_of_its_panels_is_a_view_of_its_own():
    html = (
        f"{SLOT_WITH_FAB}"
        '<div role="dialog" aria-label="New post" data-testid="new-post-sheet">'
        "  <h2>New post</h2>"
        '  <section data-view="team"><form><div data-decision-bar><button class="ui-btn ui-btn-primary">Send</button></div></form></section>'
        '  <section data-view="self"><a class="ui-btn ui-btn-primary" data-decision-bar>Open the editor</a></section>'
        '  <section data-view="idea"><div data-decision-bar><button class="ui-btn ui-btn-primary">Save idea</button></div>'
        '    <div role="dialog" aria-label="New tag"><div data-decision-bar><button class="ui-btn ui-btn-primary">Create tag</button></div></div>'
        "  </section>"
        "</div>"
        '<div role="dialog" aria-label="Go to"><input></div>'
    )
    assert _counts(html) == {
        "the page": {PHONE: 1, DESKTOP: 1},
        "dialog 'new-post-sheet', panel 'team'": {PHONE: 1, DESKTOP: 1},
        "dialog 'new-post-sheet', panel 'self'": {PHONE: 1, DESKTOP: 1},
        "dialog 'new-post-sheet', panel 'idea'": {PHONE: 1, DESKTOP: 1},
        "dialog 'New tag'": {PHONE: 1, DESKTOP: 1},
        "dialog 'Go to'": {PHONE: 0, DESKTOP: 0},
    }
    assert primary_findings(html) == []


def test_a_primary_outside_every_panel_belongs_to_each_panel():
    html = (
        '<div role="dialog" aria-label="Sheet">'
        '<div data-decision-bar><button class="ui-btn ui-btn-primary">Done</button></div>'
        '<section data-view="a"><p>One</p></section>'
        '<section data-view="b"><div data-decision-bar><button class="ui-btn ui-btn-primary">Send</button></div></section>'
        "</div>"
    )
    counts = _counts(html)
    assert counts["dialog 'Sheet', panel 'a'"] == {PHONE: 1, DESKTOP: 1}
    assert counts["dialog 'Sheet', panel 'b'"] == {PHONE: 2, DESKTOP: 2}
    assert {f.view for f in primary_findings(html)} == {"dialog 'Sheet', panel 'b'"}


# ── The place, on fixture HTML ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "html",
    [
        # The screen's floating button, in the header slot.
        SLOT_WITH_FAB,
        # A decision bar, on the page or in a dialog, at both breakpoints.
        '<div data-decision-bar class="fixed inset-x-0 bottom-0 lg:static"><button class="ui-btn ui-btn-primary">Approve &amp; schedule</button></div>',
        '<article><p>Post</p><div data-decision-bar><form><button class="ui-btn ui-btn-primary">Approve</button></form></div></article>',
        '<form><div data-decision-bar><button type="submit" class="ui-btn ui-btn-primary">Save</button></div></form>',
        '<div role="dialog" aria-label="S"><form><div data-decision-bar><button class="ui-btn ui-btn-primary">Send</button></div></form></div>',
        # A desktop-only primary in the header slot.
        '<div data-primary-slot="header"><a class="ui-btn ui-btn-primary hidden lg:inline-flex">New post</a></div>',
        # No primary at all (a watch-only screen).
        "<main><h1>Activity</h1><button class='ui-btn ui-btn-secondary'>Run now</button></main>",
    ],
)
def test_a_primary_in_its_place_passes(html):
    assert primary_findings(html) == [], primary_findings(html)


@pytest.mark.parametrize(
    ("html", "breakpoints", "reason"),
    [
        # A stray solid button: no floating button, no decision bar.
        (
            '<div class="flex"><button class="ui-btn ui-btn-primary">Save</button></div>',
            {PHONE, DESKTOP},
            "not in its place",
        ),
        ('<a href="/x" class="bg-brand-700 text-on-fill">Go</a>', {PHONE, DESKTOP}, "not in its place"),
        # In the header slot, but showing on phones without floating.
        (
            '<div data-primary-slot="header"><a class="ui-btn ui-btn-primary">New post</a></div>',
            {PHONE},
            "not in its place",
        ),
        # A floating button that keeps the old bottom, or misses the phone bar.
        (
            '<div data-primary-slot="header"><button class="ui-btn ui-btn-primary ui-fab fixed right-4 bottom-6 max-sm:bottom-4 lg:static">x</button></div>',
            {PHONE},
            "above the phone bar",
        ),
        (
            f'<div data-primary-slot="header"><button class="ui-btn ui-btn-primary ui-fab fixed right-4 {ABOVE_THE_BAR} max-sm:bottom-4 lg:static">x</button></div>',
            {PHONE},
            "above the phone bar",
        ),
        (
            f'<div data-primary-slot="header"><button class="ui-btn ui-btn-primary ui-fab fixed right-6 {ABOVE_THE_BAR} lg:static">x</button></div>',
            {PHONE},
            "above the phone bar",
        ),
        # A floating button that still floats from 1024px, or sits outside the header slot.
        (
            f'<div data-primary-slot="header"><button class="ui-fab fixed right-4 {ABOVE_THE_BAR}">x</button></div>',
            {DESKTOP},
            "lg:static",
        ),
        (
            f'<div class="flex"><button class="ui-fab fixed right-4 {ABOVE_THE_BAR} lg:static">x</button></div>',
            {DESKTOP},
            "page header",
        ),
        (f'<div data-primary-slot="footer">{FAB}</div>', {DESKTOP}, "page header"),
        # A floating button in a dialog.
        (
            f'<div role="dialog" aria-label="S"><div data-primary-slot="header">{FAB}</div></div>',
            {PHONE, DESKTOP},
            "inside a dialog",
        ),
        # A dialog's primary outside its decision bar, even in a header slot.
        (
            '<div role="dialog" aria-label="S"><button class="ui-btn ui-btn-primary">Send</button></div>',
            {PHONE, DESKTOP},
            "not in its place",
        ),
        (
            '<div role="dialog" aria-label="S"><div data-primary-slot="header"><a class="ui-btn ui-btn-primary hidden lg:inline-flex">x</a></div></div>',
            {DESKTOP},
            "not in its place",
        ),
    ],
)
def test_a_primary_anywhere_else_fails(html, breakpoints, reason):
    findings = primary_findings(html)
    assert {finding.breakpoint for finding in findings} == breakpoints, findings
    assert all(reason in finding.reason for finding in findings), findings


def test_the_shared_component_is_in_its_place_at_both_breakpoints():
    """components/primary_action.html, rendered in the page header's slot, passes the counter as is."""
    button = render_to_string(
        "components/primary_action.html",
        {"label": "New post", "testid": "new-post-open", "controls": "new-post-sheet", "dispatch": "new-post:open"},
    )
    html = f'<header class="flex items-center justify-between"><h1>Home</h1><div data-primary-slot="header">{button}</div></header>'
    assert _counts(html)["the page"] == {PHONE: 1, DESKTOP: 1}
    assert primary_findings(html) == []
    # Outside the slot it would float on desktop too: the counter says so.
    assert {f.breakpoint for f in primary_findings(f"<header>{button}</header>")} == {DESKTOP}


def test_a_finding_reads_as_a_sentence():
    finding = primary_findings('<p>\n<button class="ui-btn ui-btn-primary">Save</button></p>')[0]
    assert str(finding).startswith("the page, below 1024px, line 2: 'Save': not in its place")
