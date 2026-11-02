"""Write it myself and the Calendar cells (Phase 3, screen 1, T17).

The sheet's *Write it myself* panel is one sentence and **Open the editor**, a link to
``composer:compose`` (its ``href``, so the editor is reached without JavaScript). The sheet's
``editorUrl`` adds the date, time and account it was opened with (``static/js/new-post-sheet.js``,
``tests/js/new_post_sheet.test.cjs``). With the ``templates`` switch the panel also offers
*Start from a template* (``composer:create_landing?tab=templates``).

Each "+" in Calendar's month, week and day grids keeps its ``href`` (the composer with the cell's date
and time, and the slot's account) and, where the sheet is on the page, opens it in *Write it myself*
with the same values (``new-post:open``, ``aria-haspopup="dialog"``). A swapped grid lands on the page
that holds the sheet, so it does the same. Without the sheet (a viewer, a plain client) the "+" stays the
plain link it was. Touch and keyboard reach for the cells is screen 4's; the browser case is T21's.
"""

from __future__ import annotations

import re
import zoneinfo
from datetime import datetime, time, timedelta
from pathlib import Path
from urllib.parse import parse_qsl

import pytest
from django.urls import reverse

from apps.calendar.models import PostingSlot
from apps.common.tests.test_one_primary import elements, parse
from apps.common.tests.test_spacing_grid import off_grid
from apps.studio.models import AgencySettings
from apps.studio.tests.test_new_post_sheet_render import (
    CALENDAR,
    PAGES,
    STARTERS,
    _all,
    _client_member,
    _one,
    _page,
    _sheet,
    _url,
)

TEMPLATES = Path(__file__).resolve().parents[3] / "templates"
SENTENCE = "Write the post yourself in the editor: words, pictures, channels and a time."
CELL_LINKS = frozenset({"cal-add-btn", "calendar-slot-add"})
#: The "+" opens the sheet in Write it myself with the cell's values, as JavaScript string literals.
DISPATCH_RE = re.compile(
    r"\$dispatch\('new-post:open', \{mode: 'self', date: '(?P<date>[^'\\]*)', "
    r"time: '(?P<time>[^'\\]*)', account: '(?P<account>[^'\\]*)'\}\)"
)
#: Today's hrefs (unchanged by T17): the cell's date and time, and a channel slot's account first.
HREF_RE = re.compile(
    r"^(?P<path>[^?]+)\?(?:account=(?P<account>[0-9a-f-]{36})&)?"
    r"scheduled_date=(?P<date>\d{4}-\d{2}-\d{2})&scheduled_time=(?P<time>\d{2}:\d{2})$"
)
VIEWS = ("month", "week", "day")


def _compose(world) -> str:
    return reverse("composer:compose", kwargs={"workspace_id": world.workspace.id})


def _self_panel(client, world, page, user=None):
    return _one(_sheet(_page(client, world, page, user or world.owner)), **{"data-view": "self"})


# ── Write it myself ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("page", PAGES, ids=["home", "calendar"])
@pytest.mark.parametrize("role", STARTERS)
def test_write_it_myself_is_one_sentence_and_open_the_editor(client, world, role, page):
    panel = _self_panel(client, world, page, getattr(world, role))
    compose = _compose(world)

    link = _one(panel, **{"data-testid": "new-post-self-open"})
    assert link.tag == "a" and link.text() == "Open the editor"
    # Without JavaScript it is the editor itself; the sheet builds the rest on the same base.
    assert link.attrs.get("href") == compose
    assert link.attrs.get(":href") == f"editorUrl('{compose}')"
    # The view's one act, in its decision bar (the panel is its own view for the one-primary counter).
    assert "ui-btn-primary" in link.classes
    assert any("data-decision-bar" in each.attrs for each in link.ancestors())
    # One sentence, then the button: nothing else is said.
    assert panel.text() == f"{SENTENCE} Open the editor"


@pytest.mark.parametrize("page", PAGES, ids=["home", "calendar"])
def test_start_from_a_template_follows_the_templates_switch(client, world, page):
    panel = _self_panel(client, world, page)
    assert not _all(panel, **{"data-testid": "new-post-self-template"})
    assert "Start from a template" not in panel.text()

    AgencySettings.objects.update_or_create(workspace=world.workspace, defaults={"features": {"templates": True}})
    panel = _self_panel(client, world, page)
    link = _one(panel, **{"data-testid": "new-post-self-template"})
    landing = reverse("composer:create_landing", kwargs={"workspace_id": world.workspace.id})
    assert link.tag == "a" and link.text() == "Start from a template"
    assert link.attrs.get("href") == f"{landing}?tab=templates"
    assert "ui-btn-primary" not in link.classes
    assert not any("data-decision-bar" in each.attrs for each in link.ancestors())


def test_the_panel_spaces_on_the_8px_grid():
    name = "studio/partials/new_post_self.html"
    findings = off_grid((TEMPLATES / name).read_text(encoding="utf-8"), name)
    assert not findings, "\n".join(str(finding) for finding in findings)


# ── The Calendar cells ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def ahead(world):
    """A day two weeks ahead in the workspace's zone (every "+" of its month, week and day shows), with
    a LinkedIn posting slot at 10:00 so week and day also show a channel slot's "+"."""
    day = datetime.now(zoneinfo.ZoneInfo(world.workspace.effective_timezone)).date() + timedelta(days=14)
    PostingSlot.objects.create(social_account=world.linkedin, day_of_week=day.weekday(), time=time(10, 0))
    return day


def _grid(client, world, user, view, day, *, htmx=False):
    client.force_login(user)
    headers = {"HTTP_HX_REQUEST": "true"} if htmx else {}
    response = client.get(_url(world, CALENDAR) + f"?mode=calendar&view={view}&date={day.isoformat()}", **headers)
    assert response.status_code == 200
    return response.content.decode()


def _cell_links(html):
    return [node for node in elements(parse(html)) if node.tag == "a" and node.classes & CELL_LINKS]


def _expected_hrefs(world, view, day) -> set[str]:
    """The "+" a test can name exactly: the day at 09:00 (month), its 10:00 cell (week, day) and the
    LinkedIn slot at 10:00 (week, day)."""
    compose = _compose(world)
    if view == "month":
        return {f"{compose}?scheduled_date={day}&scheduled_time=09:00"}
    return {
        f"{compose}?scheduled_date={day}&scheduled_time=10:00",
        f"{compose}?account={world.linkedin.pk}&scheduled_date={day}&scheduled_time=10:00",
    }


@pytest.mark.parametrize("htmx", [False, True], ids=["page", "swapped-grid"])
@pytest.mark.parametrize("view", VIEWS)
@pytest.mark.parametrize("role", STARTERS)
def test_each_plus_keeps_its_link_and_opens_write_it_myself_with_the_same_values(
    client, world, ahead, role, view, htmx
):
    links = _cell_links(_grid(client, world, getattr(world, role), view, ahead, htmx=htmx))
    hrefs = [link.attrs.get("href", "") for link in links]

    assert _expected_hrefs(world, view, ahead) <= set(hrefs)
    if view != "month":
        assert any("calendar-slot-add" in link.classes for link in links)
    for link in links:
        href = HREF_RE.match(link.attrs.get("href", ""))
        assert href and href["path"] == _compose(world), link.attrs
        event = DISPATCH_RE.fullmatch(link.attrs.get("@click.prevent", ""))
        assert event, link.attrs
        assert (event["date"], event["time"], event["account"]) == (
            href["date"],
            href["time"],
            href["account"] or "",
        )
        assert dict(parse_qsl(link.attrs["href"].split("?", 1)[1])) == {
            key: value
            for key, value in (
                ("account", event["account"]),
                ("scheduled_date", event["date"]),
                ("scheduled_time", event["time"]),
            )
            if value
        }
        assert link.attrs.get("aria-haspopup") == "dialog"


@pytest.mark.parametrize("view", VIEWS)
@pytest.mark.parametrize("who", ["viewer", "client"])
def test_without_the_sheet_each_plus_is_the_plain_link_it_was(client, world, ahead, view, who):
    user = world.viewer if who == "viewer" else _client_member(world)
    html = _grid(client, world, user, view, ahead)
    links = _cell_links(html)

    assert "new-post-sheet" not in html
    assert _expected_hrefs(world, view, ahead) <= {link.attrs.get("href") for link in links}
    for link in links:
        assert HREF_RE.match(link.attrs.get("href", "")), link.attrs
        assert "@click.prevent" not in link.attrs and "aria-haspopup" not in link.attrs, link.attrs
