"""The navigation as people see it: ``base.html`` renders ``build_nav``.

Spec D8, R1 and R2 (docs/specs/02-cut-and-merge.md), plan T9 (docs/specs/phase-2.md).

- **Desktop sidebar:** Home, Approvals (with its count), Calendar, Inbox, Analytics
  (only while a platform has analytics), Activity, then Blog only with the
  workspace's ``blog`` switch; Settings is the gear at the bottom. *More*, the
  Notifications item, Set up and Intelligence are gone from it.
- **Their old entries moved without restyling:** Drafts, Posting schedule and
  Media sit in the Calendar page's header (Queues too, with the ``queues``
  switch); Ideas and Import from CSV sit in the New menu (Templates and
  Categories too, with the ``templates`` switch).
- **Notifications** is a bell, in the sidebar's header and the phone's top bar,
  that opens the existing drawer partial. The account menu's settings link says
  *Account*, so *Settings* means one place.
- **Phone:** a bottom bar with Home, Approvals (with its count), Calendar, Inbox
  and More (which opens the drawer), with room left under the page; the post
  page has none, so nothing covers its own Approve bar.
- **Command palette:** a button and Ctrl/Cmd-K open a labelled, trapped dialog
  that filters the places this person can open: the items, Settings and the
  Settings tabs the Settings screen would show them.
- **Cost:** ``sidebar_context`` hands templates a lazy ``nav``; a page builds it
  once from the values the context already has, and an HTMX fragment never
  builds it.
"""

import re
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

import pytest
from django.test import RequestFactory, override_settings
from django.urls import resolve, reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.common import context_processors, navigation
from apps.common.features import FEATURE_KEYS
from apps.composer.models import PlatformPost, Post
from apps.credentials.models import PlatformCredential
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.notifications.engine import notify
from apps.notifications.models import EventType
from apps.organizations.models import Organization
from apps.social_accounts.models import AnalyticsPlatformConfig, SocialAccount
from apps.studio.models import AgencySettings, StudioBrief
from apps.workspaces.models import Workspace

STAFF = ("owner", "manager", "editor", "viewer")
PLACES = ["home", "approvals", "calendar", "inbox", "analytics", "activity"]
LABELS = {
    "home": "Home",
    "approvals": "Approvals",
    "calendar": "Calendar",
    "inbox": "Inbox",
    "analytics": "Analytics",
    "activity": "Activity",
    "blog": "Blog",
    "settings": "Settings",
}
PHONE = ["home", "approvals", "calendar", "inbox", "more"]


def _person(email, name):
    """A user with no organisation of their own (sign-up may make one)."""
    user = User.objects.create_user(email=email, password="pw", name=name, tos_accepted_at=timezone.now())
    own = list(OrgMembership.objects.filter(user=user).values_list("organization_id", flat=True))
    WorkspaceMembership.objects.filter(user=user).delete()
    OrgMembership.objects.filter(user=user).delete()
    Organization.objects.filter(id__in=own).delete()
    return user


@pytest.fixture
def team(db):
    """One workspace with an owner, a manager, an editor, a viewer and a plain client."""
    org = Organization.objects.create(name="Org")
    ws = Workspace.objects.create(organization=org, name="WS")
    people = {}
    for role in (*STAFF, "client"):
        user = _person(f"{role}@example.com", role.title())
        OrgMembership.objects.create(user=user, organization=org, org_role="owner" if role == "owner" else "member")
        WorkspaceMembership.objects.create(user=user, workspace=ws, workspace_role=role)
        people[role] = user
    return SimpleNamespace(org=org, ws=ws, **people)


@pytest.fixture
def analytics_on(db):
    AnalyticsPlatformConfig.objects.update(is_enabled=True)
    assert AnalyticsPlatformConfig.enabled_platforms()


@pytest.fixture
def analytics_off(db):
    AnalyticsPlatformConfig.objects.update(is_enabled=False)
    have = set(AnalyticsPlatformConfig.objects.values_list("platform", flat=True))
    AnalyticsPlatformConfig.objects.bulk_create(
        AnalyticsPlatformConfig(platform=value, is_enabled=False)
        for value, _label in PlatformCredential.Platform.choices
        if value not in have
    )
    assert AnalyticsPlatformConfig.enabled_platforms() == []


def _switches(ws, **on):
    """Every switch off but those named in *on* (the blog default would read the websites)."""
    features = {key: False for key in FEATURE_KEYS}
    features.update(on)
    AgencySettings.objects.update_or_create(workspace=ws, defaults={"features": features})


def _url(name, ws, **kwargs):
    return reverse(name, kwargs={"workspace_id": ws.id, **kwargs})


def _page(client, user, url):
    client.force_login(user)
    response = client.get(url)
    assert response.status_code == 200, (url, response.status_code)
    return response.content.decode()


def _calendar(client, team, role="owner"):
    return _page(client, getattr(team, role), _url("calendar:calendar", team.ws))


def _sidebar(html):
    return html[html.index('id="app-sidebar"') : html.index("</aside>")]


def _main_nav(html):
    sidebar = _sidebar(html)
    start = sidebar.index('aria-label="Main"')
    return sidebar[start : sidebar.index("</nav>", start)]


def _phone_bar(html):
    start = html.index('data-testid="phone-bar"')
    return html[start : html.index("</nav>", start)]


def _top_bar(html):
    start = html.index('data-testid="mobile-menu-toggle"')
    return html[start : html.index('<main id="main-content"', start)]


def _new_menu(html):
    start = html.index('data-testid="sidebar-new-toggle"')
    return html[start : html.index("<!-- Create Idea Modal -->", start)]


def _tag(html, marker):
    """The opening tag that carries *marker*."""
    at = html.index(marker)
    return html[html.rindex("<", 0, at) : html.index(">", at) + 1]


def _href(html, testid):
    return re.search(r'href="([^"]*)"', _tag(html, f'data-testid="{testid}"')).group(1)


def _items(html):
    """The sidebar's places and gear, in order, by their ``nav-<key>`` hooks."""
    return re.findall(r'data-testid="nav-([\w-]+)"', _sidebar(html))


def _labels(html):
    found = re.findall(
        r'data-testid="nav-([\w-]+)".*?<span class="sidebar-nav-label">([^<]+)</span>', _sidebar(html), re.S
    )
    return dict(found)


def _palette(html):
    return re.findall(r'data-testid="palette-item-([\w-]+)"', html)


def _pending(team, count):
    account = SocialAccount.objects.create(
        workspace=team.ws,
        platform="linkedin_company",
        account_platform_id="li-1",
        account_name="Li",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
    )
    for index in range(count):
        post = Post.objects.create(workspace=team.ws, author=team.owner, caption=f"waiting {index}")
        PlatformPost.objects.create(post=post, social_account=account, status="pending_review")


# --- the sidebar: six places and the gear ------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("role", STAFF)
def test_staff_see_six_places_then_the_gear(client, team, analytics_on, role):
    _switches(team.ws)
    html = _calendar(client, team, role)

    assert _items(html) == [*PLACES, "settings"]
    assert _labels(html) == {key: LABELS[key] for key in [*PLACES, "settings"]}
    assert _href(html, "nav-settings") == _url("settings:index", team.ws)
    assert _href(html, "nav-activity") == _url("studio:team", team.ws)
    assert _href(html, "nav-approvals") == _url("approvals:index", team.ws)


@pytest.mark.django_db
def test_blog_is_the_seventh_place_only_with_its_switch(client, team, analytics_on):
    _switches(team.ws)
    assert "blog" not in _items(_calendar(client, team))

    _switches(team.ws, blog=True)
    html = _calendar(client, team)
    assert _items(html) == [*PLACES, "blog", "settings"]
    assert _labels(html)["blog"] == "Blog"
    assert _href(html, "nav-blog") == _url("blog:list", team.ws)


@pytest.mark.django_db
def test_analytics_shows_only_while_a_platform_has_analytics(client, team, analytics_off):
    _switches(team.ws)

    assert _items(_calendar(client, team)) == ["home", "approvals", "calendar", "inbox", "activity", "settings"]


@pytest.mark.django_db
@override_settings(INTELLIGENCE_ENABLED=True)
def test_more_set_up_notifications_and_intelligence_left_the_sidebar(client, team, analytics_on):
    _switches(team.ws, queues=True, templates=True)
    html = _calendar(client, team)
    nav = _main_nav(html)

    assert "sidebar-more" not in html and "<details" not in nav and "More pages" not in html
    for gone in ("More", "Set up", "Notifications", "Intelligence", "Blog &amp; SEO"):
        assert f'<span class="sidebar-nav-label">{gone}</span>' not in html, gone
    for name in (
        "composer:create_landing",
        "composer:drafts_list",
        "calendar:queue_list",
        "calendar:posting_slots",
        "composer:template_list",
        "composer:category_list",
        "composer:csv_upload",
        "media_library:index",
        "studio:setup",
    ):
        assert f'href="{_url(name, team.ws)}"' not in nav, name
    assert f'href="{reverse("notifications:list")}"' not in nav


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("name", "query", "lit"),
    [
        pytest.param("studio:index", "", "home", id="home"),
        pytest.param("approvals:index", "", "approvals", id="approvals"),
        pytest.param("calendar:calendar", "", "calendar", id="calendar"),
        pytest.param("studio:team", "", "activity", id="activity"),
        pytest.param("settings:index", "", "settings", id="settings"),
    ],
)
def test_the_lit_place_is_marked_for_assistive_technology(client, team, analytics_on, name, query, lit):
    _switches(team.ws)
    html = _page(client, team.owner, _url(name, team.ws) + query)

    current = re.findall(r'data-testid="nav-([\w-]+)"[^>]*aria-current="page"', _sidebar(html))
    assert current == [lit]
    assert "active" in _tag(html, f'data-testid="nav-{lit}"')


@pytest.mark.django_db
def test_approvals_carries_its_count_as_today(client, team):
    _switches(team.ws)
    assert 'aria-label="Approvals"' in _tag(_calendar(client, team), 'data-testid="nav-approvals"')

    _pending(team, 2)
    html = _calendar(client, team)
    approvals = _main_nav(html).split('data-testid="nav-approvals"', 1)[1].split("</a>", 1)[0]
    assert 'aria-label="Approvals, 2 waiting"' in _tag(html, 'data-testid="nav-approvals"')
    assert '<span class="sidebar-badge is-turn">2</span>' in approvals


# --- the relocated entries ------------------------------------------------------------------


@pytest.mark.django_db
def test_the_calendar_header_links_drafts_posting_schedule_and_media(client, team):
    _switches(team.ws)
    html = _calendar(client, team)
    header = html[html.index('<h1 class="ui-page-title">Publish</h1>') : html.index('id="publish-body"')]

    for testid, name in (
        ("calendar-link-drafts", "composer:drafts_list"),
        ("calendar-link-posting-schedule", "calendar:posting_slots"),
        ("calendar-link-media", "media_library:index"),
    ):
        assert f'data-testid="{testid}"' in header, testid
        assert _href(html, testid) == _url(name, team.ws)
    assert 'data-testid="calendar-link-queues"' not in html
    assert f'href="{_url("calendar:queue_list", team.ws)}"' not in html


@pytest.mark.django_db
def test_the_calendar_header_links_queues_with_its_switch(client, team):
    _switches(team.ws, queues=True)
    html = _calendar(client, team)

    assert _href(html, "calendar-link-queues") == _url("calendar:queue_list", team.ws)


@pytest.mark.django_db
def test_the_new_menu_has_ideas_and_csv_import(client, team):
    _switches(team.ws)
    menu = _new_menu(_calendar(client, team))

    assert _href(menu, "sidebar-new-ideas") == _url("composer:create_landing", team.ws)
    assert _href(menu, "sidebar-new-csv") == _url("composer:csv_upload", team.ws)
    assert 'data-testid="sidebar-new-idea"' in menu  # the quick idea modal stays
    for hidden in ("sidebar-new-templates", "sidebar-new-categories"):
        assert f'data-testid="{hidden}"' not in menu, hidden
    for name in ("composer:template_list", "composer:category_list"):
        assert _url(name, team.ws) not in _calendar(client, team), name


@pytest.mark.django_db
def test_the_new_menu_has_templates_and_categories_with_their_switch(client, team):
    _switches(team.ws, templates=True)
    menu = _new_menu(_calendar(client, team))

    assert _href(menu, "sidebar-new-templates") == _url("composer:template_list", team.ws)
    assert _href(menu, "sidebar-new-categories") == _url("composer:category_list", team.ws)


# --- notifications: the bell -----------------------------------------------------------------


@pytest.mark.django_db
def test_the_bell_opens_the_notifications_drawer(client, team):
    _switches(team.ws)
    for index in range(3):
        notify(user=team.owner, event_type=EventType.POST_FAILED, title=f"n{index}")
    html = _calendar(client, team)

    sidebar, top = _sidebar(html), _top_bar(html)
    assert sidebar.index('data-testid="notifications-bell"') < sidebar.index('data-testid="sidebar-new-toggle"')
    assert 'data-testid="notifications-bell"' in top
    for place in (sidebar, top):
        bell = _tag(place, 'data-testid="notifications-bell"')
        assert bell.startswith("<button") and 'x-data="notificationBadge(3)"' in bell
        assert "open-notifications" in bell
        assert 'data-testid="notification-badge"' in place.split('data-testid="notifications-bell"', 1)[1]

    content = _tag(html, 'id="notification-drawer-content"')
    assert f'hx-get="{reverse("notifications:drawer")}"' in content
    drawer = _tag(html, 'data-testid="notifications-drawer"')
    for attr in ('role="dialog"', 'aria-modal="true"', 'aria-label="Notifications"', "x-trap"):
        assert attr in drawer, attr
    assert html.index('data-testid="notifications-drawer"') < html.index('id="notification-drawer-content"')


@pytest.mark.django_db
def test_the_notifications_page_and_drawer_still_answer(client, team):
    client.force_login(team.owner)

    assert client.get(reverse("notifications:list")).status_code == 200
    assert client.get(reverse("notifications:drawer"), HTTP_HX_REQUEST="true").status_code == 200


@pytest.mark.django_db
def test_the_account_menu_says_account(client, team):
    _switches(team.ws)
    html = _calendar(client, team)
    link = re.search(rf'<a href="{reverse("accounts:settings")}"[^>]*>(.*?)</a>', _sidebar(html), re.S)

    assert link is not None
    words = re.sub(r"<[^>]+>", " ", link.group(1)).split()
    assert words == ["Account"]


# --- the phone ----------------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_phone_bar_is_home_approvals_calendar_inbox_and_more(client, team, analytics_on):
    _switches(team.ws, blog=True)
    _pending(team, 2)
    html = _calendar(client, team)
    bar = _phone_bar(html)

    assert re.findall(r'data-testid="phone-bar-([\w-]+)"', bar) == PHONE
    nav = _tag(html, 'data-testid="phone-bar"')
    assert nav.startswith("<nav") and "lg:hidden" in nav and "fixed" in nav and "bottom-0" in nav
    for key in ("home", "approvals", "calendar", "inbox"):
        assert _href(bar, f"phone-bar-{key}") == _href(html, f"nav-{key}"), key
    assert 'aria-current="page"' in _tag(bar, 'data-testid="phone-bar-calendar"')
    assert 'aria-label="Approvals, 2 waiting"' in _tag(bar, 'data-testid="phone-bar-approvals"')
    more = _tag(bar, 'data-testid="phone-bar-more"')
    assert more.startswith("<button") and 'aria-controls="app-sidebar"' in more
    assert "mobileMenuOpen = true" in more


@pytest.mark.django_db
def test_the_end_of_main_leaves_room_for_the_phone_bar(client, team):
    """Room after the page's content, so its last line scrolls clear of the bar whichever element
    scrolls (the page's scroller, or main where the content runs over it, as on the calendar)."""
    _switches(team.ws)
    for url in (_url("calendar:calendar", team.ws), _url("studio:index", team.ws)):
        html = _page(client, team.owner, url)
        main = html[html.index('<main id="main-content"') : html.index("</main>")]

        room = _tag(main, "data-phone-bar-room")
        for cls in ("lg:hidden", "h-16", "flex-shrink-0"):
            assert cls in room, (url, cls)
        assert 'aria-hidden="true"' in room
        assert main.rstrip().endswith("</div>") and main.index("data-phone-bar-room") > main.index(
            'id="publish-body"' if "calendar" in url else 'data-testid="home-today"'
        )


@pytest.mark.django_db
def test_the_post_page_has_no_phone_bar_over_its_approve_bar(client, team):
    _switches(team.ws)
    brief = StudioBrief.objects.create(
        workspace=team.ws,
        author=team.owner,
        idea="A launch post",
        status=StudioBrief.Status.READY,
        proposed_publish_at=timezone.now() + timedelta(days=2),
    )
    html = _page(client, team.owner, _url("studio:detail", team.ws, brief_id=brief.id))

    assert "data-decision-bar" in html and "Approve &amp; schedule" in html
    assert 'data-testid="phone-bar' not in html and "data-phone-bar-room" not in html
    # The sidebar is unchanged there, with Home lit.
    assert re.findall(r'data-testid="nav-([\w-]+)"[^>]*aria-current="page"', _sidebar(html)) == ["home"]


@pytest.mark.django_db
@pytest.mark.parametrize("edit", [False, True], ids=["new-post", "edit-post"])
def test_the_composer_has_no_phone_bar_over_its_action_bar(client, team, edit):
    _switches(team.ws)
    url = _url("composer:compose", team.ws)
    if edit:
        post = Post.objects.create(workspace=team.ws, author=team.owner, caption="A draft")
        url = _url("composer:compose_edit", team.ws, post_id=post.id)
    html = _page(client, team.owner, url)

    assert 'data-testid="compose-save-draft"' in html
    assert 'data-testid="phone-bar' not in html and "data-phone-bar-room" not in html


# --- the command palette --------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_palette_is_a_labelled_trapped_dialog_opened_by_a_button_and_ctrl_k(client, team):
    _switches(team.ws)
    html = _calendar(client, team)

    opener = _tag(html, 'data-testid="palette-open"')
    assert opener.startswith("<button") and "aria-label=" in opener and "open-palette" in opener
    assert 'data-testid="palette-open"' in _top_bar(html)
    dialog = _tag(html, 'data-testid="palette-dialog"')
    for attr in ('role="dialog"', 'aria-modal="true"', 'aria-label="', "x-trap"):
        assert attr in dialog, attr
    assert "@keydown.escape" in dialog
    field = _tag(html, 'data-testid="palette-input"')
    assert field.startswith("<input") and "aria-label=" in field
    for key in ("ctrl.k", "meta.k"):
        assert re.search(rf"@keydown\.{re.escape(key)}[\w.]*window", html) or re.search(
            rf"@keydown\.window[\w.]*{re.escape(key)}", html
        ), key


@pytest.mark.django_db
@pytest.mark.parametrize("role", STAFF)
def test_the_palette_offers_the_places_and_the_settings_tabs_this_person_may_use(client, team, analytics_on, role):
    _switches(team.ws)
    html = _calendar(client, team, role)
    tabs = client.get(_url("settings:index", team.ws)).context["settings_tabs"]

    assert _palette(html) == [*_items(html), *[f"settings-{tab['key']}" for tab in tabs]]
    assert _href(html, "palette-item-home") == _href(html, "nav-home")
    assert _href(html, "palette-item-settings") == _url("settings:index", team.ws)
    for tab in tabs:
        assert _href(html, f"palette-item-settings-{tab['key']}") == tab["url"]


@pytest.mark.django_db
def test_the_palette_follows_the_blog_switch(client, team):
    _switches(team.ws)
    assert "blog" not in _palette(_calendar(client, team))

    _switches(team.ws, blog=True)
    assert "blog" in _palette(_calendar(client, team))


@pytest.mark.django_db
def test_a_plain_client_is_offered_no_agency_screen(client, team):
    _switches(team.ws)
    html = _calendar(client, team, "client")
    offered = _palette(html)

    assert "calendar" in offered
    for refused in ("home", "approvals", "activity", "settings"):
        assert refused not in offered, refused
    assert not [key for key in offered if key.startswith("settings-")]


# --- cost: built once, from the context's own values, never for a fragment ----------------------------


def _spy():
    return mock.patch.object(navigation, "build_nav", wraps=navigation.build_nav)


@pytest.mark.django_db
def test_the_sidebar_context_builds_the_navigation_only_when_a_template_reads_it(team):
    url = _url("calendar:calendar", team.ws)
    request = RequestFactory().get(url)
    request.user = team.owner
    request.workspace = team.ws
    request.workspace_membership = WorkspaceMembership.objects.get(user=team.owner, workspace=team.ws)
    request.org_membership = OrgMembership.objects.get(user=team.owner, organization=team.org)
    request.resolver_match = resolve(url)

    with _spy() as spy:
        context = context_processors.sidebar_context(request)
        assert spy.call_count == 0
        assert [item.key for item in context["nav"].items][:3] == ["home", "approvals", "calendar"]
        assert context["nav"].active_key == "calendar"
        assert spy.call_count == 1
    assert spy.call_args.args[1]["sidebar_pending_approvals"] == context["sidebar_pending_approvals"]


@pytest.mark.django_db
def test_a_page_builds_the_navigation_once_without_running_the_sidebar_context_again(client, team):
    _switches(team.ws)
    client.force_login(team.owner)

    with _spy() as spy:
        assert client.get(_url("calendar:calendar", team.ws)).status_code == 200

    assert spy.call_count == 1
    context = spy.call_args.args[1]
    assert context is not None and "sidebar_unread_inbox_count" in context


@pytest.mark.django_db
def test_an_htmx_fragment_never_builds_the_navigation(client, team):
    _switches(team.ws)
    client.force_login(team.owner)
    client.get(_url("calendar:calendar", team.ws))  # warm the session

    with _spy() as spy:
        response = client.get(_url("calendar:publish_tab_approvals", team.ws), HTTP_HX_REQUEST="true")
        drawer = client.get(reverse("notifications:drawer"), HTTP_HX_REQUEST="true")

    assert response.status_code == 200 and drawer.status_code == 200
    assert "app-sidebar" not in response.content.decode() and "app-sidebar" not in drawer.content.decode()
    assert spy.call_count == 0
