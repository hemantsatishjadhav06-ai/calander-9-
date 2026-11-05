"""The navigation as people see it: ``base.html`` renders ``build_nav``.

Spec D8, R1 and R2 (docs/specs/02-cut-and-merge.md), plan T9 (docs/specs/phase-2.md).

- **Desktop sidebar:** Home, Approvals (with its count), Calendar, Inbox, Analytics
  (only while a platform has analytics), Activity, then Blog only with the
  workspace's ``blog`` switch; Settings is the gear at the bottom. *More*, the
  Notifications item, Set up and Intelligence are gone from it.
- **Their old entries moved without restyling:** Drafts, Posting schedule and
  Media sit in the Calendar page's header (Queues too, with the ``queues``
  switch); Ideas, Drafts and Import from CSV are the New post sheet's foot links
  on Home and Calendar (Templates and Categories too, with the ``templates``
  switch). The shell's New menu, which held them, is gone (Phase 3, T19): no
  template carries a ``sidebar-new-`` hook.
- **Notifications** is a bell, in the sidebar's header and the phone's top bar,
  that opens the existing drawer partial. The account menu's settings link says
  *Account*, so *Settings* means one place.
- **Phone:** a bottom bar with Home, Approvals (with its count), Calendar, Inbox
  and More (which opens the drawer), with room left under the page; the post
  page has none, so nothing covers its own Approve bar, and the Telegram page
  shows neither the bar nor its room to someone who is not on the team. What
  else floats along the bottom (toasts, selection bars, the blog form's Save
  bar) rises above the bar on phones and keeps its desktop place.
- **Command palette:** a button and Ctrl/Cmd-K open a labelled, trapped dialog
  that filters the places this person can open: the items whose pages let them
  in (their permissions, the client rule), Settings and the Settings tabs the
  Settings screen would show them. Every entry opens; every item left out refuses.
- **Cost:** ``sidebar_context`` hands templates a lazy ``nav``; a page builds it
  once from the values the context already has, and an HTMX fragment never
  builds it.
"""

import re
from datetime import timedelta
from html import unescape
from types import SimpleNamespace
from unittest import mock

import pytest
from django.conf import settings
from django.test import RequestFactory, override_settings
from django.urls import resolve, reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.blog.models import BlogSite
from apps.common import context_processors, navigation
from apps.common.features import FEATURE_KEYS
from apps.composer.models import PlatformPost, Post
from apps.credentials.models import PlatformCredential
from apps.members.models import BUILTIN_ROLE_PERMISSIONS, CustomRole, OrgMembership, WorkspaceMembership
from apps.notifications.engine import notify
from apps.notifications.models import EventType
from apps.organizations.models import Organization
from apps.social_accounts.models import AnalyticsPlatformConfig, SocialAccount
from apps.studio import views as studio_views
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
# The sidebar's places each role's own permissions refuse (BUILTIN_ROLE_PERMISSIONS):
# the inbox needs ``use_inbox``, analytics ``view_analytics``; a plain client is
# refused the agency's screens, Approvals and Settings as well.
REFUSED = {
    "owner": set(),
    "manager": set(),
    "editor": set(),
    "viewer": {"inbox"},
    "contributor": {"inbox", "analytics"},
    "client": {"home", "approvals", "inbox", "activity", "settings"},
}
# Each place's own screen, the one the sidebar links for the team.
SCREENS = {
    "home": "studio:index",
    "approvals": "approvals:index",
    "calendar": "calendar:calendar",
    "inbox": "inbox:feed",
    "analytics": "analytics:index",
    "activity": "studio:team",
    "blog": "blog:list",
    "settings": "settings:index",
}
# A plain client keeps an Approvals that works: the Calendar's approvals tab, which they could
# open before Phase 2, since the Approvals screen refuses them (they approve in the client portal).
CLIENT_APPROVALS = "?mode=list&tab=approvals"
# The places each role is not shown at all: those whose screen refuses them, but a client's Approvals.
LEFT_OUT = {**REFUSED, "client": REFUSED["client"] - {"approvals"}}


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
    """One workspace with an owner, a manager, an editor, a viewer, a contributor and a plain client."""
    org = Organization.objects.create(name="Org")
    ws = Workspace.objects.create(organization=org, name="WS")
    people = {}
    for role in (*STAFF, "contributor", "client"):
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


def _sheet(html):
    """The New post sheet, from its dialog to the end of the page (Home and Calendar)."""
    return html[html.index('data-testid="new-post-sheet"') :]


def _home(client, team, role="owner"):
    return _page(client, getattr(team, role), _url("studio:index", team.ws))


def _tag(html, marker):
    """The opening tag that carries *marker*."""
    at = html.index(marker)
    return html[html.rindex("<", 0, at) : html.index(">", at) + 1]


def _href(html, testid):
    """The address a link goes to, as the browser reads it (``&amp;`` is ``&``)."""
    return unescape(re.search(r'href="([^"]*)"', _tag(html, f'data-testid="{testid}"')).group(1))


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
    """Six places for the owner, a manager and an editor; a viewer is not shown the Inbox, which
    refuses them (``use_inbox``)."""
    _switches(team.ws)
    html = _calendar(client, team, role)
    places = [key for key in PLACES if key not in REFUSED[role]]

    assert _items(html) == [*places, "settings"]
    assert _labels(html) == {key: LABELS[key] for key in [*places, "settings"]}
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
@pytest.mark.parametrize("page", ["home", "calendar"])
def test_the_sheet_links_ideas_drafts_and_csv_import(client, team, page):
    _switches(team.ws)
    html = (_home if page == "home" else _calendar)(client, team)
    sheet = _sheet(html)

    assert _href(sheet, "new-post-link-ideas") == _url("composer:create_landing", team.ws)
    assert _href(sheet, "new-post-link-drafts") == _url("calendar:calendar", team.ws) + "?mode=list&tab=drafts"
    assert _href(sheet, "new-post-link-csv") == _url("composer:csv_upload", team.ws)
    assert 'data-testid="new-post-save-idea"' in sheet  # the quick idea is the sheet's idea form
    for hidden in ("new-post-link-templates", "new-post-link-categories"):
        assert f'data-testid="{hidden}"' not in sheet, hidden
    for name in ("composer:template_list", "composer:category_list"):
        assert _url(name, team.ws) not in html, name
    assert "sidebar-new-" not in html  # the shell's New menu is gone


@pytest.mark.django_db
@pytest.mark.parametrize("page", ["home", "calendar"])
def test_the_sheet_links_templates_and_categories_with_their_switch(client, team, page):
    _switches(team.ws, templates=True)
    sheet = _sheet((_home if page == "home" else _calendar)(client, team))

    assert _href(sheet, "new-post-link-templates") == _url("composer:template_list", team.ws)
    assert _href(sheet, "new-post-link-categories") == _url("composer:category_list", team.ws)


def test_no_template_carries_the_old_new_menu():
    """The shell's New menu left with Phase 3 T19: neither its hooks nor its classes are anywhere."""
    roots = [settings.BASE_DIR / "templates", *(settings.BASE_DIR / "apps").glob("*/templates")]
    found = [
        str(path.relative_to(settings.BASE_DIR))
        for root in roots
        for path in sorted(root.rglob("*.html"))
        if "sidebar-new-" in path.read_text(encoding="utf-8")
    ]
    assert found == []


# --- notifications: the bell -----------------------------------------------------------------


@pytest.mark.django_db
def test_the_bell_opens_the_notifications_drawer(client, team):
    _switches(team.ws)
    for index in range(3):
        notify(user=team.owner, event_type=EventType.POST_FAILED, title=f"n{index}")
    html = _calendar(client, team)

    sidebar, top = _sidebar(html), _top_bar(html)
    assert sidebar.index('data-testid="notifications-bell"') < sidebar.index('data-testid="nav-')  # the first place
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
def test_the_media_pages_folders_button_sits_above_the_phone_bar(client, team):
    """The Calendar header links Media; on a phone its floating Folders button would sit on the bar's
    Home tab (bar 56px plus the safe area, at z-20), so it rises by the bar's height plus its gap."""
    _switches(team.ws)
    html = _page(client, team.owner, _url("media_library:index", team.ws))

    assert 'data-testid="phone-bar"' in html
    toggle = _tag(html, 'data-testid="media-folders-toggle"')
    assert "fixed" in toggle and "lg:hidden" in toggle
    assert "bottom-4" not in toggle
    assert "bottom-[calc(4.5rem+env(safe-area-inset-bottom))]" in toggle


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


def _facing_client(team):
    """Someone outside the team on a custom role marked client-facing (an editor's permissions)."""
    role = CustomRole.objects.create(
        organization=team.org,
        name="External",
        permissions={**BUILTIN_ROLE_PERMISSIONS["editor"], "client_facing": True},
    )
    user = _person("facing@example.com", "Facing")
    WorkspaceMembership.objects.create(user=user, workspace=team.ws, workspace_role="editor", custom_role=role)
    return user


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("who", "shown"),
    [("owner", True), ("editor", True), ("client", False), ("client_facing", False)],
)
def test_the_telegram_page_leaves_room_for_the_phone_bar_only_where_it_shows_it(client, team, who, shown):
    """The Telegram page keeps the navigation from someone who is not on the team, phone bar included.
    The room at the end of main and the error toast's lift go with the bar, so their page does not end
    in 64px of empty space with no bar under it."""
    _switches(team.ws)
    user = _facing_client(team) if who == "client_facing" else getattr(team, who)
    html = _page(client, user, _url("telegram:settings", team.ws))

    assert ('data-testid="phone-bar"' in html) is shown, who
    assert ("data-phone-bar-room" in html) is shown, who
    toast = _tag(html, 'data-testid="error-toast"')
    assert (ABOVE_THE_BAR in toast) is shown, who


# --- floating along the bottom: clear of the phone bar on phones, unchanged on desktop ----------------

# Above the phone bar (58px: two 1px borders and its 56px items, plus the safe area) with the gap
# the media page's Folders button already keeps (base.html; media_library/library_index.html).
ABOVE_THE_BAR = "bottom-[calc(4.5rem+env(safe-area-inset-bottom))]"
# The approval toasts (approvals/partials/_toasts.html, plain CSS): the same lift below 1024px, and
# above the calendar's selection bar (56px tall on a phone) while posts are selected.
TOAST_HOST_ABOVE_THE_BAR = (
    "@media (max-width: 1023px) { #bb-toast-host { bottom: calc(4.5rem + env(safe-area-inset-bottom)); } }"
)
TOASTS_ABOVE_THE_SELECTION = "@media (max-width: 1023px) { body.has-selection #bb-toast-host { bottom: calc(9rem + env(safe-area-inset-bottom)); } }"


def _rises_on_phones(tag):
    """*tag* sits above the phone bar below 1024px and 24px from the bottom from 1024px, as before."""
    return ABOVE_THE_BAR in tag and "lg:bottom-6" in tag and "max-sm:bottom-4" not in tag


def _unchanged(tag):
    return "bottom-6 max-sm:bottom-4" in tag and ABOVE_THE_BAR not in tag


@pytest.mark.django_db
def test_the_error_toast_rises_above_the_phone_bar_where_the_bar_shows(client, team):
    _switches(team.ws)
    for url in (_url("studio:index", team.ws), _url("calendar:calendar", team.ws), _url("inbox:feed", team.ws)):
        html = _page(client, team.owner, url)
        assert 'data-testid="phone-bar"' in html, url
        assert _rises_on_phones(_tag(html, 'data-testid="error-toast"')), url


@pytest.mark.django_db
def test_without_the_phone_bar_the_error_toast_keeps_its_place(client, team):
    """The post page and the composer have their own bar instead of the phone bar."""
    _switches(team.ws)
    brief = StudioBrief.objects.create(
        workspace=team.ws,
        author=team.owner,
        idea="A launch post",
        status=StudioBrief.Status.READY,
        proposed_publish_at=timezone.now() + timedelta(days=2),
    )
    for url in (_url("studio:detail", team.ws, brief_id=brief.id), _url("composer:compose", team.ws)):
        html = _page(client, team.owner, url)
        assert 'data-testid="phone-bar"' not in html, url
        assert _unchanged(_tag(html, 'data-testid="error-toast"')), url


@pytest.mark.django_db
def test_the_calendars_selection_bar_and_toasts_rise_above_the_phone_bar(client, team):
    _switches(team.ws)
    html = _calendar(client, team)

    assert _rises_on_phones(_tag(html, 'data-testid="calendar-bulk-bar"'))
    assert TOAST_HOST_ABOVE_THE_BAR in html
    # The rule that lifts the toasts over the selection bar keeps its desktop value and gains a phone one after it.
    assert "body.has-selection #bb-toast-host { bottom: 5.5rem; }" in html
    assert html.index(TOASTS_ABOVE_THE_SELECTION) > html.index("body.has-selection #bb-toast-host { bottom: 5.5rem; }")


@pytest.mark.django_db
def test_the_approvals_selection_bar_and_toasts_rise_above_the_phone_bar(client, team):
    """The list is one partial on the Approvals screen and the calendar's Approvals tab, and the tab
    loads it as an HTMX fragment, which never builds the navigation: its bar rises on phones without
    asking whether the bar is there (both pages that show it have the phone bar)."""
    _switches(team.ws)
    _pending(team, 1)
    for url in (_url("approvals:index", team.ws), _url("calendar:calendar", team.ws) + "?mode=list&tab=approvals"):
        html = _page(client, team.owner, url)
        assert 'data-testid="phone-bar"' in html, url
        assert _rises_on_phones(_tag(html, 'data-testid="approvals-bulk-bar"')), url
        assert TOAST_HOST_ABOVE_THE_BAR in html, url

    fragment = client.get(_url("calendar:publish_tab_approvals", team.ws), HTTP_HX_REQUEST="true").content.decode()
    assert _rises_on_phones(_tag(fragment, 'data-testid="approvals-bulk-bar"'))


@pytest.mark.django_db
def test_the_approval_toasts_keep_their_place_where_there_is_no_phone_bar(client, team):
    _switches(team.ws)
    html = _page(client, team.owner, _url("composer:compose", team.ws))

    assert 'data-testid="toast-host"' in html and 'data-testid="phone-bar"' not in html
    assert TOAST_HOST_ABOVE_THE_BAR not in html


@pytest.mark.django_db
def test_the_blog_forms_save_bar_docks_on_the_phone_bar(client, team):
    """Sticky at the bottom of the page's scroller, which ends at main's 48px bottom padding on a phone:
    10px more (and the safe area) puts it flush on the 58px phone bar. From 1024px it is unchanged."""
    _switches(team.ws, blog=True)
    BlogSite.objects.create(
        workspace=team.ws,
        name="Site",
        kind=BlogSite.Kind.NEOPOLIS_STATIC,
        site_url="https://example.com",
        repo="org/site",
        workflow_file="publish.yml",
    )
    html = _page(client, team.owner, _url("blog:create", team.ws))

    assert 'data-testid="phone-bar"' in html
    actions = _tag(html, 'data-testid="blog-form-actions"')
    assert "sticky" in actions
    classes = re.search(r'class="([^"]*)"', actions).group(1).split()
    assert "bottom-[calc(0.625rem+env(safe-area-inset-bottom))]" in classes and "lg:bottom-0" in classes
    assert "bottom-0" not in classes


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
    # The palette places the focus itself (into the field, back to its opener); the trap only keeps
    # Tab inside. Left to the trap, WebKit did not land the focus in the field (CI, iPhone 13).
    assert "x-trap.noscroll.noautofocus.noreturn" in dialog
    component = html[html.index("function commandPalette(") :]
    assert "this.opener = document.activeElement" in component
    assert "this.$nextTick(() => this.placeFocus(" in component
    place = component[component.index("placeFocus(tries) {") :]
    assert "this.$refs.dialog.contains(document.activeElement)" in place and "this.$refs.input.focus()" in place
    assert "opener.focus()" in component
    # While it is open the focus stays in the dialog, with no time limit: focus that lands outside goes
    # back to the field, and so does focus that leaves for nowhere. WebKit moved it out after opening,
    # and the trap, told not to place the focus, has nowhere to send it back to (CI, iPhone 13).
    root = _tag(html, 'x-data="commandPalette(')
    assert '@focusin.window.capture="guard($event)"' in root
    assert '@focusout="lost($event)"' in dialog

    def body(name):
        start = component.index(f"{name} {{")
        return component[start : component.index("\n                },", start)]

    guard, lost, soon = body("guard(event)"), body("lost(event)"), body("refocusSoon()")
    assert "this.$refs.dialog.contains(event.target)" in guard and "this.refocusSoon()" in guard
    assert "event.relatedTarget" in lost and "this.refocusSoon()" in lost
    # Never inside the browser's own focus change: another dialog's trap, still active for a moment
    # while this one starts, would pull the focus straight back and the two would recurse until the
    # stack overflows. Once per turn, and a bounded number of times per opening.
    assert "this.$refs.input.focus()" not in guard and "this.$refs.input.focus()" not in lost
    assert "setTimeout(" in soon and "this.$refs.input.focus()" in soon
    assert "this._restores" in soon and "this._restores = 0" in component[component.index("show() {") :]
    # Enter and the arrows choose among the entries the typed words match, not among what the browser
    # has laid out: the list's links are in the entries' order.
    assert "getClientRects" not in component
    shown = component[component.index("shownLinks() {") :]
    assert "self.matches(index)" in shown
    assert "this.shownLinks()[0]" in component[component.index("openFirst() {") :]
    assert "this.shownLinks()" in component[component.index("move(step) {") :]
    for key in ("ctrl.k", "meta.k"):
        assert re.search(rf"@keydown\.{re.escape(key)}[\w.]*window", html) or re.search(
            rf"@keydown\.window[\w.]*{re.escape(key)}", html
        ), key


@pytest.mark.django_db
def test_the_sidebar_and_phone_go_to_buttons_are_one_and_the_same(client, team):
    """One component in both places, so they cannot drift: only where each shows differs (its classes),
    and both name the shortcut, which works at every width."""
    _switches(team.ws)
    html = _calendar(client, team)
    sidebar = _tag(_sidebar(html), 'data-testid="palette-open"')
    top = _tag(_top_bar(html), 'data-testid="palette-open"')

    def without_class(tag):
        return re.sub(r'\sclass="[^"]*"', "", tag)

    assert without_class(sidebar) == without_class(top)
    assert 'aria-keyshortcuts="Control+K Meta+K"' in top
    assert "hidden lg:inline-flex" in sidebar and "hidden" not in re.search(r'class="([^"]*)"', top).group(1)


@pytest.mark.django_db
@pytest.mark.parametrize("role", (*STAFF, "contributor"))
def test_the_palette_offers_the_places_and_the_settings_tabs_this_person_may_use(client, team, analytics_on, role):
    """The sidebar's places this person's permissions open (the inbox needs ``use_inbox``,
    analytics ``view_analytics``), then Settings and the tabs the Settings screen shows them."""
    _switches(team.ws)
    html = _calendar(client, team, role)
    tabs = client.get(_url("settings:index", team.ws)).context["settings_tabs"]
    places = [key for key in _items(html) if key != "settings" and key not in REFUSED[role]]

    assert _palette(html) == [*places, "settings", *[f"settings-{tab['key']}" for tab in tabs]]
    assert _href(html, "palette-item-home") == _href(html, "nav-home")
    assert _href(html, "palette-item-settings") == _url("settings:index", team.ws)
    for tab in tabs:
        assert _href(html, f"palette-item-settings-{tab['key']}") == tab["url"]


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["viewer", "contributor", "client"])
def test_the_palette_leaves_out_the_inbox_and_analytics_without_their_permission(client, team, analytics_on, role):
    _switches(team.ws)
    offered = _palette(_calendar(client, team, role))

    assert "inbox" not in offered
    assert ("analytics" in offered) is (role != "contributor")


@pytest.mark.django_db
def test_the_palette_follows_a_custom_roles_permissions_not_its_built_in_role(client, team, analytics_on):
    """A viewer given a custom role with the inbox but not analytics is offered exactly that."""
    _switches(team.ws)
    role = CustomRole.objects.create(
        organization=team.org,
        name="Inbox only",
        permissions={**BUILTIN_ROLE_PERMISSIONS["viewer"], "use_inbox": True, "view_analytics": False},
    )
    WorkspaceMembership.objects.filter(user=team.viewer, workspace=team.ws).update(custom_role=role)
    offered = _palette(_calendar(client, team, "viewer"))

    assert "inbox" in offered and "analytics" not in offered


@pytest.mark.django_db
@pytest.mark.parametrize("role", (*STAFF, "contributor", "client"))
def test_every_destination_the_palette_offers_opens_and_every_place_it_leaves_out_refuses(
    client, team, analytics_on, role
):
    _switches(team.ws, blog=True)
    html = _calendar(client, team, role)
    offered = _palette(html)

    for key in offered:
        url = _href(html, f"palette-item-{key}")
        assert client.get(url).status_code in {200, 301, 302}, (role, key, url)
    # The sidebar shows the palette's places, the gear standing for the Settings tabs, each to the same page.
    assert _items(html) == [key for key in offered if not key.startswith("settings-")]
    for key in _items(html):
        assert _href(html, f"nav-{key}") == _href(html, f"palette-item-{key}"), key
    left_out = [key for key in SCREENS if key not in offered]
    assert set(left_out) == LEFT_OUT[role]
    for key in left_out:
        url = _url(SCREENS[key], team.ws)
        assert client.get(url).status_code == 403, (role, key, url)


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
    for refused in ("home", "inbox", "activity", "settings"):
        assert refused not in offered, refused
    assert not [key for key in offered if key.startswith("settings-")]
    # Their Approvals is the Calendar's approvals tab, which lets them in; the Approvals screen does not.
    assert _href(html, "palette-item-approvals") == _url("calendar:calendar", team.ws) + CLIENT_APPROVALS
    assert client.get(_url("approvals:index", team.ws)).status_code == 403


# --- the keyboard shortcuts (spec D16, Phase 3 T20) ----------------------------------------------------
# static/js/shortcuts.js runs the keys; the list is the shell's dialog. The browser cases are
# tests/e2e/self/shortcuts.spec.ts, the guards case by case tests/js/shortcuts.test.cjs.


def _shortcuts_root(html):
    return _tag(html, "data-shortcuts")


@pytest.mark.django_db
def test_the_shortcut_list_is_a_labelled_trapped_dialog_with_a_switch(client, team):
    _switches(team.ws)
    html = _page(client, team.owner, _url("approvals:index", team.ws))

    root = _shortcuts_root(html)
    assert 'x-data="shortcutsList()"' in root and '@open-shortcuts.window="show()"' in root
    # Escape closes the list wherever the focus is, before its trap has started too (shortcuts.js).
    assert "@keydown.escape.window=" in root and "close()" in root
    dialog = _tag(html, 'data-testid="shortcuts-dialog"')
    # The list places the focus itself (x-ref close); its trap only keeps Tab inside, held on `trapped`.
    for attr in (
        'role="dialog"',
        'aria-modal="true"',
        'aria-labelledby="shortcuts-title"',
        'x-trap.noscroll.noautofocus.noreturn="trapped"',
        'x-ref="dialog"',
    ):
        assert attr in dialog, attr
    assert "@keydown.escape" in dialog
    assert 'x-ref="close"' in _tag(html, 'data-testid="shortcuts-close"')
    assert re.search(r'<h2 id="shortcuts-title"[^>]*>Keyboard shortcuts</h2>', html)

    toggle = _tag(html, 'data-testid="shortcuts-toggle"')
    assert toggle.startswith("<input") and 'type="checkbox"' in toggle and 'role="switch"' in toggle
    labelled_by = re.search(r'aria-labelledby="([^"]+)"', toggle).group(1)
    assert re.search(rf'id="{labelled_by}"[^>]*>Single-key shortcuts<', html)
    # The keys the list names, and the one that brings the list back with single keys off.
    assert 'data-testid="shortcuts-go-to"' in html and 'data-testid="shortcuts-list"' in html
    assert "<kbd" in html[html.index('data-testid="shortcuts-dialog"') :]
    # Every key has one look: base.html writes the class once, so the seven keys cannot drift apart.
    keys = re.findall(r'<kbd class="([^"]*)">', html[html.index('data-testid="shortcuts-dialog"') :])
    assert len(keys) == 7 and len(set(keys)) == 1 and "font-mono" in keys[0], keys


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("role", "starts_posts"),
    [("owner", True), ("manager", True), ("editor", True), ("contributor", True), ("viewer", False), ("client", False)],
)
def test_n_goes_to_homes_new_post_only_for_whoever_may_start_posts(client, team, role, starts_posts):
    """`n` away from the sheet goes to Home's #new-post: the page names that address only for someone
    who may start posts (``apps.studio.views.can_start_posts``), and lists `n` only for them."""
    _switches(team.ws)
    html = _calendar(client, team, role)
    root = _shortcuts_root(html)

    if starts_posts:
        assert f'data-new-post-url="{_url("studio:index", team.ws)}#new-post"' in root
        assert 'data-testid="shortcuts-new-post"' in html
    else:
        assert "data-new-post-url" not in root
        assert 'data-testid="shortcuts-new-post"' not in html


@pytest.mark.django_db
def test_go_to_does_not_open_over_the_new_post_sheet(client, team):
    """Ctrl/Cmd-K inside the sheet does nothing: Go to's open handler returns while the sheet is open
    (the sheet sets has-sheet on body), before it remembers an opener or opens."""
    _switches(team.ws)
    html = _page(client, team.owner, _url("studio:index", team.ws))
    component = html[html.index("function commandPalette(") :]
    show = component[component.index("show() {") : component.index("placeFocus(tries) {")]

    guard = show.index("document.body.classList.contains('has-sheet')")
    assert "return;" in show[guard : show.index("\n", guard)]
    assert guard < show.index("this.opener = document.activeElement") < show.index("this.open = true")


@pytest.mark.django_db
def test_who_may_start_posts_is_read_only_when_a_page_asks(team):
    """The address `n` goes to is lazy, like the navigation: a fragment that never reads it never
    looks at the membership's permissions for it."""
    url = _url("approvals:index", team.ws)
    request = RequestFactory().get(url)
    request.user = team.editor
    request.workspace = team.ws
    request.workspace_membership = WorkspaceMembership.objects.get(user=team.editor, workspace=team.ws)
    request.org_membership = OrgMembership.objects.get(user=team.editor, organization=team.org)
    request.resolver_match = resolve(url)

    with mock.patch.object(studio_views, "can_start_posts", wraps=studio_views.can_start_posts) as spy:
        context = context_processors.sidebar_context(request)
        assert spy.call_count == 0
        assert str(context["new_post_url"]) == _url("studio:index", team.ws) + "#new-post"
        assert spy.call_count == 1


# --- the sidebar and the phone bar offer only places this person may open ----------------------------


def _phone_places(html):
    """The phone bar's links (More is a button) by key, with their addresses."""
    bar = _phone_bar(html)
    keys = re.findall(r'data-testid="phone-bar-([\w-]+)"', bar)
    return {key: _href(bar, f"phone-bar-{key}") for key in keys if key != "more"}


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["viewer", "contributor", "client"])
def test_the_sidebar_and_phone_bar_link_only_places_that_let_this_person_in(client, team, analytics_on, role):
    _switches(team.ws, blog=True)
    html = _calendar(client, team, role)
    linked = {f"nav-{key}": _href(html, f"nav-{key}") for key in _items(html)}
    linked.update({f"phone-bar-{key}": url for key, url in _phone_places(html).items()})

    assert "nav-calendar" in linked and "phone-bar-calendar" in linked
    for hook, url in linked.items():
        assert client.get(url).status_code in {200, 301, 302}, (role, hook, url)


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["viewer", "contributor", "client"])
def test_the_sidebar_and_phone_bar_leave_out_exactly_the_places_that_refuse_this_person(
    client, team, analytics_on, role
):
    _switches(team.ws)
    html = _calendar(client, team, role)
    shown = [key for key in [*PLACES, "settings"] if key not in LEFT_OUT[role]]

    assert _items(html) == shown
    phone = [key for key in ("home", "approvals", "calendar", "inbox") if key in shown]
    bar = _phone_bar(html)
    assert re.findall(r'data-testid="phone-bar-([\w-]+)"', bar) == [*phone, "more"]
    # One column for each entry, as five fill the bar for the team.
    assert f"grid-cols-{len(phone) + 1}" in re.search(r'<ul class="([^"]*)"', bar).group(1).split()


@pytest.mark.django_db
def test_a_plain_clients_approvals_is_the_calendars_approvals_tab_and_has_no_gear(client, team, analytics_on):
    _switches(team.ws)
    _pending(team, 2)
    html = _calendar(client, team, "client")
    tab = _url("calendar:calendar", team.ws) + CLIENT_APPROVALS

    assert _href(html, "nav-approvals") == tab
    assert _href(_phone_bar(html), "phone-bar-approvals") == tab
    assert 'aria-label="Approvals, 2 waiting"' in _tag(html, 'data-testid="nav-approvals"')
    assert 'data-testid="nav-settings"' not in html
    # The tab lights their Approvals, as it did before Phase 2.
    lit = _page(client, team.client, tab)
    assert re.findall(r'data-testid="nav-([\w-]+)"[^>]*aria-current="page"', _sidebar(lit)) == ["approvals"]


@pytest.mark.django_db
@pytest.mark.parametrize("role", STAFF)
def test_the_team_keeps_the_gear_and_the_approvals_screen(client, team, role):
    _switches(team.ws)
    html = _calendar(client, team, role)

    assert _href(html, "nav-settings") == _url("settings:index", team.ws)
    assert _href(html, "nav-approvals") == _url("approvals:index", team.ws)


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
