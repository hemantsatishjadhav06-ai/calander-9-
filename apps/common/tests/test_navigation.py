"""``build_nav``: the six places, the gear and the phone bar for one request.

Spec R1 (docs/specs/02-cut-and-merge.md), plan T2 (docs/specs/phase-2.md).

- The items come in one order: Home, Approvals, Calendar, Inbox, Analytics
  (only while a platform has analytics), Activity, then Blog (only with the
  workspace's ``blog`` switch). Settings is the gear, apart from the items.
- The phone bar is Home, Approvals (with its count), Calendar, Inbox and More.
- Exactly one place is lit, from the resolved URL: Home on the agency's own
  pages, Activity on the team, job and routine pages, Settings on every page a
  setting lives on today, Approvals on the approvals list, Calendar on the rest
  of the calendar, and Inbox, Analytics and Blog on their apps.
- Approvals and Settings point at their new screens once those routes exist,
  and at today's pages until then. Activity is ``studio:team``, whose path is
  ``/studio/activity/`` (spec D4).
- The counts are the ones ``sidebar_context`` already computed: building the
  navigation reads nothing but the request's switches, which it shares.
"""

import re
import uuid
from unittest import mock

import pytest
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import NoReverseMatch, ResolverMatch, resolve, reverse
from django.utils import timezone

from apps.blog.models import BlogSite
from apps.common import navigation
from apps.common.context_processors import sidebar_context
from apps.common.features import request_features
from apps.common.navigation import Nav, NavItem, build_nav
from apps.composer.models import PlatformPost, Post
from apps.credentials.models import PlatformCredential
from apps.inbox.models import InboxMessage
from apps.organizations.models import Organization
from apps.social_accounts.models import AnalyticsPlatformConfig, SocialAccount
from apps.studio.models import AgencySettings
from apps.workspaces.models import Workspace

FEATURE_TABLES = (AgencySettings._meta.db_table, BlogSite._meta.db_table)

ORDER = ["home", "approvals", "calendar", "inbox", "analytics", "activity", "blog"]
LABELS = ["Home", "Approvals", "Calendar", "Inbox", "Analytics", "Activity", "Blog"]
PHONE = ["home", "approvals", "calendar", "inbox", "more"]

# Naming rules for copy (CLAUDE.md) and the words the readiness tests ban.
BANNED = re.compile(
    r"\b(?:ai studio|studio|assistant|operator|cto|agents?|workers?|lead|administrator|api[_ ]?keys?|fal|"
    r"ai service|model|provider|tokens?)\b",
    re.IGNORECASE,
)


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org")


@pytest.fixture
def workspace(org):
    return Workspace.objects.create(organization=org, name="WS")


@pytest.fixture
def analytics_on(db):
    """At least one platform has analytics (a platform with no row counts as on)."""
    AnalyticsPlatformConfig.objects.update(is_enabled=True)
    assert AnalyticsPlatformConfig.enabled_platforms()


@pytest.fixture
def analytics_off(db):
    """No platform has analytics, so the Analytics item is hidden."""
    AnalyticsPlatformConfig.objects.update(is_enabled=False)
    have = set(AnalyticsPlatformConfig.objects.values_list("platform", flat=True))
    AnalyticsPlatformConfig.objects.bulk_create(
        AnalyticsPlatformConfig(platform=value, is_enabled=False)
        for value, _label in PlatformCredential.Platform.choices
        if value not in have
    )
    assert AnalyticsPlatformConfig.enabled_platforms() == []


def _blog(workspace, on):
    AgencySettings.objects.update_or_create(workspace=workspace, defaults={"features": {"blog": on}})


def _url(name, workspace, **kwargs):
    return reverse(name, kwargs={"workspace_id": workspace.id, **kwargs})


def _request(path, workspace, user, match=None):
    """A GET for *path*, resolved as the URL resolver would (or as *match*)."""
    request = RequestFactory().get(path)
    request.user = user
    request.workspace = workspace
    request.resolver_match = match or resolve(request.path_info)
    return request


def _future(app, url_name):
    """The match a route Phase 2 has not added yet will produce."""
    return ResolverMatch(lambda request: None, (), {}, url_name=url_name, app_names=[app], namespaces=[app])


def _nav(request):
    return build_nav(request, sidebar_context(request))


def _lit(nav):
    """Every key that is lit: the items and the gear (the phone bar repeats them)."""
    return [item.key for item in (*nav.items, nav.settings) if item.active]


def _item(nav, key):
    return next(item for item in nav.items if item.key == key)


# --- the items, their order, their labels and their targets ---------------------


@pytest.mark.django_db
def test_the_items_come_in_order_with_the_gear_apart(workspace, user, analytics_on):
    _blog(workspace, True)
    nav = _nav(_request(_url("studio:index", workspace), workspace, user))

    assert [item.key for item in nav.items] == ORDER
    assert [item.label for item in nav.items] == LABELS
    assert (nav.settings.key, nav.settings.label) == ("settings", "Settings")
    assert "settings" not in [item.key for item in nav.items]


@pytest.mark.django_db
def test_each_item_goes_to_its_page(workspace, user, analytics_on):
    _blog(workspace, True)
    nav = _nav(_request(_url("studio:index", workspace), workspace, user))

    assert _item(nav, "home").url == _url("studio:index", workspace)
    assert _item(nav, "calendar").url == _url("calendar:calendar", workspace)
    assert _item(nav, "inbox").url == _url("inbox:feed", workspace)
    assert _item(nav, "analytics").url == _url("analytics:index", workspace)
    assert _item(nav, "blog").url == _url("blog:list", workspace)


@pytest.mark.django_db
def test_analytics_shows_while_a_platform_has_analytics(workspace, user, analytics_on):
    nav = _nav(_request(_url("studio:index", workspace), workspace, user))

    assert "analytics" in [item.key for item in nav.items]


@pytest.mark.django_db
def test_analytics_is_hidden_when_no_platform_has_analytics(workspace, user, analytics_off):
    _blog(workspace, True)
    nav = _nav(_request(_url("studio:index", workspace), workspace, user))

    assert [item.key for item in nav.items] == [key for key in ORDER if key != "analytics"]


@pytest.mark.django_db
def test_blog_shows_only_with_the_switch_on(workspace, user, analytics_on):
    path = _url("studio:index", workspace)

    assert "blog" not in [item.key for item in _nav(_request(path, workspace, user)).items]

    _blog(workspace, True)
    assert [item.key for item in _nav(_request(path, workspace, user)).items][-1] == "blog"


@pytest.mark.django_db
def test_an_enabled_website_shows_blog_by_default_and_the_switch_off_hides_it(workspace, user, analytics_on):
    BlogSite.objects.create(
        workspace=workspace,
        name="Site",
        kind=BlogSite.Kind.NEOPOLIS_STATIC,
        site_url="https://www.example.com",
        repo="example/site",
        workflow_file="publish.yml",
        is_enabled=True,
    )
    path = _url("studio:index", workspace)

    assert "blog" in [item.key for item in _nav(_request(path, workspace, user)).items]

    _blog(workspace, False)
    assert "blog" not in [item.key for item in _nav(_request(path, workspace, user)).items]


@pytest.mark.django_db
def test_no_label_uses_a_banned_word(workspace, user, analytics_on):
    _blog(workspace, True)
    nav = _nav(_request(_url("studio:index", workspace), workspace, user))

    labels = [item.label for item in (*nav.items, nav.settings, *nav.phone)]
    assert labels
    for label in labels:
        assert not BANNED.search(label), label


@pytest.mark.django_db
def test_no_workspace_means_no_navigation(user):
    request = RequestFactory().get("/notifications/")
    request.user = user
    request.workspace = None
    request.resolver_match = resolve("/notifications/")

    assert build_nav(request, sidebar_context(request)) == Nav()
    assert Nav().items == () and Nav().settings is None and Nav().phone == ()


# --- the new screens: Approvals and Settings by their route once it exists, Activity by studio:team --


def _reverse_as_if(missing=(), present=None):
    """``reverse`` with the routes in *missing* absent and those in *present* added."""
    real = reverse
    present = present or {}

    def fake(viewname, *args, **kwargs):
        if viewname in missing:
            raise NoReverseMatch(f"{viewname} has no route yet")
        if viewname in present:
            return present[viewname]
        return real(viewname, *args, **kwargs)

    return mock.patch.object(navigation, "reverse", side_effect=fake)


@pytest.mark.django_db
def test_approvals_falls_back_to_the_calendars_approvals_tab(workspace, user):
    request = _request(_url("studio:index", workspace), workspace, user)
    with _reverse_as_if(missing={"approvals:index"}):
        nav = _nav(request)

    assert _item(nav, "approvals").url == _url("calendar:calendar", workspace) + "?mode=list&tab=approvals"


@pytest.mark.django_db
def test_approvals_goes_to_its_own_screen_once_the_route_exists(workspace, user):
    request = _request(_url("studio:index", workspace), workspace, user)
    with _reverse_as_if(present={"approvals:index": "/approvals-screen/"}):
        nav = _nav(request)

    assert _item(nav, "approvals").url == "/approvals-screen/"


@pytest.mark.django_db
def test_activity_is_the_team_route_at_its_activity_address(workspace, user):
    """``studio:team`` names Activity (spec D4): no other route name is tried first, even one that resolves."""
    request = _request(_url("studio:index", workspace), workspace, user)
    with _reverse_as_if(present={"studio:activity": "/activity-screen/"}):
        nav = _nav(request)

    assert _item(nav, "activity").url == _url("studio:team", workspace)
    assert _item(nav, "activity").url.endswith("/studio/activity/")


@pytest.mark.django_db
def test_settings_falls_back_to_set_up(workspace, user):
    request = _request(_url("studio:index", workspace), workspace, user)
    with _reverse_as_if(missing={"settings:index"}):
        nav = _nav(request)

    assert nav.settings.url == _url("studio:setup", workspace)


@pytest.mark.django_db
def test_settings_goes_to_its_own_screen_once_the_route_exists(workspace, user):
    request = _request(_url("studio:index", workspace), workspace, user)
    with _reverse_as_if(present={"settings:index": "/settings-screen/"}):
        nav = _nav(request)

    assert nav.settings.url == "/settings-screen/"


@pytest.mark.django_db
def test_every_link_lights_its_own_item(workspace, user, analytics_on):
    """With today's routes, or after a later task adds one: a link always lands on its own item."""
    _blog(workspace, True)
    nav = _nav(_request(_url("studio:index", workspace), workspace, user))

    for item in (*nav.items, nav.settings):
        landed = _nav(_request(item.url, workspace, user))
        assert _lit(landed) == [item.key], item.url


# --- which place is lit ----------------------------------------------------------

BRIEF = {"brief_id": uuid.uuid4()}
JOB = {"job_id": uuid.uuid4()}


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("name", "kwargs", "query", "expected"),
    [
        # Home: the agency's own pages that are not Activity or Settings.
        pytest.param("studio:index", {}, "", "home", id="home-index"),
        pytest.param("studio:detail", BRIEF, "", "home", id="home-post-page"),
        pytest.param("studio:progress", BRIEF, "", "home", id="home-post-progress"),
        pytest.param("studio:thread", {}, "", "home", id="home-thread"),
        pytest.param("studio:create", {}, "", "home", id="home-create"),
        # Activity: the team at work, its jobs and its routines.
        pytest.param("studio:team", {}, "", "activity", id="activity-team"),
        pytest.param("studio:team_board", {}, "", "activity", id="activity-board"),
        pytest.param("studio:job", JOB, "", "activity", id="activity-job"),
        pytest.param("studio:routines", {}, "", "activity", id="activity-routines"),
        pytest.param("studio:routines_create", {}, "", "activity", id="activity-routine-form-again"),
        # Settings: every page a setting lives on today.
        pytest.param("studio:setup", {}, "", "settings", id="settings-set-up"),
        pytest.param("studio:settings_hub", {}, "", "settings", id="settings-hub"),
        pytest.param("studio:brand", {}, "", "settings", id="settings-brand"),
        pytest.param("studio:autopilot", {}, "", "settings", id="settings-autopilot"),
        pytest.param("studio:trust", {}, "", "settings", id="settings-verified-facts"),
        pytest.param("studio:memory", {}, "", "settings", id="settings-memory"),
        pytest.param("studio:outcomes", {}, "", "settings", id="settings-outcomes"),
        pytest.param("studio:memory_house_style", {}, "", "settings", id="settings-memory-form-again"),
        pytest.param("workspaces:settings", {}, "", "settings", id="settings-workspace"),
        pytest.param("workspaces:approvals_settings", {}, "", "settings", id="settings-approvals"),
        pytest.param("social_accounts:list", {}, "", "settings", id="settings-accounts"),
        pytest.param("social_accounts:connect", {}, "", "settings", id="settings-connect-an-account"),
        pytest.param("telegram:settings", {}, "", "settings", id="settings-telegram"),
        pytest.param("client_portal_admin:client_list", {}, "", "settings", id="settings-clients"),
        # Approvals: the calendar's approvals list.
        pytest.param("calendar:calendar", {}, "?mode=list&tab=approvals", "approvals", id="approvals-tab"),
        # Calendar: the rest of the calendar.
        pytest.param("calendar:calendar", {}, "", "calendar", id="calendar"),
        pytest.param("calendar:calendar", {}, "?mode=list", "calendar", id="calendar-list"),
        pytest.param("calendar:calendar", {}, "?mode=list&tab=drafts", "calendar", id="calendar-other-tab"),
        pytest.param("calendar:queue_list", {}, "", "calendar", id="calendar-queues"),
        pytest.param("calendar:posting_slots", {}, "", "calendar", id="calendar-posting-schedule"),
        # Inbox, Analytics and Blog: their apps.
        pytest.param("inbox:feed", {}, "", "inbox", id="inbox"),
        pytest.param("analytics:index", {}, "", "analytics", id="analytics"),
        pytest.param("blog:list", {}, "", "blog", id="blog"),
    ],
)
def test_the_lit_place(workspace, user, analytics_on, name, kwargs, query, expected):
    _blog(workspace, True)
    nav = _nav(_request(_url(name, workspace, **kwargs) + query, workspace, user))

    assert _lit(nav) == [expected]
    assert nav.active_key == expected


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param("/members/", "settings", id="settings-members"),
        pytest.param("/notifications/preferences/", "settings", id="settings-notification-preferences"),
    ],
)
def test_the_lit_place_on_pages_without_a_workspace_in_the_url(workspace, user, path, expected):
    nav = _nav(_request(path, workspace, user))

    assert _lit(nav) == [expected]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("app", "url_name", "expected"),
    [
        pytest.param("approvals", "index", "approvals", id="approvals-screen"),
        pytest.param("studio", "activity", "activity", id="activity-screen"),
        pytest.param("settings", "index", "settings", id="settings-screen"),
    ],
)
def test_the_new_screens_light_their_place(workspace, user, app, url_name, expected):
    nav = _nav(_request("/", workspace, user, match=_future(app, url_name)))

    assert _lit(nav) == [expected]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path",
    [
        pytest.param(lambda ws: "/notifications/", id="notifications"),
        pytest.param(lambda ws: _url("composer:compose", ws), id="new-post"),
        pytest.param(lambda ws: _url("composer:drafts_list", ws), id="drafts"),
        pytest.param(lambda ws: _url("media_library:index", ws), id="media"),
    ],
)
def test_pages_outside_the_six_places_light_nothing(workspace, user, path):
    nav = _nav(_request(path(workspace), workspace, user))

    assert _lit(nav) == []
    assert nav.active_key is None


@pytest.mark.django_db
def test_nothing_is_lit_without_a_resolved_url(workspace, user):
    request = RequestFactory().get("/")
    request.user = user
    request.workspace = workspace

    assert _lit(_nav(request)) == []


@pytest.mark.django_db
def test_a_hidden_item_is_never_lit(workspace, user, analytics_off):
    _blog(workspace, False)

    for name in ("blog:list", "analytics:index"):
        nav = _nav(_request(_url(name, workspace), workspace, user))
        assert _lit(nav) == []
        assert nav.active_key is None


# --- the phone bar -------------------------------------------------------------


@pytest.mark.django_db
def test_the_phone_bar_is_home_approvals_calendar_inbox_and_more(workspace, user, analytics_on):
    _blog(workspace, True)
    nav = _nav(_request(_url("studio:index", workspace), workspace, user))

    assert [item.key for item in nav.phone] == PHONE
    assert [item.label for item in nav.phone] == ["Home", "Approvals", "Calendar", "Inbox", "More"]
    more = nav.phone[-1]
    assert more.url is None  # a button: it opens the drawer
    assert more.count is None
    for item in nav.phone[:-1]:
        assert item == _item(nav, item.key)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("name", "kwargs", "lit"),
    [
        pytest.param("studio:index", {}, "home", id="home"),
        pytest.param("calendar:calendar", {}, "calendar", id="calendar"),
        pytest.param("inbox:feed", {}, "inbox", id="inbox"),
        pytest.param("studio:team", {}, "more", id="activity-is-under-more"),
        pytest.param("studio:setup", {}, "more", id="settings-is-under-more"),
        pytest.param("analytics:index", {}, "more", id="analytics-is-under-more"),
        pytest.param("blog:list", {}, "more", id="blog-is-under-more"),
        pytest.param("composer:compose", {}, None, id="nothing"),
    ],
)
def test_the_phone_bar_lights_more_for_places_it_does_not_show(workspace, user, analytics_on, name, kwargs, lit):
    _blog(workspace, True)
    nav = _nav(_request(_url(name, workspace, **kwargs), workspace, user))

    assert [item.key for item in nav.phone if item.active] == ([lit] if lit else [])


# --- counts: the ones the sidebar context already has -------------------------------


@pytest.mark.django_db
def test_counts_are_the_sidebar_contexts(workspace, user):
    account = SocialAccount.objects.create(
        workspace=workspace,
        platform="bluesky",
        account_platform_id="did",
        account_name="a",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
    )
    for status in ("pending_review", "pending_client", "scheduled"):
        post = Post.objects.create(workspace=workspace, author=user, caption=status)
        PlatformPost.objects.create(post=post, social_account=account, status=status)
    InboxMessage.objects.create(
        workspace=workspace,
        social_account=account,
        platform_message_id="pm-1",
        message_type=InboxMessage.MessageType.COMMENT,
        sender_name="Ada",
        body="hi?",
        received_at=timezone.now(),
    )
    request = _request(_url("studio:index", workspace), workspace, user)
    context = sidebar_context(request)

    nav = build_nav(request, context)

    assert context["sidebar_pending_approvals"] == 2
    assert context["sidebar_unread_inbox_count"] == 1
    assert _item(nav, "approvals").count == 2
    assert _item(nav, "inbox").count == 1
    assert [item.count for item in nav.phone] == [None, 2, None, 1, None]
    assert all(item.count is None for item in nav.items if item.key not in {"approvals", "inbox"})
    assert nav.settings.count is None


@pytest.mark.django_db
def test_it_reuses_the_context_values_and_queries_nothing_more(workspace, user, analytics_on):
    _blog(workspace, True)
    request = _request(_url("studio:index", workspace), workspace, user)
    context = {**sidebar_context(request), "sidebar_pending_approvals": 7, "sidebar_unread_inbox_count": 4}
    request_features(request)  # the template's ``features`` reads it once per request

    with CaptureQueriesContext(connection) as captured:
        nav = build_nav(request, context)

    assert captured.captured_queries == []
    assert (_item(nav, "approvals").count, _item(nav, "inbox").count) == (7, 4)


@pytest.mark.django_db
def test_its_only_reads_are_the_requests_switches(workspace, user, analytics_on):
    _blog(workspace, True)
    request = _request(_url("studio:index", workspace), workspace, user)
    context = sidebar_context(request)

    with CaptureQueriesContext(connection) as captured:
        build_nav(request, context)
    with CaptureQueriesContext(connection) as again:
        build_nav(request, context)

    sql = [query["sql"] for query in captured.captured_queries]
    assert 0 < len(sql) <= 2
    assert all(any(table in statement for table in FEATURE_TABLES) for statement in sql), sql
    assert again.captured_queries == []


@pytest.mark.django_db
def test_without_a_context_it_uses_the_sidebar_context(workspace, user, analytics_on):
    request = _request(_url("calendar:calendar", workspace) + "?mode=list&tab=approvals", workspace, user)

    assert build_nav(request) == build_nav(request, sidebar_context(request))


def test_items_are_plain_values():
    item = NavItem(key="home", label="Home", url="/x/", count=None, active=True)

    assert item == NavItem("home", "Home", "/x/", None, True)
    with pytest.raises(AttributeError):
        item.active = False
