"""The screen registry and dark readiness (Phase 3, T1; docs/specs/phase-3.md, "The screen registry").

- ``apps/common/screens.py`` imports without Django, so ``tools/recolor.py`` can read it.
- Every template the registry names exists, and every page it names reverses with a workspace id;
  every declared page and every screen's page has its root templates in ``PAGE_TEMPLATES``.
- ``template_tree`` follows literal ``{% include %}`` and ``{% extends %}`` names (fixture templates),
  never a commented-out one, a variable or a template that is not the project's; it follows an
  inclusion tag's use to the template the tag renders (``inclusion_tags`` reads them from the
  templatetags modules and refuses a form it cannot read), on fixtures and on the real Calendar and
  Approvals templates.
- Every page in ``PAGE_TEMPLATES``, rendered for a member who may open it, renders its listed roots,
  so the map cannot drift from the views; rendered as an owner with posts, on its plain URL and on
  each query in ``PAGE_QUERIES`` (Calendar's list view and every list-mode tab
  ``calendar.views._TAB_TEMPLATES`` can choose), every project template it renders is inside what
  each guard that reads its roots reads (inside its own tree when none does), inclusion tags'
  templates included; and those renders do draw the selects and the status pills.
  ``RUNTIME_CHOSEN`` (templates picked through a variable include) is read by no guard, so it excuses
  them only on a page whose roots no guard reads, decided as the guards decide what to read: the page
  is not in ``DARK_READY`` (recolor reads those pages' roots and every screen's fragments) and no
  screen's ``template_tree(templates + fragments)`` holds one of its roots (the spacing and
  inline-confirm guards read a gated screen's; a screen not gated yet that reaches the roots counts
  already, so the requirement shows while it is built). A screen's ``pages`` alone impose nothing:
  screen 1's entry lists Home and Calendar and its sheet reaches neither root. On a page a guard
  reads, each must be inside what that guard reads (the reaching screen's ``fragments``; any screen's
  for a dark-ready page), or the check fails, so no guard misses a template those renders show (a
  gated Calendar screen without its four tabs in ``fragments`` fails, whatever its ``pages``).
- A gated screen lists a page and a role, so the one-primary test renders something of it.
- Home and Calendar are declared dark-ready (T22, with screen 1) and no other page is yet: Approvals
  renders Calendar's list partial but stays light until screen 3. What the two pages pick at run time
  is in their own screens' ``fragments`` (screens 2 and 4, registered for that at T22, not gated). A
  declared page's ``<html>`` carries ``data-theme-ready`` and other pages' do not; the client
  portal's base does the same.
- An HTMX fragment never renders an ``<html>`` tag, so the flag never lands inside a page.
"""

import dataclasses
import os
import subprocess
import sys
import uuid
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.urls import resolve, reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.approvals.tests.world import World
from apps.calendar import views as calendar_views
from apps.client_portal.models import MagicLinkToken
from apps.common import context_processors, screens
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace

ROOT = Path(__file__).resolve().parents[3]
HOME = ("studio", "index")
CALENDAR = ("calendar", "calendar")
APPROVALS = ("approvals", "index")


def _templates():
    """Every template name the registry holds: the pages' roots and the screens' parts."""
    names = {name for roots in screens.PAGE_TEMPLATES.values() for name in roots}
    for screen in screens.SCREENS.values():
        names.update(screen.templates)
        names.update(screen.fragments)
    return sorted(names)


def _pages():
    """Every page the registry names: declared, mapped, or one of a screen's."""
    pages = set(screens.DARK_READY) | set(screens.PAGE_TEMPLATES)
    for screen in screens.SCREENS.values():
        pages.update(screen.pages)
    return sorted(pages)


def _role_for(page):
    """A role that may open *page*: the first role of a screen that lists it, else the owner."""
    for screen in screens.SCREENS.values():
        if page in screen.pages and screen.roles:
            return screen.roles[0]
    return "owner"


def _url(page, ws):
    return reverse(f"{page[0]}:{page[1]}", kwargs={"workspace_id": ws.id})


def _html_tag(response):
    """The page's opening ``<html …>`` tag."""
    html = response.content.decode()
    start = html.index("<html")
    return html[start : html.index(">", start) + 1]


def _write(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _person(email):
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
    people = {}

    def member(role):
        if role not in people:
            user = _person(f"{role}@example.com")
            OrgMembership.objects.create(user=user, organization=org, org_role="owner" if role == "owner" else "member")
            WorkspaceMembership.objects.create(user=user, workspace=ws, workspace_role=role)
            people[role] = user
        return people[role]

    return SimpleNamespace(org=org, ws=ws, member=member)


@pytest.fixture
def world(db):
    """The Approvals tests' workspace (``apps/approvals/tests/world.py``): an owner, connected pages, ``post``."""
    return World()


# ─────────────────────────────── The registry itself ───────────────────────────────


def test_the_registry_imports_without_django():
    """recolor runs without settings, so the module may not import Django at module level."""
    env = {k: v for k, v in os.environ.items() if k != "DJANGO_SETTINGS_MODULE"}
    probe = "import sys, apps.common.screens; print(sorted(m for m in sys.modules if m.split('.')[0] == 'django'))"
    out = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]", out.stdout


def test_every_registered_template_exists():
    names = _templates()
    assert names, "the registry maps no template"
    missing = [name for name in names if screens.find_template(name) is None]
    assert not missing, f"registered templates that do not exist: {missing}"


def test_every_registered_page_reverses_with_a_workspace_id():
    workspace_id = uuid.uuid4()
    for app_name, url_name in _pages():
        path = reverse(f"{app_name}:{url_name}", kwargs={"workspace_id": workspace_id})
        match = resolve(path)
        assert (match.app_name, match.url_name) == (app_name, url_name)


def test_every_declared_and_screen_page_has_its_roots_mapped():
    """recolor finds a page's tree through PAGE_TEMPLATES, so no declared or screen page may be missing."""
    wanted = set(screens.DARK_READY)
    for screen in screens.SCREENS.values():
        wanted.update(screen.pages)
    assert wanted <= set(screens.PAGE_TEMPLATES), sorted(wanted - set(screens.PAGE_TEMPLATES))
    assert all(roots for roots in screens.PAGE_TEMPLATES.values())


def test_home_and_calendar_are_declared_dark_ready_and_no_other_page_yet():
    """Screen 1 declares the two pages its sheet lives on (T22, spec D2); every other page waits for its
    own screen's gate. Approvals renders Calendar's list partial but stays light until screen 3."""
    declared = set(screens.DARK_READY)
    assert declared == {HOME, CALENDAR}, sorted(declared)
    assert APPROVALS not in declared


#: What Home and Calendar pick at run time, through a variable ``{% include %}`` that ``template_tree``
#: cannot follow, each with where the name comes from. Both pages are declared dark-ready (T22), so a
#: guard reads them and none of this is taken on trust: each is in the ``fragments`` of its page's own
#: screen (``_guard_reads``). The tests below that put back a registry of T22's eve read it as the
#: allowlist those pages had then.
CHOSEN_ON_HOME_AND_CALENDAR: dict[str, str] = {
    "studio/partials/thread.html": "Home's thread: {% include thread.template %} (studio.chat.PANEL_TEMPLATE)",
    "calendar/partials/publish_queue.html": "list mode's tab: {% include initial_tab_template %} (calendar.views._TAB_TEMPLATES)",
    "calendar/partials/publish_drafts.html": "the same include, ?tab=drafts",
    "calendar/partials/publish_approvals.html": "the same include, ?tab=approvals",
    "calendar/partials/publish_sent.html": "the same include, ?tab=sent",
}


def test_home_and_calendar_list_what_they_pick_at_run_time_in_their_own_screens():
    """recolor reads a declared page's ``template_tree(roots)`` and every screen's ``fragments``, so the
    thread and the four list tabs are listed there: in the entries of screens 2 (Home) and 4 (Calendar),
    each holding its page's root and not gated, so no guard but recolor's reads them before their gates.
    Not in screen 1's: its tree is the sheet's, and its gate would hold them to its guards."""
    home, calendar = screens.SCREENS["home"], screens.SCREENS["calendar"]
    assert (home.templates, home.pages, home.gated) == (screens.PAGE_TEMPLATES[HOME], (HOME,), False)
    assert (calendar.templates, calendar.pages, calendar.gated) == (
        screens.PAGE_TEMPLATES[CALENDAR],
        (CALENDAR,),
        False,
    )
    assert home.fragments == ("studio/partials/thread.html",)
    assert set(calendar.fragments) == set(calendar_views._TAB_TEMPLATES.values())
    assert {*home.fragments, *calendar.fragments} == set(CHOSEN_ON_HOME_AND_CALENDAR)
    assert not set(CHOSEN_ON_HOME_AND_CALENDAR) & set(screens.SCREENS["new_post"].fragments)


#: Screen 1's parts (docs/specs/phase-3.md, T14): the sheet component and its three partials, the
#: panels T16 (Ask the team), T17 (Write it myself) and T18 (the idea form) fill.
NEW_POST_TEMPLATES = (
    "components/new_post_sheet.html",
    "studio/partials/new_post_team.html",
    "studio/partials/new_post_self.html",
    "composer/partials/new_post_idea.html",
)


def test_screen_one_is_registered_as_its_start_task_adds_it():
    """The New post sheet: its templates, on Home and Calendar, for the three roles that may start
    posts (``create_posts`` and not a plain client), not gated until its gate (T25). Its one fragment
    is the 400 answer ``studio:create`` gives the sheet (T15), which HTMX loads and the page writes
    into the sheet's error line, so the guards that read a screen's fragments read it too."""
    entry = screens.SCREENS["new_post"]

    assert entry.templates == NEW_POST_TEMPLATES
    assert entry.fragments == ("studio/partials/new_post_team_error.html",)
    assert entry.pages == (HOME, CALENDAR)
    assert entry.roles == ("owner", "manager", "editor")
    assert entry.gated is False
    assert screens.PAGE_TEMPLATES[HOME] == ("studio/index.html",)
    assert screens.PAGE_TEMPLATES[CALENDAR] == ("calendar/calendar.html",)
    # A component the two pages include (from T16): its own tree never holds their roots, so no guard
    # reads those pages through it; their own screens (2 and 4) hold what they pick at run time.
    tree = set(screens.template_tree((*entry.templates, *entry.fragments)))
    assert not tree & {*screens.PAGE_TEMPLATES[HOME], *screens.PAGE_TEMPLATES[CALENDAR]}, sorted(tree)


def test_a_screen_records_its_parts():
    screen = screens.Screen(templates=("studio/index.html",))
    assert (screen.fragments, screen.pages, screen.roles, screen.gated) == ((), (), (), False)
    for name, screen in screens.SCREENS.items():
        assert screen.templates, name
        assert set(screen.roles) <= {"owner", "manager", "editor", "viewer", "contributor", "client"}, name


def _rendered_by_nothing(registry: dict[str, screens.Screen]) -> list[str]:
    """The gated screens the one-primary test would render nothing of: no page, or no role to open one."""
    return sorted(name for name, screen in registry.items() if screen.gated and not (screen.pages and screen.roles))


def test_a_gated_screen_lists_a_page_and_a_role():
    """The one-primary test renders each page of a gated screen for each of its roles, so a gated
    screen without either would pass it having rendered nothing."""
    assert not _rendered_by_nothing(screens.SCREENS), _rendered_by_nothing(screens.SCREENS)
    calendar = screens.Screen(templates=("calendar/calendar.html",), gated=True)
    assert _rendered_by_nothing(
        {
            "no-page": dataclasses.replace(calendar, roles=("owner",)),
            "no-role": dataclasses.replace(calendar, pages=(CALENDAR,)),
            "both": dataclasses.replace(calendar, pages=(CALENDAR,), roles=("owner",)),
            "not-gated": dataclasses.replace(calendar, gated=False),
        }
    ) == ["no-page", "no-role"]


# ─────────────────────────────── template_tree ───────────────────────────────


def test_template_tree_follows_literal_includes_and_extends(tmp_path):
    _write(tmp_path, "base.html", '<html>{% include "partials/nav.html" %}{% block content %}{% endblock %}</html>')
    _write(tmp_path, "partials/nav.html", "<nav>{% include 'partials/item.html' with active=True only %}</nav>")
    _write(tmp_path, "partials/item.html", "<a>Item</a>")
    _write(
        tmp_path,
        "pages/home.html",
        '{% extends "base.html" %}\n{% block content %}\n  {% include "partials/card.html" %}\n{% endblock %}',
    )
    _write(tmp_path, "partials/card.html", '<div>{% include "partials/card.html" %}</div>')  # a cycle ends
    _write(tmp_path, "partials/unused.html", "<p>Not reached</p>")

    tree = screens.template_tree(["pages/home.html"], dirs=[tmp_path])

    assert tree[0] == "pages/home.html"
    assert set(tree) == {
        "pages/home.html",
        "base.html",
        "partials/nav.html",
        "partials/item.html",
        "partials/card.html",
    }
    assert len(tree) == len(set(tree))


def test_template_tree_skips_comments_variables_and_foreign_names(tmp_path):
    _write(tmp_path, "partials/a.html", "a")
    _write(tmp_path, "partials/b.html", "b")
    _write(
        tmp_path,
        "page.html",
        '{# {% include "partials/a.html" %} #}\n'
        '{% comment %}\n{% include "partials/b.html" %}\n{% endcomment %}\n'
        "{% include thread.template %}\n"
        '{% include "allauth/layouts/elsewhere.html" %}\n',
    )
    assert screens.template_tree(["page.html"], dirs=[tmp_path]) == ("page.html",)


def test_template_tree_reaches_base_from_a_real_page():
    tree = screens.template_tree(screens.PAGE_TEMPLATES[HOME])
    assert tree[0] == "studio/index.html"
    assert "base.html" in tree


# Every inclusion-tag form the repository's templatetags use or could use readably: a positional
# template, ``filename=`` with ``takes_context`` and a ``name=`` override, and the call form.
FIXTURE_TAGS = """\
from django import template

register = template.Library()


@register.inclusion_tag("components/badge.html")
def badge(status, label=""):
    return {"status": status}


@register.inclusion_tag(filename="components/picker.html", takes_context=True, name="pick")
def picker(context, model):
    return {"model": model}


@register.inclusion_tag("components/hidden.html")
def hidden():
    return {}


@register.simple_tag
def plain():
    return ""


def chip():
    return {}


register.inclusion_tag("components/chip.html")(chip)
"""


def test_inclusion_tags_reads_every_readable_form(tmp_path):
    _write(tmp_path, "fixture_tags.py", FIXTURE_TAGS)
    assert screens.inclusion_tags([tmp_path / "fixture_tags.py"]) == {
        "badge": "components/badge.html",
        "pick": "components/picker.html",  # the name= override, not the function's name
        "hidden": "components/hidden.html",
        "chip": "components/chip.html",
    }


def test_template_tree_follows_an_inclusion_tag_to_its_template_and_that_templates_includes(tmp_path):
    _write(tmp_path, "fixture_tags.py", FIXTURE_TAGS)
    templates = tmp_path / "templates"
    _write(
        templates,
        "page.html",
        "{% load fixture_tags %}<main>{% badge 'draft' label='Draft' %}{% pick model='x' %}{%chip%}"
        "{% plain %}{# {% hidden %} #}{% comment %}{% hidden %}{% endcomment %}</main>",
    )
    _write(templates, "components/badge.html", '{% include "components/_icon.html" %}<span>{{ status }}</span>')
    _write(templates, "components/_icon.html", "<svg></svg>")
    # A tag used inside a tag's own template is followed too.
    _write(
        templates,
        "components/picker.html",
        "{% load fixture_tags %}{% badge model %}{% include 'components/_caret.html' %}",
    )
    _write(templates, "components/_caret.html", "<i></i>")
    _write(templates, "components/chip.html", "<b>chip</b>")
    _write(templates, "components/hidden.html", "<p>Only used in a comment</p>")

    tags = screens.inclusion_tags([tmp_path / "fixture_tags.py"])
    tree = screens.template_tree(["page.html"], dirs=[templates], tags=tags)

    assert tree[0] == "page.html"
    assert set(tree) == {
        "page.html",
        "components/badge.html",
        "components/_icon.html",
        "components/picker.html",
        "components/_caret.html",
        "components/chip.html",
    }
    assert len(tree) == len(set(tree))
    # Without the tags, the same page reaches nothing: the literal includes live inside the tags' templates.
    assert screens.template_tree(["page.html"], dirs=[templates], tags={}) == ("page.html",)


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('T = "a.html"\n@register.inclusion_tag(T)\ndef a():\n    return {}\n', id="variable-template"),
        pytest.param('@register.inclusion_tag("a/" + "b.html")\ndef a():\n    return {}\n', id="computed-template"),
        pytest.param(
            '@register.inclusion_tag(filename=f"{1}.html")\ndef a():\n    return {}\n', id="f-string-template"
        ),
        pytest.param(
            'N = "a"\n@register.inclusion_tag("a.html", name=N)\ndef a():\n    return {}\n', id="variable-name"
        ),
        pytest.param('@register.inclusion_tag("a.html", None, False, "b")\ndef a():\n    return {}\n', id="positional"),
        pytest.param("@register.inclusion_tag\ndef a():\n    return {}\n", id="bare-decorator"),
        pytest.param('register.inclusion_tag("a.html")(make())\n', id="call-on-a-non-name"),
        pytest.param('tag = register.inclusion_tag("a.html")\n', id="never-applied"),
        pytest.param("@register.inclusion_tag()\ndef a():\n    return {}\n", id="no-template"),
    ],
)
def test_inclusion_tags_refuses_a_form_it_cannot_read(tmp_path, source):
    _write(tmp_path, "odd_tags.py", "from django import template\nregister = template.Library()\n" + source)
    with pytest.raises(ValueError, match=r"odd_tags\.py:\d+"):
        screens.inclusion_tags([tmp_path / "odd_tags.py"])


def test_inclusion_tags_refuses_one_name_for_two_templates(tmp_path):
    """Which one a page gets depends on its ``{% load %}`` order, so the tree cannot know."""
    head = "from django import template\nregister = template.Library()\n"
    _write(tmp_path, "a_tags.py", head + '@register.inclusion_tag("a.html")\ndef badge():\n    return {}\n')
    _write(tmp_path, "b_tags.py", head + '@register.inclusion_tag("b.html")\ndef badge():\n    return {}\n')
    with pytest.raises(ValueError, match=r"'badge'"):
        screens.inclusion_tags([tmp_path / "a_tags.py", tmp_path / "b_tags.py"])


def test_the_repositorys_inclusion_tags_are_read():
    tags = screens.inclusion_tags()
    assert tags["ui_select"] == "components/ui_select.html"
    assert tags["status_badge"] == "approvals/partials/_status_badge.html"


def test_template_tree_reaches_the_inclusion_tags_templates_from_real_pages():
    """Calendar's filters are ``{% ui_select %}`` and the approvals rows' pills ``{% status_badge %}``."""
    calendar = screens.template_tree(screens.PAGE_TEMPLATES[CALENDAR])
    assert {"components/ui_select.html", "components/_filter_icon.html"} <= set(calendar), calendar
    for root in (
        "approvals/index.html",
        "calendar/partials/publish_approvals.html",
        "calendar/partials/list_view.html",
    ):
        tree = screens.template_tree((root,))
        assert {"approvals/partials/_status_badge.html", "approvals/partials/_status_icon.html"} <= set(tree), (
            root,
            tree,
        )


# ─────────────────────────────── The map against the views ───────────────────────────────


@pytest.mark.parametrize("page", sorted(screens.PAGE_TEMPLATES), ids=lambda page: ":".join(page))
def test_every_mapped_page_renders_its_listed_roots(client, team, page):
    client.force_login(team.member(_role_for(page)))
    response = client.get(_url(page, team.ws))
    assert response.status_code == 200, response.status_code
    rendered = {template.name for template in response.templates}
    assert set(screens.PAGE_TEMPLATES[page]) <= rendered, sorted(rendered)
    # Only a declared page carries the flag (Home and Calendar, from T22).
    assert response.context["theme_ready"] is (page in screens.DARK_READY)
    assert ("data-theme-ready" in _html_tag(response)) is (page in screens.DARK_READY)


#: Templates a page picks at run time, through a variable ``{% include %}`` that ``template_tree``
#: cannot follow, each with where the name comes from. The guards never read this list, so the drift
#: check takes the choice on trust (adding each rendered one's tree) only on a page whose roots no
#: guard reads: not in ``DARK_READY``, and in no screen's ``template_tree(templates + fragments)``,
#: gated or not yet (a screen's ``pages`` do not count). Once a guard reads them, each must be inside
#: what that guard reads: the fragments of the screen whose tree holds the page's roots, and for a
#: dark-ready page the fragments of any screen, as recolor reads them (``_guard_reads``). Empty since
#: T22: Home's and Calendar's entries left when the two pages were declared
#: (``CHOSEN_ON_HOME_AND_CALENDAR``, now in their screens' fragments). A mapped page that a guard does
#: not read yet and that picks a template at run time adds its entry here.
RUNTIME_CHOSEN: dict[str, str] = {}

#: The queries a mapped page is opened with, beyond its plain URL: the ones that render its other
#: templates (Calendar's list view and its list mode, on its default tab and on every tab
#: ``calendar.views._TAB_TEMPLATES`` can choose, so a new tab is opened as soon as it exists).
PAGE_QUERIES: dict[screens.Page, tuple[dict[str, str], ...]] = {
    CALENDAR: (
        {"view": "list"},
        {"mode": "list"},
        *({"mode": "list", "tab": tab} for tab in calendar_views._TAB_TEMPLATES),
    ),
}

#: What the drift check exists to see: templates reached only through an inclusion tag, which the
#: world's posts must make the pages render (or the check would pass without looking at them).
TAG_TEMPLATES_RENDERED = ("components/ui_select.html", "approvals/partials/_status_badge.html")


def _project_templates(response):
    """The project's templates *response* rendered (its ``templates/`` directories), by load name."""
    names = set()
    for template in response.templates:
        path = Path(getattr(template.origin, "name", "") or "")
        for directory in screens.TEMPLATE_DIRS:
            if path.is_absolute() and path.is_relative_to(directory):
                names.add(path.relative_to(directory).as_posix())
                break
    return names


def _guard_reads(page: screens.Page) -> list[set[str]]:
    """What each guard that reads *page*'s roots reads with them, one set per guard (none: no guard does).

    - recolor's dark rule, when *page* is in ``DARK_READY``: ``template_tree(roots)`` and the tree of
      every screen's ``fragments`` (``tools/recolor.py``, ``dark_ready_templates``).
    - The spacing and inline-confirm guards, for each screen whose ``template_tree(templates +
      fragments)`` holds one of *page*'s roots: that tree (``test_spacing_grid.gated_templates``,
      ``test_components.gated_tree``). They read it once the screen is gated; a screen not gated yet
      that reaches the roots owns the page and counts already, so the requirement shows while it is
      built, not at its gate. A screen whose tree holds none of the roots (a component's, such as
      screen 1's sheet) reads nothing of the page, whatever its ``pages`` say.
    """
    roots = screens.PAGE_TEMPLATES[page]
    reads: list[set[str]] = []
    if page in screens.DARK_READY:
        fragments = [name for screen in screens.SCREENS.values() for name in screen.fragments]
        reads.append(set(screens.template_tree((*roots, *fragments))))
    for screen in screens.SCREENS.values():
        tree = set(screens.template_tree((*screen.templates, *screen.fragments)))
        if tree & set(roots):
            reads.append(tree)
    return reads


@pytest.fixture
def busy(client, world):
    """An owner's client on the world's workspace, with connected channels and posts in every state,
    so the filters (``{% ui_select %}``) and the status pills (``{% status_badge %}``) render."""
    for status in ("pending_review", "pending_client", "approved", "changes_requested", "rejected", "on_hold"):
        world.post(status, tags=("launch",))
    for status in ("scheduled", "published", "failed"):
        post = world.post(status, account=world.linkedin, when=timezone.now())
        post.platform_posts.update(scheduled_at=timezone.now())
    client.force_login(world.owner)
    return SimpleNamespace(client=client, workspace=world.workspace)


def _drift(
    busy: SimpleNamespace, pages: Iterable[screens.Page], allow: Mapping[str, str] | None = None
) -> tuple[dict[str, list[str]], set[str], set[str]]:
    """Render each of *pages* on its plain URL and each of its ``PAGE_QUERIES``.

    Returns ``(strays, exempted, seen)``: per page and query, the project templates rendered outside
    what a guard that reads the page's roots reads (``_guard_reads``, each such guard on its own); or,
    when no guard reads them, outside the page's own tree plus the trees of the templates in *allow*
    (default ``RUNTIME_CHOSEN``) it rendered; those exempted templates; and every project template
    rendered. A page a guard reads gets no exemption: what it picks at run time must be in what that
    guard reads (the fragments of the screen that reaches the page; every screen's fragments for recolor).
    """
    allowed = RUNTIME_CHOSEN if allow is None else allow
    strays: dict[str, list[str]] = {}
    exempted: set[str] = set()
    seen: set[str] = set()
    for page in pages:
        roots = screens.PAGE_TEMPLATES[page]
        reads = _guard_reads(page)
        for query in ({}, *PAGE_QUERIES.get(page, ())):
            response = busy.client.get(
                reverse(f"{page[0]}:{page[1]}", kwargs={"workspace_id": busy.workspace.id}), query
            )
            assert response.status_code == 200, (page, query, response.status_code)
            rendered = _project_templates(response)
            assert set(roots) <= rendered, (page, query)
            seen |= rendered
            if reads:
                unread = {name for read in reads for name in rendered - read}
            else:
                picked = rendered & set(allowed)
                exempted |= picked
                unread = rendered - set(screens.template_tree((*roots, *sorted(picked))))
            if unread:
                strays[f"{':'.join(page)} {query}"] = sorted(unread)
    return strays, exempted, seen


def test_every_template_a_mapped_page_renders_is_in_its_tree(busy):
    """What the guards read (``template_tree``) is what the page shows, inclusion tags included."""
    strays, exempted, seen = _drift(busy, sorted(screens.PAGE_TEMPLATES))

    assert not strays, f"rendered but outside template_tree, so no guard reads them: {strays}"
    # Every entry of the allowlist is still chosen at run time on a mapped page whose roots no guard
    # reads, so it cannot go stale: once a screen reaches that page or the page is declared, the entry
    # goes and the template must be in that guard's fragments instead.
    assert exempted == set(RUNTIME_CHOSEN), sorted(set(RUNTIME_CHOSEN) - exempted)
    # The world still draws the selects and the pills: fewer posts would leave them unread, not stray.
    assert set(TAG_TEMPLATES_RENDERED) <= seen, sorted(set(TAG_TEMPLATES_RENDERED) - seen)


#: The four list-mode tabs Calendar picks at run time (``{% include initial_tab_template %}``).
CALENDAR_TABS = tuple(calendar_views._TAB_TEMPLATES.values())
#: Calendar's own screen, as the guards read it: ``template_tree(templates + fragments)`` holds
#: Calendar's root, so its guards read the page whether or not it lists the page in ``pages`` (here it
#: lists none, as the spacing guard needs none). Gated, its gate having forgot the tabs; and listing them.
GATED_CALENDAR = screens.Screen(templates=("calendar/calendar.html",), gated=True)
LISTED_CALENDAR = dataclasses.replace(GATED_CALENDAR, fragments=CALENDAR_TABS)
#: Screen 1's shape as its Start task adds it (docs/specs/phase-3.md, T14): a component's templates,
#: which reach neither Home's root nor Calendar's, both pages in ``pages``, not gated yet. Its
#: templates stand in for the sheet's (stubs until T16-T18) with components that do render templates
#: of their own, so the tree it is checked against is not empty; the real entry's one fragment (the
#: sheet's error answer) reaches no page root either.
NEW_POST = screens.Screen(
    templates=("components/ui_select.html", "approvals/partials/_status_badge.html"),
    pages=(HOME, CALENDAR),
    roles=("owner", "manager", "editor"),
)


def _unread(strays: dict[str, list[str]]) -> set[str]:
    return {name for names in strays.values() for name in names}


@pytest.mark.parametrize("gated", [True, False], ids=["gated", "before-its-gate"])
def test_a_screen_that_reaches_a_pages_roots_must_list_its_run_time_templates(busy, monkeypatch, gated):
    """A gated Calendar screen without its tabs in ``fragments`` fails the drift check, as does the
    same screen before its gate (it owns the page, so the requirement shows while it is built): the
    spacing guard reads its ``template_tree(templates + fragments)``, which holds Calendar's root and
    none of the four tabs, so the tabs would render off-grid spacing unread."""
    monkeypatch.setattr(screens, "DARK_READY", frozenset())
    forgot = dataclasses.replace(GATED_CALENDAR, gated=gated)
    monkeypatch.setattr(screens, "SCREENS", {"calendar": forgot})
    read = set(screens.template_tree((*forgot.templates, *forgot.fragments)))
    assert "calendar/calendar.html" in read and not read & set(CALENDAR_TABS), sorted(read)

    strays, exempted, _ = _drift(busy, [CALENDAR])

    assert set(CALENDAR_TABS) <= _unread(strays), f"the tabs were taken on trust on a page a guard reads: {strays}"
    assert not exempted, sorted(exempted)


@pytest.mark.parametrize("gated", [True, False], ids=["gated", "before-its-gate"])
def test_a_screen_that_reaches_a_pages_roots_and_lists_its_run_time_templates_passes(busy, monkeypatch, gated):
    """The same screen with the four tabs in ``fragments``: no stray, nothing taken on trust, and the
    guards' own tree holds every tab."""
    monkeypatch.setattr(screens, "DARK_READY", frozenset())
    listed = dataclasses.replace(LISTED_CALENDAR, gated=gated)
    monkeypatch.setattr(screens, "SCREENS", {"calendar": listed})

    strays, exempted, _ = _drift(busy, [CALENDAR])

    assert not strays, strays
    assert not exempted, sorted(exempted)
    assert set(CALENDAR_TABS) <= set(screens.template_tree((*listed.templates, *listed.fragments)))


@pytest.mark.parametrize("gated", [False, True], ids=["at-its-start", "at-its-gate"])
def test_a_screen_that_does_not_reach_its_pages_roots_imposes_nothing_on_them(busy, monkeypatch, gated):
    """Screen 1's entry lists Home and Calendar in ``pages`` but its templates (a component's) reach
    neither page's root, so no guard reads those pages through it: with neither page declared (the
    registry of T22's eve), Home's thread and Calendar's tabs stay on that day's allowlist, and nothing
    asks for them in screen 1's ``fragments``."""
    monkeypatch.setattr(screens, "DARK_READY", frozenset())
    entry = dataclasses.replace(NEW_POST, gated=gated)
    monkeypatch.setattr(screens, "SCREENS", {"new_post": entry})
    read = set(screens.template_tree((*entry.templates, *entry.fragments)))
    assert not read & {*screens.PAGE_TEMPLATES[HOME], *screens.PAGE_TEMPLATES[CALENDAR]}, sorted(read)

    strays, exempted, _ = _drift(busy, [HOME, CALENDAR], allow=CHOSEN_ON_HOME_AND_CALENDAR)

    assert not strays, f"a screen that does not reach these pages' roots was made to read their templates: {strays}"
    assert exempted == set(CHOSEN_ON_HOME_AND_CALENDAR), sorted(set(CHOSEN_ON_HOME_AND_CALENDAR) ^ exempted)


@pytest.mark.parametrize(
    "registry",
    [
        pytest.param({}, id="no-screen"),
        pytest.param({"new_post": NEW_POST}, id="a-screen-listing-the-page-without-the-tabs"),
    ],
)
def test_a_dark_ready_pages_run_time_templates_must_be_in_a_screens_fragments(busy, monkeypatch, registry):
    """recolor reads a dark-ready page's ``template_tree(roots)`` and every screen's fragments, so a
    dark-ready Calendar whose tabs are in no screen's ``fragments`` fails."""
    monkeypatch.setattr(screens, "DARK_READY", frozenset({CALENDAR}))
    monkeypatch.setattr(screens, "SCREENS", registry)

    strays, exempted, _ = _drift(busy, [CALENDAR])

    assert set(CALENDAR_TABS) <= _unread(strays), f"the tabs were taken on trust on a page a guard reads: {strays}"
    assert not exempted, sorted(exempted)


def test_a_dark_ready_page_reads_its_run_time_templates_in_every_screens_fragments(busy, monkeypatch):
    """As recolor does: the tabs in the fragments of a screen that neither reaches nor lists Calendar
    still cover the dark-ready Calendar."""
    monkeypatch.setattr(screens, "DARK_READY", frozenset({CALENDAR}))
    elsewhere = dataclasses.replace(NEW_POST, pages=(HOME,), fragments=CALENDAR_TABS)
    monkeypatch.setattr(screens, "SCREENS", {"elsewhere": elsewhere})
    assert "calendar/calendar.html" not in screens.template_tree((*elsewhere.templates, *elsewhere.fragments))

    strays, exempted, _ = _drift(busy, [CALENDAR])

    assert not strays, strays
    assert not exempted, sorted(exempted)


# ─────────────────────────────── The readiness flag ───────────────────────────────


def test_theme_context_reads_the_resolved_page_without_a_query(db, rf, monkeypatch, django_assert_num_queries):
    monkeypatch.setattr(screens, "DARK_READY", frozenset({HOME}))
    workspace_id = uuid.uuid4()
    home = rf.get(f"/workspace/{workspace_id}/studio/")
    home.resolver_match = resolve(home.path)
    calendar = rf.get(f"/workspace/{workspace_id}/calendar/")
    calendar.resolver_match = resolve(calendar.path)
    unresolved = rf.get("/nowhere/")
    with django_assert_num_queries(0):
        assert context_processors.theme_context(home) == {"theme_ready": True}
        assert context_processors.theme_context(calendar) == {"theme_ready": False}
        assert context_processors.theme_context(unresolved) == {"theme_ready": False}


def test_a_declared_page_carries_the_flag_and_others_do_not(client, team, monkeypatch):
    monkeypatch.setattr(screens, "DARK_READY", frozenset({HOME}))
    client.force_login(team.member("owner"))

    home = client.get(_url(HOME, team.ws))
    calendar = client.get(_url(CALENDAR, team.ws))

    assert home.status_code == calendar.status_code == 200
    assert home.context["theme_ready"] is True
    assert " data-theme-ready" in _html_tag(home)
    assert calendar.context["theme_ready"] is False
    assert "data-theme-ready" not in _html_tag(calendar)


def test_the_portal_base_carries_the_flag_when_its_page_is_declared(client, team, monkeypatch):
    user = team.member("client")
    token = MagicLinkToken.objects.create(user=user, workspace=team.ws)
    entry = client.post(reverse("client_portal:magic_link_entry", kwargs={"token": token.token}))
    assert entry.status_code == 302
    url = reverse("client_portal:dashboard")

    plain = client.get(url)
    assert plain.status_code == 200
    assert "data-theme-ready" not in _html_tag(plain)

    monkeypatch.setattr(screens, "DARK_READY", frozenset({("client_portal", "dashboard")}))
    declared = client.get(url)
    assert declared.status_code == 200
    assert " data-theme-ready" in _html_tag(declared)


# ─────────────────────────────── Fragments ───────────────────────────────

# What Home and Calendar load with HTMX: the mode switch, a sub-view, and Home's "Right now" strip.
FRAGMENTS: tuple[tuple[str, dict[str, str]], ...] = (
    ("calendar:calendar", {"mode": "list", "_switch_mode": "1"}),
    ("calendar:calendar", {"mode": "calendar", "_switch_mode": "1"}),
    ("calendar:calendar", {"mode": "calendar", "view": "month"}),
    ("calendar:calendar", {"mode": "calendar", "view": "week"}),
    ("studio:team_board", {"part": "strip"}),
    ("studio:team_board", {}),
)


def test_an_htmx_fragment_never_renders_an_html_tag(client, team, monkeypatch):
    # Every page declared, so a fragment that carried an <html> tag would carry the flag too.
    declared = set(screens.PAGE_TEMPLATES) | {tuple(name.split(":")) for name, _ in FRAGMENTS}
    monkeypatch.setattr(screens, "DARK_READY", frozenset(declared))
    client.force_login(team.member("owner"))
    for name, params in FRAGMENTS:
        response = client.get(reverse(name, kwargs={"workspace_id": team.ws.id}), params, HTTP_HX_REQUEST="true")
        assert response.status_code == 200, (name, params, response.status_code)
        html = response.content.decode().lower()
        assert "<html" not in html, (name, params)
        assert "data-theme-ready" not in html, (name, params)


def test_no_screen_fragment_template_holds_an_html_tag():
    for name, screen in screens.SCREENS.items():
        for template in screens.template_tree(screen.fragments):
            path = screens.find_template(template)
            assert path is not None, (name, template)
            assert "<html" not in path.read_text(encoding="utf-8").lower(), (name, template)
