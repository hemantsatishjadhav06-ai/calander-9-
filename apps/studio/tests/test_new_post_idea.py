"""Save it as an idea (Phase 3, screen 1, T18).

The sheet's third view is the idea form that the shell's New idea dialog held (``base.html``; T19 took
the dialog and the New menu out of the shell): a column, a title (focused when the view shows), a
description with the emoji picker
(its 95 options rendered only while it is open), pictures uploaded through
``composer:idea_upload_media`` and sent as asset ids, and, only with the ``templates`` switch, tags and
the "Create new tag" dialog through ``composer:tag_create``. It posts to ``composer:idea_create`` and
fires ``ideaChanged`` on success. *Save it as an idea instead* (``new-post-save-idea``) in Ask the
team's decision bar reaches it; *Back to New post* (``idea-close``) returns.

The columns and tags reach ``static/js/new-post-sheet.js`` through ``json_script``, never pasted into
JavaScript, so a name with a quote or markup stays text. Home's and Calendar's views read them (only
for whoever gets the sheet, and the tags only with the switch); ``sidebar_context`` no longer reads
them on every render (``apps/common/tests/test_navigation_and_guards.py``). The browser case is T21's.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

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
from apps.composer.models import Idea, IdeaGroup, Tag
from apps.organizations.models import Organization
from apps.studio.models import AgencySettings
from apps.studio.tests.conftest import jpeg_bytes
from apps.studio.tests.test_new_post_sheet_render import (
    CALENDAR,
    HOME,
    PAGES,
    STARTERS,
    _all,
    _client_member,
    _named_from_data,
    _one,
    _page,
    _sheet,
    _url,
)
from apps.workspaces.models import Workspace

TEMPLATES = Path(__file__).resolve().parents[3] / "templates"
IDEA_TEMPLATE = "composer/partials/new_post_idea.html"
#: A column and a tag that would break out of a JavaScript string, an attribute or a script element.
AWKWARD = 'Mike\'s "launch" </script><b>bold</b>'


def _templates(world, on: bool) -> None:
    AgencySettings.objects.update_or_create(workspace=world.workspace, defaults={"features": {"templates": on}})


def _columns(world) -> list[IdeaGroup]:
    return [
        IdeaGroup.objects.create(workspace=world.workspace, name=name, position=index)
        for index, name in enumerate(("Unassigned", "To do", "In progress"))
    ]


def _idea_panel(sheet: Node) -> Node:
    return _one(sheet, **{"data-view": "idea"})


def _json(sheet: Node, element_id: str):
    found = _all(sheet, id=element_id)
    assert len(found) == 1, (element_id, len(found))
    script = found[0]
    assert script.tag == "script" and script.attrs.get("type") == "application/json"
    return json.loads(script.text())


def _in_a_template(node: Node) -> bool:
    return any(each.tag == "template" for each in node.ancestors())


# ── Reaching it ─────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("page", PAGES, ids=["home", "calendar"])
@pytest.mark.parametrize("role", STARTERS)
def test_save_it_as_an_idea_instead_sits_beside_send_and_opens_the_idea_form(client, world, role, page):
    sheet = _sheet(_page(client, world, page, getattr(world, role)))
    team = _one(sheet, **{"data-view": "team"})

    reach = _one(team, **{"data-testid": "new-post-save-idea"})
    assert reach.tag == "button" and reach.attrs.get("type") == "button"
    assert reach.text() == "Save it as an idea instead"
    assert reach.attrs.get("@click") == "setMode('idea')"
    assert not is_primary(reach)
    send = _one(team, **{"data-testid": "new-post-team-send"})
    bar = next(each for each in send.ancestors() if "data-decision-bar" in each.attrs)
    assert any(each is bar for each in reach.ancestors())


#: The idea form's hooks. tests/e2e/self/emoji-picker.spec.ts, phone-menu-focus.spec.ts and the
#: Lighthouse idea interaction (tests/lighthouse/targets.mjs) find them by test id alone, so a page has
#: one of each, the sheet's. The shell's New idea dialog that carried the same ones went with T19.
IDEA_HOOKS = (
    "idea-title",
    "idea-description",
    "idea-emoji-toggle",
    "idea-emoji-search",
    "idea-emoji-option",
    "idea-close",
)
#: What the shell's New menu and its New idea and Create new tag dialogs left on a page (T19 took them).
SHELL_IDEA_MARKERS = (
    "sidebar-new-",
    "sidebarNewMenu",
    "openCreateModal",
    'aria-label="New idea"',
    'id="sidebar-create-tag-title"',
)


@pytest.mark.parametrize("page", PAGES, ids=["home", "calendar"])
@pytest.mark.parametrize("role", STARTERS)
def test_where_the_sheet_is_the_idea_form_is_the_sheet_s_alone(client, world, role, page):
    html = _page(client, world, page, getattr(world, role))
    root = parse(html)
    sheet = _one(root, **{"data-testid": "new-post-sheet"})

    for hook in IDEA_HOOKS:
        found = _all(root, **{"data-testid": hook})
        assert len(found) == 1, (hook, len(found))
        assert any(each is sheet for each in found[0].ancestors()), hook
    # No New menu leads to a dialog of the shell's: the sheet's own button and new-post:open reach the form.
    assert 'class="idea-modal-overlay"' not in html
    for marker in SHELL_IDEA_MARKERS:
        assert marker not in html, marker


@pytest.mark.parametrize(
    ("name", "role"),
    (("approvals:index", "owner"), ("composer:create_landing", "editor"), ("calendar:calendar", "viewer")),
    ids=["approvals", "ideas", "calendar-viewer"],
)
def test_without_the_sheet_no_page_keeps_the_shell_s_new_menu_or_idea_dialog(client, world, name, role):
    """Every other place, and Calendar for someone who may not start posts: neither the sheet nor the
    shell's New menu and dialogs (the Ideas page keeps its own New idea dialog, which is not the shell's)."""
    client.force_login(getattr(world, role))
    response = client.get(reverse(name, kwargs={"workspace_id": world.workspace.id}))
    assert response.status_code == 200
    html = response.content.decode()
    root = parse(html)

    assert not _all(root, **{"data-testid": "new-post-sheet"})
    for hook in IDEA_HOOKS:
        assert not _all(root, **{"data-testid": hook}), hook
    for marker in SHELL_IDEA_MARKERS:
        assert marker not in html, marker


# ── The form ────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("page", PAGES, ids=["home", "calendar"])
def test_the_idea_form_posts_to_idea_create_with_the_old_dialog_s_fields(client, world, page):
    sheet = _sheet(_page(client, world, page, world.editor))
    panel = _idea_panel(sheet)
    kwargs = {"workspace_id": world.workspace.id}

    form = _one(panel, **{"data-testid": "new-post-idea"})
    assert form.tag == "form" and form.attrs.get("method") == "post"
    assert form.attrs.get("action") == reverse("composer:idea_create", kwargs=kwargs)
    assert form.attrs.get("enctype") == "multipart/form-data"
    assert form.attrs.get("@submit.prevent") == "saveIdea($event)"
    # Pictures go up one by one and the form sends their asset ids, never the files themselves.
    assert form.attrs.get("data-upload-url") == reverse("composer:idea_upload_media", kwargs=kwargs)
    names = {node.attrs.get("name") for node in elements(form) if node.tag in ("input", "select", "textarea")}
    assert names - {None} == {
        "csrfmiddlewaretoken",
        "group",
        "title",
        "description",
        "media_asset_ids",
        "media_asset_id",
    }
    files = [node for node in elements(form) if node.tag == "input" and node.attrs.get("type") == "file"]
    assert len(files) == 1 and "name" not in files[0].attrs and "multiple" in files[0].attrs

    title = _one(form, **{"data-testid": "idea-title"})
    assert title.tag == "input" and title.attrs.get("name") == "title"
    assert "required" in title.attrs and title.attrs.get("maxlength") == "255"
    description = _one(form, **{"data-testid": "idea-description"})
    assert description.tag == "textarea" and description.attrs.get("name") == "description"
    column = _one(form, **{"data-testid": "idea-column"})
    assert column.tag == "select" and column.attrs.get("name") == "group"
    add = _one(form, **{"data-testid": "idea-media-add"})
    assert add.tag == "button" and add.attrs.get("type") == "button" and add.text() == "Add a picture"

    # The emoji picker: a named toggle, a named search, and its 95 options only while it is open.
    toggle = _one(form, **{"data-testid": "idea-emoji-toggle"})
    assert toggle.tag == "button" and toggle.attrs.get("aria-label") == "Insert emoji"
    assert toggle.attrs.get(":aria-expanded") == "emojiPickerOpen.toString()"
    assert _one(form, **{"data-testid": "idea-emoji-search"}).attrs.get("aria-label") == "Search emoji"
    options = _all(form, **{"data-testid": "idea-emoji-option"})
    assert len(options) == 1 and _in_a_template(options[0])
    loop = next(each for each in options[0].ancestors() if each.tag == "template")
    assert loop.attrs.get("x-for") == "emoji in _filteredEmojis()"

    # The decision bar: the error line, Back to New post on the left and Save idea, the view's primary.
    save = _one(form, **{"data-testid": "idea-save"})
    assert save.tag == "button" and save.attrs.get("type") == "submit" and save.text() == "Save idea"
    assert "ui-btn-primary" in save.classes
    bar = next(each for each in save.ancestors() if "data-decision-bar" in each.attrs)
    error = _one(bar, id="new-post-idea-error")
    assert error.attrs.get("role") == "alert" and error.attrs.get("data-testid") == "new-post-idea-error"
    back = _one(bar, **{"data-testid": "idea-close"})
    assert back.tag == "button" and back.attrs.get("type") == "button"
    assert back.text() == "Back to New post" and back.attrs.get("@click") == "setMode('team')"
    assert not is_primary(back)
    # The shell audit's L1: sentence case.
    assert "Save Idea" not in sheet.text()


@pytest.mark.parametrize("page", PAGES, ids=["home", "calendar"])
def test_the_columns_and_tags_reach_the_script_as_json_in_board_order(client, world, page):
    columns = _columns(world)
    other = Workspace.objects.create(organization=Organization.objects.create(name="Elsewhere"), name="Other")
    IdeaGroup.objects.create(workspace=other, name="Someone else's column", position=0)
    Tag.objects.create(workspace=other, name="someone-else")
    for name in ("launch", "awards"):
        Tag.objects.create(workspace=world.workspace, name=name)
    _templates(world, True)

    sheet = _sheet(_page(client, world, page, world.owner))

    assert _json(sheet, "new-post-idea-columns") == [{"id": str(each.id), "label": each.name} for each in columns]
    assert _json(sheet, "new-post-idea-tags") == ["awards", "launch"]


def test_the_sheet_s_idea_form_saves_in_the_chosen_column_with_its_pictures(client, world):
    """What the form sends, under the names it renders, makes the idea where the person chose."""
    columns = _columns(world)
    sheet = _sheet(_page(client, world, HOME, world.editor))
    form = _one(_idea_panel(sheet), **{"data-testid": "new-post-idea"})
    chosen = _json(sheet, "new-post-idea-columns")[1]["id"]
    assert chosen == str(columns[1].id)

    upload = client.post(
        form.attrs["data-upload-url"],
        {"file": SimpleUploadedFile("tower.jpg", jpeg_bytes(), content_type="image/jpeg")},
    )
    assert upload.status_code == 200, upload.content
    asset_id = upload.json()["asset_id"]
    response = client.post(
        form.attrs["action"],
        {
            "group": chosen,
            "title": "Covered parking, explained",
            "description": "Three reasons buyers ask",
            "media_asset_ids": asset_id,
            "media_asset_id": asset_id,
        },
    )

    assert response.status_code == 204 and response.headers.get("HX-Trigger") == "ideaChanged"
    idea = Idea.objects.get(title="Covered parking, explained")
    assert idea.workspace == world.workspace and idea.author == world.editor
    assert idea.group_id == columns[1].id and idea.description == "Three reasons buyers ask"
    assert str(idea.media_asset_id) == asset_id
    assert [str(each) for each in idea.media_attachments.values_list("media_asset_id", flat=True)] == [asset_id]


@pytest.mark.parametrize("page", PAGES, ids=["home", "calendar"])
def test_tags_and_their_dialog_follow_the_templates_switch(client, world, page):
    Tag.objects.create(workspace=world.workspace, name="launch")
    tag_create = reverse("composer:tag_create", kwargs={"workspace_id": world.workspace.id})

    _templates(world, False)
    sheet = _sheet(_page(client, world, page, world.owner))
    panel = _idea_panel(sheet)
    assert not _all(panel, **{"data-testid": "idea-tags"})
    assert not _all(panel, **{"data-testid": "idea-tag-dialog"})
    assert not _all(panel, name="tags")
    assert not _all(sheet, id="new-post-idea-tags")
    assert "data-tag-url" not in _one(panel, **{"data-testid": "new-post-idea"}).attrs
    assert not [node.attrs for node in elements(sheet) if any(tag_create in value for value in node.attrs.values())]
    assert tag_create not in sheet.text()

    _templates(world, True)
    sheet = _sheet(_page(client, world, page, world.owner))
    panel = _idea_panel(sheet)
    form = _one(panel, **{"data-testid": "new-post-idea"})
    assert form.attrs.get("data-tag-url") == tag_create
    tags = _one(form, **{"data-testid": "idea-tags"})
    assert _one(tags, **{"data-testid": "idea-tag-search"}).attrs.get("aria-label") == "Search or create a tag"
    assert _one(form, name="tags").attrs.get("type") == "hidden"
    dialog = _one(panel, **{"data-testid": "idea-tag-dialog"})
    assert dialog.attrs.get("role") == "dialog" and dialog.attrs.get("aria-modal") == "true"
    assert any(key.startswith("x-trap") for key in dialog.attrs)
    title = _one(dialog, id=dialog.attrs.get("aria-labelledby"))
    assert title.text() == "Create new tag"
    name = _one(dialog, **{"data-testid": "idea-tag-name"})
    assert name.tag == "input" and name.attrs.get("aria-labelledby") == title.attrs["id"]
    # Escape closes this dialog only: it must not reach the sheet, whose own Escape closes everything.
    assert "@keydown.escape.stop.prevent" in dialog.attrs
    create = _one(dialog, **{"data-testid": "idea-tag-create"})
    assert create.text() == "Create" and any("data-decision-bar" in each.attrs for each in create.ancestors())
    opener = _one(tags, **{"data-testid": "idea-tag-new"})
    assert opener.text() == "Create new tag" and opener.attrs.get("aria-haspopup") == "dialog"
    # The address the form names creates the tag in this workspace.
    client.force_login(world.editor)
    created = client.post(tag_create, {"name": "awards"})
    assert created.status_code == 200 and Tag.objects.filter(workspace=world.workspace, name="awards").exists()


@pytest.mark.parametrize("page", PAGES, ids=["home", "calendar"])
def test_a_column_or_tag_named_with_a_quote_renders_safely(client, world, page):
    IdeaGroup.objects.create(workspace=world.workspace, name=AWKWARD, position=0)
    Tag.objects.create(workspace=world.workspace, name=AWKWARD[:100])
    _templates(world, True)

    html = _page(client, world, page, world.owner)
    sheet = _sheet(html)

    assert _json(sheet, "new-post-idea-columns")[0]["label"] == AWKWARD
    assert _json(sheet, "new-post-idea-tags") == [AWKWARD[:100]]
    # The name never leaves its JSON: no element it carries, no closed script, no value pasted into code.
    assert "<b>bold</b>" not in html
    assert not [node for node in elements(parse(html)) if node.tag == "b" and node.text() == "bold"]
    for node in elements(sheet):
        if node.tag == "script":
            assert node.attrs.get("type") == "application/json", node.attrs
        for key, value in node.attrs.items():
            assert "Mike" not in value, (key, value)


def test_the_tag_dialog_is_one_primary_in_its_own_bar_and_every_control_is_labelled(client, world):
    _templates(world, True)
    html = _page(client, world, HOME, world.owner)
    sheet = _sheet(html)

    tag_views = [view for view in views(html) if view.name == "dialog 'idea-tag-dialog'"]
    assert len(tag_views) == 1
    for breakpoint in BREAKPOINTS:
        shown = [node.name() for node in tag_views[0].members if is_primary(node) and breakpoint in shown_at(node)]
        assert shown == ["idea-tag-create"], (breakpoint, shown)
    assert not [str(f) for f in primary_findings(html) if f.view in ("dialog 'idea-tag-dialog'",)]
    assert not [str(f) for f in primary_findings(html) if f.view.startswith("dialog 'new-post-sheet'")]

    labels = {node.attrs.get("for") for node in elements(sheet) if node.tag == "label"}
    unlabelled = [
        node.attrs
        for node in elements(sheet)
        if node.tag in ("input", "select", "textarea")
        and node.attrs.get("type") not in ("hidden", "file")
        and not (
            any(each.tag == "label" for each in node.ancestors())
            or node.attrs.get("aria-label")
            or node.attrs.get("aria-labelledby")
            or node.attrs.get("id") in labels
        )
    ]
    assert not unlabelled
    for node in elements(sheet):
        if node.tag == "button":
            assert node.text() or node.attrs.get("aria-label") or _named_from_data(node), node.attrs


# ── Who reads the columns and tags ──────────────────────────────────────────────────────────────

IDEA_GROUP_SQL = '"composer_idea_group"'
TAG_SQL = '"composer_tag"'


def _reads(client, url, table, **headers) -> int:
    """How many queries a second visit to *url* sends to *table* (the first warms per-process caches)."""
    client.get(url, **headers)
    with CaptureQueriesContext(connection) as queries:
        response = client.get(url, **headers)
    assert response.status_code == 200
    return sum(table in query["sql"] for query in queries.captured_queries)


@pytest.mark.parametrize("page", PAGES, ids=["home", "calendar"])
def test_only_whoever_gets_the_sheet_reads_the_columns(client, world, page):
    _columns(world)
    for user, expected in ((world.owner, 1), (world.editor, 1), (world.viewer, 0)):
        client.force_login(user)
        assert _reads(client, _url(world, page), IDEA_GROUP_SQL) == expected, user


def test_home_reads_the_tags_for_the_sheet_only_with_the_switch(client, world):
    client.force_login(world.owner)
    _templates(world, False)
    assert _reads(client, _url(world, HOME), TAG_SQL) == 0
    _templates(world, True)
    assert _reads(client, _url(world, HOME), TAG_SQL) == 1
    client.force_login(world.viewer)
    assert _reads(client, _url(world, HOME), TAG_SQL) == 0


def test_calendar_hands_the_sheet_the_tags_its_filter_already_read(client, world):
    """Calendar's tag filter reads the workspace's tags for everyone; the sheet reuses that list."""
    _templates(world, True)
    client.force_login(world.viewer)
    filter_only = _reads(client, _url(world, CALENDAR), TAG_SQL)
    client.force_login(world.owner)

    assert filter_only == 1
    assert _reads(client, _url(world, CALENDAR), TAG_SQL) == filter_only


def test_a_swapped_calendar_a_plain_client_and_the_other_places_read_no_column(client, world):
    _columns(world)
    client.force_login(world.owner)

    assert (
        _reads(client, _url(world, CALENDAR) + "?mode=calendar&view=week", IDEA_GROUP_SQL, HTTP_HX_REQUEST="true") == 0
    )
    for name in ("approvals:index", "inbox:feed", "studio:team", "settings:index"):
        assert _reads(client, reverse(name, kwargs={"workspace_id": world.workspace.id}), IDEA_GROUP_SQL) == 0, name
    client.force_login(_client_member(world))
    assert _reads(client, _url(world, CALENDAR), IDEA_GROUP_SQL) == 0


# ── The 8 px grid, ahead of the gate (T25) ──────────────────────────────────────────────────────


def test_the_idea_form_spaces_on_the_8px_grid():
    findings = off_grid((TEMPLATES / IDEA_TEMPLATE).read_text(encoding="utf-8"), IDEA_TEMPLATE)
    assert not findings, "\n".join(str(finding) for finding in findings)
