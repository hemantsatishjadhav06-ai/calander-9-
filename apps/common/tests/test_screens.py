"""The screen registry and dark readiness (Phase 3, T1; docs/specs/phase-3.md, "The screen registry").

- ``apps/common/screens.py`` imports without Django, so ``tools/recolor.py`` can read it.
- Every template the registry names exists, and every page it names reverses with a workspace id;
  every declared page and every screen's page has its root templates in ``PAGE_TEMPLATES``.
- ``template_tree`` follows literal ``{% include %}`` and ``{% extends %}`` names (fixture templates),
  never a commented-out one, a variable or a template that is not the project's.
- Every page in ``PAGE_TEMPLATES``, rendered for a member who may open it, renders its listed roots,
  so the map cannot drift from the views.
- ``theme_ready`` is false for every page today (no visible change). Once a page is declared in
  ``DARK_READY``, its ``<html>`` carries ``data-theme-ready`` and other pages' do not; the client
  portal's base does the same.
- An HTMX fragment never renders an ``<html>`` tag, so the flag never lands inside a page.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.urls import resolve, reverse
from django.utils import timezone

from apps.accounts.models import User
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
