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
  ``calendar.views._TAB_TEMPLATES`` can choose), every project template it renders is inside its tree
  plus its screens' fragments; and those renders do draw the selects and the status pills.
  ``RUNTIME_CHOSEN`` (templates picked through a variable include) is read by no guard: it excuses
  them only on a page no guard reads yet (in no screen's ``pages``, not in ``DARK_READY``). On a
  page a guard reads, each must be in its screen's ``fragments``, or the check fails, so no guard
  misses a template those renders show (a gated Calendar without its four tabs listed fails).
- ``theme_ready`` is false for every page today (no visible change). Once a page is declared in
  ``DARK_READY``, its ``<html>`` carries ``data-theme-ready`` and other pages' do not; the client
  portal's base does the same.
- An HTMX fragment never renders an ``<html>`` tag, so the flag never lands inside a page.
"""

import dataclasses
import os
import subprocess
import sys
import uuid
from collections.abc import Iterable
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


def test_no_page_is_declared_dark_ready_yet():
    """Each screen's gate declares its own pages (Home and Calendar first, at T22); until then none is."""
    assert not screens.DARK_READY, sorted(screens.DARK_READY)


def test_a_screen_records_its_parts():
    screen = screens.Screen(templates=("studio/index.html",))
    assert (screen.fragments, screen.pages, screen.roles, screen.gated) == ((), (), (), False)
    for name, screen in screens.SCREENS.items():
        assert screen.templates, name
        assert set(screen.roles) <= {"owner", "manager", "editor", "viewer", "contributor", "client"}, name


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
    # Nothing changes until a page is declared: today no page is, so no <html> carries the flag.
    assert response.context["theme_ready"] is (page in screens.DARK_READY)
    assert ("data-theme-ready" in _html_tag(response)) is (page in screens.DARK_READY)


#: Templates a page picks at run time, through a variable ``{% include %}`` that ``template_tree``
#: cannot follow, each with where the name comes from. The guards never read this list: no guard reads
#: these templates until the screen's gate lists them in its ``fragments``. So the drift check takes
#: the choice on trust (adding each rendered one's tree) only on a page no guard reads yet, one no
#: screen lists in ``pages`` and not in ``DARK_READY``; on any other page each must be in the tree of
#: its screen's ``fragments``, as the registry's rule says.
RUNTIME_CHOSEN: dict[str, str] = {
    "studio/partials/thread.html": "Home's thread: {% include thread.template %} (studio.chat.PANEL_TEMPLATE)",
    "calendar/partials/publish_queue.html": "list mode's tab: {% include initial_tab_template %} (calendar.views._TAB_TEMPLATES)",
    "calendar/partials/publish_drafts.html": "the same include, ?tab=drafts",
    "calendar/partials/publish_approvals.html": "the same include, ?tab=approvals",
    "calendar/partials/publish_sent.html": "the same include, ?tab=sent",
}

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


def _fragments_of(page):
    return tuple(name for screen in screens.SCREENS.values() if page in screen.pages for name in screen.fragments)


def _read_by_a_guard(page):
    """Whether *page* is a guard's: a screen lists it in ``pages``, or it is declared dark-ready."""
    return page in screens.DARK_READY or any(page in screen.pages for screen in screens.SCREENS.values())


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


def _drift(busy: SimpleNamespace, pages: Iterable[screens.Page]) -> tuple[dict[str, list[str]], set[str], set[str]]:
    """Render each of *pages* on its plain URL and each of its ``PAGE_QUERIES``.

    Returns ``(strays, exempted, seen)``: per page and query, the project templates rendered outside
    the page's tree (its roots and its screens' fragments, plus the trees of the ``RUNTIME_CHOSEN``
    templates it rendered while no guard reads it); those exempted templates; and every project
    template rendered. A page a guard reads gets no exemption (``_read_by_a_guard``): what it picks at
    run time must be in its screens' ``fragments``, the only place the guards look for it.
    """
    strays: dict[str, list[str]] = {}
    exempted: set[str] = set()
    seen: set[str] = set()
    for page in pages:
        for query in ({}, *PAGE_QUERIES.get(page, ())):
            response = busy.client.get(
                reverse(f"{page[0]}:{page[1]}", kwargs={"workspace_id": busy.workspace.id}), query
            )
            assert response.status_code == 200, (page, query, response.status_code)
            rendered = _project_templates(response)
            assert set(screens.PAGE_TEMPLATES[page]) <= rendered, (page, query)
            seen |= rendered
            picked = set() if _read_by_a_guard(page) else rendered & set(RUNTIME_CHOSEN)
            exempted |= picked
            tree = set(screens.template_tree((*screens.PAGE_TEMPLATES[page], *_fragments_of(page), *sorted(picked))))
            if rendered - tree:
                strays[f"{':'.join(page)} {query}"] = sorted(rendered - tree)
    return strays, exempted, seen


def test_every_template_a_mapped_page_renders_is_in_its_tree(busy):
    """What the guards read (``template_tree``) is what the page shows, inclusion tags included."""
    strays, exempted, seen = _drift(busy, sorted(screens.PAGE_TEMPLATES))

    assert not strays, f"rendered but outside template_tree, so no guard reads them: {strays}"
    # Every entry of the allowlist is still chosen at run time on a mapped page no guard reads, so it
    # cannot go stale: once a gate lists an entry in its screen's fragments, the entry goes.
    assert exempted == set(RUNTIME_CHOSEN), sorted(set(RUNTIME_CHOSEN) - exempted)
    # The world still draws the selects and the pills: fewer posts would leave them unread, not stray.
    assert set(TAG_TEMPLATES_RENDERED) <= seen, sorted(set(TAG_TEMPLATES_RENDERED) - seen)


#: The four list-mode tabs Calendar picks at run time (``{% include initial_tab_template %}``).
CALENDAR_TABS = tuple(calendar_views._TAB_TEMPLATES.values())
#: Calendar as a gated screen whose gate forgot its run-time templates, and as one that lists them.
GATED_CALENDAR = screens.Screen(templates=("calendar/calendar.html",), pages=(CALENDAR,), gated=True)
LISTED_CALENDAR = dataclasses.replace(GATED_CALENDAR, fragments=CALENDAR_TABS)


@pytest.mark.parametrize(
    ("dark_ready", "registry"),
    [
        pytest.param(frozenset(), {"calendar": GATED_CALENDAR}, id="gated-screen-without-fragments"),
        pytest.param(frozenset({CALENDAR}), {}, id="dark-ready-page-without-a-screen"),
    ],
)
def test_a_guarded_pages_run_time_templates_must_be_in_its_screens_fragments(busy, monkeypatch, dark_ready, registry):
    """The allowlist covers only a page no guard reads yet. The guards read a gated screen's
    ``template_tree(templates + fragments)`` and a dark-ready page's ``template_tree(roots)`` plus
    the screens' fragments, never ``RUNTIME_CHOSEN``; so once a screen lists the page or the page is
    declared, a template it picks at run time must be in its screen's ``fragments``: otherwise a
    gated Calendar passes the grid guard while its four tabs render off-grid spacing unread.
    """
    monkeypatch.setattr(screens, "DARK_READY", dark_ready)
    monkeypatch.setattr(screens, "SCREENS", registry)
    strays, exempted, _ = _drift(busy, [CALENDAR])
    unread = {name for names in strays.values() for name in names}
    assert set(CALENDAR_TABS) <= unread, f"the tabs were taken on trust on a page a guard reads: {strays}"
    assert not exempted, sorted(exempted)

    # The screen that lists them in its fragments: no stray, and the guards' own tree holds every tab.
    monkeypatch.setattr(screens, "SCREENS", {"calendar": LISTED_CALENDAR})
    strays, exempted, _ = _drift(busy, [CALENDAR])
    assert not strays, strays
    assert not exempted, sorted(exempted)
    assert set(CALENDAR_TABS) <= set(screens.template_tree((*LISTED_CALENDAR.templates, *LISTED_CALENDAR.fragments)))


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
