"""The New post sheet and its trigger on Home and Calendar (Phase 3, screen 1, T16).

Who may start posts (``create_posts`` and not a plain client: ``views.can_start_posts``, the rule
``studio:create`` enforces) gets one **New post** button and one sheet on Home and Calendar, and nobody
else gets either. The button is ``components/primary_action.html``: floating above the phone bar below
1024 px and in the page header's primary slot from 1024 px, with ``has-fab`` on ``body``. The sheet is a
labelled, trapped dialog with a mode control, three panels (``data-view``) and the foot links; its
*Ask the team* panel renders ``BriefForm`` and posts to ``studio:create`` through HTMX, writing a
refusal into its own error line (``data-inline-error``). The browser behaviour (opening, focus,
Escape, ``#new-post``) is T21's (``tests/e2e/screens/new-post.spec.ts``).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.common.tests.test_navigation_render import ABOVE_THE_BAR
from apps.common.tests.test_one_primary import (
    BREAKPOINTS,
    Node,
    elements,
    is_primary,
    parse,
    primary_findings,
    shown_at,
    views,
)
from apps.common.tests.test_spacing_grid import off_grid
from apps.members.models import WorkspaceMembership
from apps.studio import views as studio_views
from apps.studio.forms import BriefForm, studio_accounts
from apps.studio.models import AgencySettings

HOME = ("studio", "index")
CALENDAR = ("calendar", "calendar")
PAGES = (HOME, CALENDAR)
STARTERS = ("owner", "manager", "editor")
TEMPLATES = Path(__file__).resolve().parents[3] / "templates"
#: The templates T16 writes; the spacing guard reads them once screen 1 is gated (T25).
NEW_TEMPLATES = ("components/new_post_sheet.html", "studio/partials/new_post_team.html")
ALLOWANCE = "This starts the team's work and counts toward this month's allowance."
HELP = "Your manager replies with what we're making. Nothing is made until you go ahead."
LOOK = "Keep the brand look"
#: Primaries already on these pages that other tasks move (each in its own place, not the sheet's):
#: Home's thread Send becomes tinted in screen 2 (spec, "Screen 2 · Home"); Calendar's Add event is
#: screen 4's. The count below proves the button adds exactly one primary beside them.
MOVED_LATER = {HOME: {"thread-composer-send"}, CALENDAR: {"Add event"}}


def _url(world, page, **kwargs):
    return reverse(f"{page[0]}:{page[1]}", kwargs={"workspace_id": world.workspace.id, **kwargs})


def _client_member(world):
    user = world.viewer.__class__.objects.create_user(
        email="client@example.com", password="pw-12345678", name="Client", tos_accepted_at=timezone.now()
    )
    WorkspaceMembership.objects.create(user=user, workspace=world.workspace, workspace_role="client")
    return user


def _page(client, world, page, user, query=""):
    client.force_login(user)
    response = client.get(_url(world, page) + query)
    assert response.status_code == 200, (page, response.status_code)
    return response.content.decode()


def _all(root: Node, **attrs: str) -> list[Node]:
    return [node for node in elements(root) if all(node.attrs.get(key) == value for key, value in attrs.items())]


def _one(root: Node, **attrs: str) -> Node:
    found = _all(root, **attrs)
    assert len(found) == 1, (attrs, len(found))
    return found[0]


def _inside(node: Node, ancestor: Node) -> bool:
    return any(each is ancestor for each in node.ancestors())


def _sheet(html: str) -> Node:
    return _one(parse(html), **{"data-testid": "new-post-sheet"})


def _visible_text(node: Node) -> str:
    """The sheet's words as a person meets them: its text, and the labels, placeholders and titles."""
    parts = [node.text()]
    for each in elements(node):
        parts += [each.attrs.get(key, "") for key in ("aria-label", "placeholder", "title")]
        parts += re.findall(r"'([^']*)'", each.attrs.get("x-text", ""))
    return " ".join(part for part in parts if part)


# ── Who gets the button and the sheet ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("page", PAGES, ids=["home", "calendar"])
@pytest.mark.parametrize("role", STARTERS)
def test_who_may_start_posts_gets_one_trigger_and_one_sheet(client, world, role, page):
    html = _page(client, world, page, getattr(world, role))
    root = parse(html)

    trigger = _one(root, **{"data-testid": "new-post-open"})
    assert trigger.tag == "button" and trigger.attrs.get("type") == "button"
    assert trigger.text() == "New post"
    assert trigger.attrs.get("aria-haspopup") == "dialog"
    assert trigger.attrs.get("aria-expanded") == "false"
    assert trigger.attrs.get("aria-controls") == "new-post-sheet"
    assert "new-post:open" in trigger.attrs.get("@click", "")
    assert {"ui-btn", "ui-btn-primary", "ui-fab", "fixed", "right-4", ABOVE_THE_BAR, "lg:static"} <= trigger.classes
    assert any(each.attrs.get("data-primary-slot") == "header" for each in trigger.ancestors())
    body = next(node for node in elements(root) if node.tag == "body")
    assert "has-fab" in body.classes

    sheet = _sheet(html)
    assert sheet.attrs.get("id") == "new-post-sheet"
    assert sheet.attrs.get("role") == "dialog" and sheet.attrs.get("aria-modal") == "true"
    assert sheet.attrs.get("aria-labelledby") == "new-post-title"
    assert any(key.startswith("x-trap.noscroll") for key in sheet.attrs), sheet.attrs
    # A bottom sheet below 1024 px, a 480 px drawer on the right from 1024 px, on the sheet's motion.
    assert {"rounded-t-2xl", "max-h-[92vh]", "lg:w-[480px]", "lg:rounded-none"} <= sheet.classes
    assert sheet.attrs.get("x-transition:enter") == "motion-sheet-enter"
    assert (
        sheet.attrs.get("x-transition:enter-start") == sheet.attrs.get("x-transition:leave-end") == "motion-sheet-out"
    )
    assert sheet.attrs.get("x-transition:enter-end") == sheet.attrs.get("x-transition:leave-start") == "motion-sheet-in"
    assert sheet.attrs.get("x-transition:leave") == "motion-sheet-leave"
    overlay = next(each for each in sheet.ancestors() if {"fixed", "inset-0"} <= each.classes)
    assert any("ui-overlay" in each.classes for each in elements(overlay))
    # The heading names the dialog (statically, as the a11y sweep reads it); the idea form renames it.
    title = _one(sheet, id="new-post-title")
    assert title.tag == "h2" and title.text() == "New post"
    assert "New idea" in title.attrs.get("x-text", "")
    grabber = [each for each in elements(sheet) if each.attrs.get("data-sheet-grabber") is not None]
    assert len(grabber) == 1 and grabber[0].attrs.get("aria-hidden") == "true" and "lg:hidden" in grabber[0].classes
    close = _one(sheet, **{"data-testid": "new-post-close"})
    assert close.tag == "button" and close.attrs.get("aria-label") == "Close"

    modes = _one(sheet, role="group")
    assert modes.attrs.get("aria-label") == "How to start"
    team, myself = (_one(modes, **{"data-testid": f"new-post-mode-{mode}"}) for mode in ("team", "self"))
    assert team.text() == "Ask the team" and myself.text() == "Write it myself"
    assert team.attrs.get("aria-pressed") == "true" and myself.attrs.get("aria-pressed") == "false"
    assert {node.attrs["data-view"] for node in elements(sheet) if "data-view" in node.attrs} == {
        "team",
        "self",
        "idea",
    }
    assert len([node for node in elements(sheet) if "data-view" in node.attrs]) == 3


@pytest.mark.parametrize("page", PAGES, ids=["home", "calendar"])
def test_the_foot_links_reach_their_pages_and_follow_the_templates_switch(client, world, page):
    kwargs = {"workspace_id": world.workspace.id}
    expected = {
        "ideas": reverse("composer:create_landing", kwargs=kwargs),
        "drafts": reverse("calendar:calendar", kwargs=kwargs) + "?mode=list&tab=drafts",
        "csv": reverse("composer:csv_upload", kwargs=kwargs),
    }
    switched = {
        "templates": reverse("composer:template_list", kwargs=kwargs),
        "categories": reverse("composer:category_list", kwargs=kwargs),
    }

    sheet = _sheet(_page(client, world, page, world.owner))
    links = {key: _all(sheet, **{"data-testid": f"new-post-link-{key}"}) for key in (*expected, *switched)}
    assert {key: [node.attrs.get("href") for node in found] for key, found in links.items()} == {
        **{key: [href] for key, href in expected.items()},
        "templates": [],
        "categories": [],
    }
    assert [links[key][0].text() for key in expected] == ["Ideas", "Drafts", "Import from CSV"]

    AgencySettings.objects.update_or_create(workspace=world.workspace, defaults={"features": {"templates": True}})
    sheet = _sheet(_page(client, world, page, world.owner))
    for key, href in switched.items():
        assert [node.attrs.get("href") for node in _all(sheet, **{"data-testid": f"new-post-link-{key}"})] == [href]


@pytest.mark.parametrize("page", PAGES, ids=["home", "calendar"])
def test_a_viewer_gets_neither_the_button_nor_the_sheet(client, world, page):
    html = _page(client, world, page, world.viewer)

    assert "new-post-open" not in html and "new-post-sheet" not in html
    body = next(node for node in elements(parse(html)) if node.tag == "body")
    assert "has-fab" not in body.classes


def test_a_plain_client_gets_calendar_without_them_and_home_stays_closed(client, world):
    user = _client_member(world)

    html = _page(client, world, CALENDAR, user)
    assert "new-post-open" not in html and "new-post-sheet" not in html
    assert client.get(_url(world, HOME)).status_code == 403


def test_can_start_posts_is_create_posts_and_not_a_plain_client(world):
    memberships = {m.workspace_role: m for m in WorkspaceMembership.objects.filter(workspace=world.workspace)}
    assert [studio_views.can_start_posts(memberships[role]) for role in (*STARTERS, "viewer")] == [
        True,
        True,
        True,
        False,
    ]
    client_membership = WorkspaceMembership.objects.get(user=_client_member(world), workspace=world.workspace)
    assert studio_views.can_start_posts(client_membership) is False
    assert studio_views.can_start_posts(None) is False


@pytest.mark.parametrize(
    "name",
    ["approvals:index", "inbox:feed", "studio:team", "settings:index"],
    ids=["approvals", "inbox", "activity", "settings"],
)
def test_no_sheet_on_the_other_places(client, world, name):
    client.force_login(world.owner)
    response = client.get(reverse(name, kwargs={"workspace_id": world.workspace.id}))
    assert response.status_code == 200
    html = response.content.decode()

    for hook in ("new-post-open", "new-post-sheet", "new-post-team"):
        assert hook not in html, (name, hook)
    body = next(node for node in elements(parse(html)) if node.tag == "body")
    assert "has-fab" not in body.classes


# ── Ask the team: the form ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("page", PAGES, ids=["home", "calendar"])
def test_ask_the_team_posts_to_studio_create_and_shows_refusals_in_its_own_line(client, world, page):
    sheet = _sheet(_page(client, world, page, world.editor))
    panel = _one(sheet, **{"data-view": "team"})
    form = _one(panel, **{"data-testid": "new-post-team"})
    create = reverse("studio:create", kwargs={"workspace_id": world.workspace.id})

    assert form.tag == "form"
    assert form.attrs.get("hx-post") == create and form.attrs.get("action") == create
    assert form.attrs.get("method") == "post"
    assert form.attrs.get("hx-swap") == "none"
    assert form.attrs.get("data-inline-error") == "#new-post-team-error"
    assert form.attrs.get("hx-disabled-elt")
    # base.html's handler returns on data-no-error-toast before it reads data-inline-error.
    assert "data-no-error-toast" not in form.attrs
    assert _all(form, name="csrfmiddlewaretoken")

    error = _one(form, id="new-post-team-error")
    assert error.attrs.get("data-testid") == "new-post-team-error" and error.attrs.get("role") == "alert"
    idea = _one(form, **{"data-testid": "new-post-team-idea"})
    assert idea.tag == "textarea" and idea.attrs.get("name") == "idea"
    assert idea.attrs.get("maxlength") == "2000" and "required" in idea.attrs
    send = _one(form, **{"data-testid": "new-post-team-send"})
    assert send.tag == "button" and send.attrs.get("type") == "submit" and send.text() == "Send"
    assert "ui-btn-primary" in send.classes
    bar = next(each for each in send.ancestors() if "data-decision-bar" in each.attrs)
    assert _inside(error, bar)
    assert ALLOWANCE in bar.text()
    assert HELP in panel.text()
    # Everything the view reads, under its own names.
    names = {node.attrs["name"] for node in elements(form) if node.tag in ("input", "select", "textarea")}
    assert names == {"csrfmiddlewaretoken", "idea", "accounts", "goal", "notes", "source_picture", "style_lock"}
    more = [each for each in elements(form) if each.tag == "details"]
    assert len(more) == 1 and more[0].children[0].tag == "summary" and more[0].children[0].text() == "More"
    for name in ("goal", "notes", "source_picture", "style_lock"):
        assert _inside(_one(form, name=name), more[0]), name
    assert not _inside(idea, more[0]) and not _inside(_all(form, name="accounts")[0], more[0])
    # The look checkbox in the plan's and spec's words, which are the thread's for the same choice.
    look = _one(form, name="style_lock")
    assert look.attrs.get("type") == "checkbox"
    assert next(each for each in look.ancestors() if each.tag == "label").text() == LOOK


@pytest.mark.parametrize("page", PAGES, ids=["home", "calendar"])
def test_every_control_in_the_sheet_is_labelled(client, world, page):
    sheet = _sheet(_page(client, world, page, world.owner))
    labels = {node.attrs.get("for") for node in elements(sheet) if node.tag == "label"}

    unlabelled = []
    for node in elements(sheet):
        if node.tag not in ("input", "select", "textarea") or node.attrs.get("type") == "hidden":
            continue
        wrapped = any(each.tag == "label" for each in node.ancestors())
        if not (wrapped or node.attrs.get("aria-label") or node.attrs.get("id") in labels):
            unlabelled.append(node.attrs)
    assert not unlabelled
    for node in elements(sheet):
        if node.tag == "button":
            assert node.text() or node.attrs.get("aria-label"), node.attrs


@pytest.mark.parametrize("page", PAGES, ids=["home", "calendar"])
def test_the_channels_are_the_workspace_s_studio_accounts_with_the_form_s_choice(client, world, page):
    sheet = _sheet(_page(client, world, page, world.owner))
    channels = _one(sheet, **{"data-testid": "new-post-team-channels"})
    boxes = [node for node in elements(channels) if node.tag == "input" and node.attrs.get("name") == "accounts"]

    assert [box.attrs.get("value") for box in boxes] == [
        str(account.pk) for account in studio_accounts(world.workspace)
    ]
    assert all(box.attrs.get("type") == "checkbox" for box in boxes)
    initial = BriefForm(workspace=world.workspace).initial["accounts"]
    assert [box.attrs.get("value") for box in boxes if "checked" in box.attrs] == initial == [str(world.linkedin.pk)]
    assert channels.tag == "fieldset" and channels.children[0].tag == "legend"
    assert channels.children[0].text() == "Post to"


@pytest.mark.parametrize("ticked", [False, True], ids=["none-ticked", "one-ticked"])
@pytest.mark.parametrize("refusal", ["invalid-form", "chat-error"])
def test_a_page_re_render_keeps_the_channels_and_the_person_s_choice(client, world, monkeypatch, refusal, ticked):
    """Without HTMX a refusal after the form is read re-renders Home (400). ``studio:create`` validates
    without the channels when none is ticked; the sheet on that page still lists them under their legend."""
    from apps.studio import chat, customer_workflow

    if refusal == "chat-error":

        def refuse(*args, **kwargs):
            raise chat.ChatError("Write a message first.")

        monkeypatch.setattr(customer_workflow, "save_idea", refuse)
    data = {"idea": "" if refusal == "invalid-form" else "Tell buyers about the new covered parking"}
    if ticked:
        data["accounts"] = [world.linkedin.pk]
    client.force_login(world.editor)

    response = client.post(reverse("studio:create", kwargs={"workspace_id": world.workspace.id}), data)

    assert response.status_code == 400
    html = response.content.decode()
    channels = _one(_sheet(html), **{"data-testid": "new-post-team-channels"})
    assert channels.children[0].tag == "legend" and channels.children[0].text() == "Post to"
    boxes = [node for node in elements(channels) if node.tag == "input" and node.attrs.get("name") == "accounts"]
    assert [box.attrs.get("value") for box in boxes] == [
        str(account.pk) for account in studio_accounts(world.workspace)
    ]
    assert [box.attrs.get("value") for box in boxes if "checked" in box.attrs] == (
        [str(world.linkedin.pk)] if ticked else []
    )
    assert "No channels are connected yet." not in html


def test_start_a_post_is_still_absent_from_home(client, world):
    html = _page(client, world, HOME, world.owner)

    assert "Start a post" not in html


@pytest.mark.parametrize("page", PAGES, ids=["home", "calendar"])
def test_the_sheet_says_no_ai_and_no_brief(client, world, photo, page):
    photo(title="Tower at dusk")
    words = _visible_text(_sheet(_page(client, world, page, world.owner)))

    assert "Your idea" in words and "Send" in words  # the words are read, not an empty string
    assert not re.search(r"\bAI\b", words), words
    assert "brief" not in words.lower(), words


# ── One primary per view, in its place (T8's counter) ──────────────────────────────────────────


@pytest.mark.parametrize("page", PAGES, ids=["home", "calendar"])
@pytest.mark.parametrize("role", STARTERS)
def test_one_primary_per_view_in_its_place(client, world, role, page):
    html = _page(client, world, page, getattr(world, role))
    found = views(html)

    sheet_views = [view for view in found if view.name.startswith("dialog 'new-post-sheet'")]
    assert sorted(view.name.split("'")[-2] for view in sheet_views) == ["idea", "self", "team"]
    # The sheet's views have no finding, and the button is in its place at both breakpoints. (The page's
    # count, with the primaries other tasks move beside the button, is checked just below.)
    findings = [
        str(finding)
        for finding in primary_findings(html)
        if finding.view.startswith("dialog 'new-post-sheet'") or "'new-post-open': " in finding.reason
    ]
    assert not findings, findings
    for view in sheet_views:
        for breakpoint in BREAKPOINTS:
            shown = [node.name() for node in view.members if is_primary(node) and breakpoint in shown_at(node)]
            expected = ["new-post-team-send"] if view.name.endswith("'team'") else []
            assert shown == expected, (view.name, breakpoint, shown)
    page_view = found[0]
    for breakpoint in BREAKPOINTS:
        shown = [node.name() for node in page_view.members if is_primary(node) and breakpoint in shown_at(node)]
        assert [name for name in shown if name not in MOVED_LATER[page]] == ["new-post-open"], (breakpoint, shown)


def test_the_viewer_s_pages_gain_no_primary(client, world):
    for page in PAGES:
        html = _page(client, world, page, world.viewer)
        for breakpoint in BREAKPOINTS:
            shown = [
                node.name() for node in views(html)[0].members if is_primary(node) and breakpoint in shown_at(node)
            ]
            assert not [name for name in shown if name not in MOVED_LATER[page]], (page, breakpoint, shown)


# ── What it costs ───────────────────────────────────────────────────────────────────────────────


def _queries(client, world, page, monkeypatch, *, sheet: bool) -> int:
    monkeypatch.setattr(studio_views, "can_start_posts", lambda membership: sheet)
    client.force_login(world.owner)
    url = _url(world, page)
    client.get(url)  # warm the per-process caches (sessions, content types) so both counts read alike
    with CaptureQueriesContext(connection) as queries:
        response = client.get(url)
    assert response.status_code == 200
    assert ("new-post-sheet" in response.content.decode()) is sheet
    return len(queries)


def test_home_reads_nothing_more_for_the_sheet(client, world, monkeypatch):
    """Home already builds the form on every visit; the sheet renders it and reads nothing else."""
    assert _queries(client, world, HOME, monkeypatch, sheet=True) == _queries(
        client, world, HOME, monkeypatch, sheet=False
    )


def test_calendar_reads_only_what_the_form_reads(client, world, monkeypatch):
    with CaptureQueriesContext(connection) as form_reads:
        BriefForm(workspace=world.workspace)
    with_sheet = _queries(client, world, CALENDAR, monkeypatch, sheet=True)
    without = _queries(client, world, CALENDAR, monkeypatch, sheet=False)

    assert with_sheet - without == len(form_reads)


# ── The 8 px grid, ahead of the gate (T25) ──────────────────────────────────────────────────────


@pytest.mark.parametrize("name", NEW_TEMPLATES)
def test_the_new_templates_space_on_the_8px_grid(name):
    path = TEMPLATES / name
    findings = off_grid(path.read_text(encoding="utf-8"), name)
    assert not findings, "\n".join(str(finding) for finding in findings)
