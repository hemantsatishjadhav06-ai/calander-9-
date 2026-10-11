"""Google Search Console: the OAuth flow, the property choice, the daily sync and the numbers read back.

Nothing reaches Google: ``search_console._request`` is replaced by :class:`FakeGoogle`.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from background_task.models import Task
from django.core import signing
from django.db import connection as db_connection
from django.test import override_settings
from django.urls import reverse

from apps.blog import search_console
from apps.blog.models import SearchConsoleConnection, SearchPerformance
from apps.blog.tests.conftest import approved_post

REFRESH = "1//refresh-token-secret"
TODAY = dt.date(2026, 10, 9)


class FakeGoogle:
    """Answers the token, sites and searchAnalytics calls; records every request."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []
        self.token_status = 200
        self.refresh_token = REFRESH
        self.sites = [
            {"siteUrl": "sc-domain:neopolisinfra.com", "permissionLevel": "siteOwner"},
            {"siteUrl": "https://other.example/", "permissionLevel": "siteFullUser"},
            {"siteUrl": "https://unverified.example/", "permissionLevel": "siteUnverifiedUser"},
        ]
        self.rows: list[dict] = []
        self.query_status = 200
        self.raise_error: Exception | None = None

    def __call__(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.raise_error is not None:
            raise self.raise_error
        request = httpx.Request(method, url)
        if url == search_console.TOKEN_URL:
            grant = kwargs["data"]["grant_type"]
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_grant"}, request=request)
            if grant == "authorization_code":
                return httpx.Response(
                    200, json={"refresh_token": self.refresh_token, "access_token": "at-1"}, request=request
                )
            return httpx.Response(200, json={"access_token": "at-2", "expires_in": 3599}, request=request)
        if url == search_console.REVOKE_URL:
            return httpx.Response(200, request=request)
        if url == search_console.SITES_URL:
            return httpx.Response(200, json={"siteEntry": self.sites}, request=request)
        if url.endswith("/searchAnalytics/query"):
            if self.query_status != 200:
                return httpx.Response(
                    self.query_status, json={"error": {"status": "PERMISSION_DENIED"}}, request=request
                )
            start = kwargs["json"]["startRow"]
            limit = kwargs["json"]["rowLimit"]
            return httpx.Response(200, json={"rows": self.rows[start : start + limit]}, request=request)
        raise AssertionError(f"Unexpected Google call {method} {url}")

    def queries(self):
        return [kw["json"] for method, url, kw in self.calls if url.endswith("/searchAnalytics/query")]


@pytest.fixture
def google(monkeypatch):
    fake = FakeGoogle()
    monkeypatch.setattr(search_console, "_request", fake)
    return fake


@pytest.fixture
def gsc_settings(settings):
    settings.GSC_CLIENT_ID = "client-id.apps.googleusercontent.com"
    settings.GSC_CLIENT_SECRET = "gsc-secret"
    settings.APP_URL = "https://app.smbean.test"
    return settings


@pytest.fixture(autouse=True)
def _fresh_cache():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


def _connect(world, *, property_url="sc-domain:neopolisinfra.com", site=None):
    return SearchConsoleConnection.objects.create(
        site=site or world.neopolis, property_url=property_url, refresh_token=REFRESH, connected_by=world.owner
    )


def _row(day, page, query, clicks=1, impressions=10, position=5.0):
    return {
        "keys": [day.isoformat(), page, query],
        "clicks": clicks,
        "impressions": impressions,
        "ctr": clicks / impressions,
        "position": position,
    }


# ---------------------------------------------------------------------------
# The OAuth flow
# ---------------------------------------------------------------------------


def test_the_authorization_url_asks_for_read_only_offline_access_with_pkce(world, gsc_settings):
    url = search_console.authorization_url(world.owner, world.neopolis)
    parts = urlsplit(url)
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == search_console.AUTH_URL
    assert query["scope"] == "https://www.googleapis.com/auth/webmasters.readonly"
    assert query["access_type"] == "offline" and query["prompt"] == "consent"
    assert query["redirect_uri"] == "https://app.smbean.test/blog/search-console/callback/"
    assert query["code_challenge_method"] == "S256" and len(query["code_challenge"]) == 43
    state = search_console.read_state(query["state"], world.owner)
    assert state.site_id == str(world.neopolis.pk) and state.workspace_id == str(world.workspace.pk)
    # The verifier is derived from the state, so the challenge matches what the callback will send.
    assert search_console.pkce_challenge(search_console.pkce_verifier(state.nonce)) == query["code_challenge"]


def test_the_state_is_bound_to_the_person_and_cannot_be_forged(world):
    state = search_console.sign_state(search_console.make_state(world.owner, world.neopolis))
    with pytest.raises(search_console.SearchConsoleError, match="someone else"):
        search_console.read_state(state, world.editor)
    with pytest.raises(search_console.SearchConsoleError, match="didn't come from"):
        search_console.read_state(state[:-2] + "xx", world.owner)
    forged = signing.dumps({"u": str(world.owner.pk), "s": "x", "w": "y", "n": "z"}, salt="another-salt")
    with pytest.raises(search_console.SearchConsoleError):
        search_console.read_state(forged, world.owner)


def test_an_expired_state_is_refused(world, monkeypatch):
    state = search_console.sign_state(search_console.make_state(world.owner, world.neopolis))
    monkeypatch.setattr(search_console, "STATE_MAX_AGE", -1)
    with pytest.raises(search_console.SearchConsoleError, match="too long"):
        search_console.read_state(state, world.owner)


def _callback_url(world, user, *, code="auth-code", site=None, extra=""):
    state = search_console.sign_state(search_console.make_state(user, site or world.neopolis))
    return reverse("blog_search_console_callback") + f"?state={state}&code={code}{extra}"


def test_the_callback_stores_the_refresh_token_encrypted_and_asks_for_the_property(client, world, gsc_settings, google):
    client.force_login(world.owner)
    response = client.get(_callback_url(world, world.owner))

    assert response.status_code == 302
    assert response["Location"] == reverse(
        "blog:search_console_property", kwargs={"workspace_id": world.workspace.id, "site_id": world.neopolis.pk}
    )
    connection = SearchConsoleConnection.objects.get(site=world.neopolis)
    assert connection.refresh_token == REFRESH and connection.property_url == ""
    assert connection.connected_by == world.owner
    assert search_console.has_token(connection) and not search_console.is_connected(connection)
    with db_connection.cursor() as cursor:
        cursor.execute("SELECT refresh_token FROM blog_search_console_connection WHERE id = %s", [connection.pk])
        assert REFRESH not in cursor.fetchone()[0]
    exchange = google.calls[0][2]["data"]
    assert exchange["grant_type"] == "authorization_code" and exchange["code"] == "auth-code"
    assert exchange["redirect_uri"] == "https://app.smbean.test/blog/search-console/callback/"
    assert len(exchange["code_verifier"]) == 64


@pytest.mark.parametrize("role", ["editor", "client", "viewer"])
def test_only_an_owner_may_finish_connecting(client, world, gsc_settings, google, role):
    user = getattr(world, role)
    client.force_login(user)
    response = client.get(_callback_url(world, user))
    assert response.status_code == 403
    assert not SearchConsoleConnection.objects.exists()
    assert google.calls == []


def test_a_state_started_by_someone_else_is_refused(client, world, gsc_settings, google):
    client.force_login(world.editor)
    response = client.get(_callback_url(world, world.owner))
    assert response.status_code == 302
    assert not SearchConsoleConnection.objects.exists() and google.calls == []


def test_a_cancelled_or_refused_consent_stores_nothing(client, world, gsc_settings, google):
    client.force_login(world.owner)
    response = client.get(_callback_url(world, world.owner, extra="&error=access_denied"), follow=True)
    assert "cancelled or refused" in response.content.decode()
    assert not SearchConsoleConnection.objects.exists() and google.calls == []


def test_google_refusing_the_code_is_a_sentence(client, world, gsc_settings, google):
    google.token_status = 400
    client.force_login(world.owner)
    response = client.get(_callback_url(world, world.owner), follow=True)
    assert "accept the sign-in" in response.content.decode()
    assert not SearchConsoleConnection.objects.exists()


def test_no_refresh_token_means_no_connection(client, world, gsc_settings, google):
    google.refresh_token = ""
    client.force_login(world.owner)
    body = client.get(_callback_url(world, world.owner), follow=True).content.decode()
    assert "lasting access" in body
    assert not SearchConsoleConnection.objects.exists()


def test_connect_redirects_to_google_for_owners_only(client, world, gsc_settings):
    url = reverse(
        "blog:search_console_connect", kwargs={"workspace_id": world.workspace.id, "site_id": world.neopolis.pk}
    )
    client.force_login(world.editor)
    assert client.post(url).status_code == 403
    client.force_login(world.owner)
    assert client.get(url).status_code == 405
    response = client.post(url)
    assert response.status_code == 302 and response["Location"].startswith(search_console.AUTH_URL)


def test_without_a_google_client_nothing_reaches_google(client, world, settings, google):
    settings.GSC_CLIENT_ID = ""
    settings.GSC_CLIENT_SECRET = ""
    client.force_login(world.owner)
    url = reverse(
        "blog:search_console_connect", kwargs={"workspace_id": world.workspace.id, "site_id": world.neopolis.pk}
    )
    response = client.post(url, follow=True)
    assert "Ask your admin to connect Google Search Console" in response.content.decode()
    body = client.get(reverse("blog:list", kwargs={"workspace_id": world.workspace.id})).content.decode()
    assert "Ask your admin to connect Google Search Console" in body
    assert "Connect Google Search Console" not in body
    assert google.calls == []


def test_another_workspaces_site_cannot_be_connected(client, world, gsc_settings):
    from apps.blog.models import BlogSite
    from apps.workspaces.models import Workspace

    other_ws = Workspace.objects.create(organization=world.org, name="Elsewhere")
    other = BlogSite.objects.create(
        workspace=other_ws,
        name="Other",
        kind="morespace_static",
        site_url="https://o.example",
        repo="o/r",
        workflow_file="w",
    )
    client.force_login(world.owner)
    url = reverse("blog:search_console_connect", kwargs={"workspace_id": world.workspace.id, "site_id": other.pk})
    assert client.post(url).status_code == 404


# ---------------------------------------------------------------------------
# Picking the property
# ---------------------------------------------------------------------------


def _property_url(world, site=None):
    return reverse(
        "blog:search_console_property",
        kwargs={"workspace_id": world.workspace.id, "site_id": (site or world.neopolis).pk},
    )


def test_the_property_page_lists_readable_properties_and_suggests_the_match(client, world, gsc_settings, google):
    _connect(world, property_url="")
    client.force_login(world.owner)
    body = client.get(_property_url(world)).content.decode()
    assert "sc-domain:neopolisinfra.com" in body and "https://other.example/" in body
    assert "unverified.example" not in body
    assert 'value="sc-domain:neopolisinfra.com" checked' in body


def test_only_a_listed_property_can_be_saved(client, world, gsc_settings, google):
    connection = _connect(world, property_url="")
    client.force_login(world.owner)
    response = client.post(_property_url(world), {"property": "sc-domain:attacker.example"})
    assert response.status_code == 400
    connection.refresh_from_db()
    assert connection.property_url == ""


def test_saving_the_property_queues_the_backfill(
    client, world, gsc_settings, google, django_capture_on_commit_callbacks
):
    connection = _connect(world, property_url="")
    client.force_login(world.owner)
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(_property_url(world), {"property": "sc-domain:neopolisinfra.com"})
    assert response.status_code == 302
    connection.refresh_from_db()
    assert connection.property_url == "sc-domain:neopolisinfra.com" and search_console.is_connected(connection)
    task = Task.objects.get(task_name="apps.blog.tasks.sync_search_console_site")
    assert str(connection.pk) in task.task_params and task.priority == -30


def test_the_property_page_is_for_owners(client, world, gsc_settings, google):
    _connect(world, property_url="")
    for user in (world.editor, world.client):
        client.force_login(user)
        assert client.get(_property_url(world)).status_code == 403
    assert google.calls == []


def test_disconnect_revokes_and_removes_the_numbers(client, world, gsc_settings, google):
    _connect(world)
    SearchPerformance.objects.create(
        site=world.neopolis, date=TODAY, page="https://www.neopolisinfra.com/blog/x", query="q", impressions=3
    )
    client.force_login(world.owner)
    url = reverse(
        "blog:search_console_disconnect", kwargs={"workspace_id": world.workspace.id, "site_id": world.neopolis.pk}
    )
    client.post(url)
    assert not SearchConsoleConnection.objects.exists() and not SearchPerformance.objects.exists()
    assert google.calls[-1][1] == search_console.REVOKE_URL


def test_disconnect_works_when_google_is_unreachable(client, world, gsc_settings, google):
    _connect(world)
    google.raise_error = httpx.ConnectError("down")
    client.force_login(world.owner)
    url = reverse(
        "blog:search_console_disconnect", kwargs={"workspace_id": world.workspace.id, "site_id": world.neopolis.pk}
    )
    assert client.post(url).status_code == 302
    assert not SearchConsoleConnection.objects.exists()


# ---------------------------------------------------------------------------
# Syncing
# ---------------------------------------------------------------------------


def test_the_first_sync_backfills_90_days_and_upserts(world, gsc_settings, google):
    connection = _connect(world)
    page = "https://www.neopolisinfra.com/blog/flats-in-kokapet-2026"
    google.rows = [
        _row(TODAY - dt.timedelta(days=2), page, "flats in kokapet", clicks=3, impressions=40, position=8.2),
        _row(TODAY - dt.timedelta(days=2), page, "kokapet prices", clicks=0, impressions=20, position=14.0),
    ]
    assert search_console.sync(connection, today=TODAY) == 2
    query = google.queries()[0]
    assert query["dimensions"] == ["date", "page", "query"]
    assert query["startDate"] == (TODAY - dt.timedelta(days=90)).isoformat()
    assert query["endDate"] == (TODAY - dt.timedelta(days=1)).isoformat()
    assert SearchPerformance.objects.count() == 2

    # The next sync re-reads from 3 days before the newest stored day, and updates in place.
    google.rows = [_row(TODAY - dt.timedelta(days=2), page, "flats in kokapet", clicks=5, impressions=50, position=7.0)]
    google.calls.clear()
    assert search_console.sync(connection, today=TODAY) == 1
    assert google.queries()[0]["startDate"] == (TODAY - dt.timedelta(days=5)).isoformat()
    row = SearchPerformance.objects.get(query="flats in kokapet")
    assert (row.clicks, row.impressions, row.position) == (5, 50, 7.0)
    assert SearchPerformance.objects.count() == 2


def test_sync_pages_through_large_results(world, gsc_settings, google, monkeypatch):
    monkeypatch.setattr(search_console, "ROW_LIMIT", 2)
    connection = _connect(world)
    page = "https://www.neopolisinfra.com/blog/a"
    google.rows = [_row(TODAY - dt.timedelta(days=1), page, f"q{i}") for i in range(5)]
    assert search_console.sync(connection, today=TODAY) == 5
    assert [q["startRow"] for q in google.queries()] == [0, 2, 4]


def test_a_lost_permission_is_recorded_on_the_connection_and_nothing_raises(world, gsc_settings, google):
    connection = _connect(world)
    google.query_status = 403
    assert search_console.run_sync(connection.pk) == 0
    connection.refresh_from_db()
    assert "can't read sc-domain:neopolisinfra.com" in connection.last_error
    assert connection.last_sync_at is not None


def test_a_revoked_token_asks_for_a_reconnect(world, gsc_settings, google):
    connection = _connect(world)
    google.token_status = 400
    search_console.run_sync(connection.pk)
    connection.refresh_from_db()
    assert "connect it again" in connection.last_error


def test_an_unexpected_crash_is_recorded_not_raised(world, gsc_settings, google, monkeypatch):
    connection = _connect(world)

    def boom(*args, **kwargs):
        raise RuntimeError("bug")

    monkeypatch.setattr(search_console, "sync", boom)
    assert search_console.run_sync(connection.pk) == 0
    connection.refresh_from_db()
    assert "unexpected error" in connection.last_error


def test_the_refresh_token_is_never_logged(world, gsc_settings, google, caplog):
    connection = _connect(world)
    google.token_status = 401
    with caplog.at_level(logging.DEBUG):
        search_console.run_sync(connection.pk)
    assert REFRESH not in caplog.text and "gsc-secret" not in caplog.text


def test_due_connections_skip_recent_unpicked_and_archived(world, gsc_settings):
    from django.utils import timezone

    due = _connect(world)
    _connect(world, site=world.morespace, property_url="")  # no property yet
    assert [c.pk for c in search_console.due_connections()] == [due.pk]
    SearchConsoleConnection.objects.filter(pk=due.pk).update(last_sync_at=timezone.now())
    assert search_console.due_connections() == []
    SearchConsoleConnection.objects.filter(pk=due.pk).update(last_sync_at=timezone.now() - dt.timedelta(days=2))
    world.workspace.is_archived = True
    world.workspace.save(update_fields=["is_archived"])
    assert search_console.due_connections() == []


def test_the_daily_tick_queues_one_sync_per_due_site(world, gsc_settings):
    from apps.blog.tasks import queue_search_console_syncs

    _connect(world)
    queue_search_console_syncs.now()
    tasks = Task.objects.filter(task_name="apps.blog.tasks.sync_search_console_site")
    assert tasks.count() == 1 and tasks.get().priority == -30


# ---------------------------------------------------------------------------
# Reading the numbers back
# ---------------------------------------------------------------------------


def _perf(world, day, page, query, clicks, impressions, position):
    SearchPerformance.objects.create(
        site=world.neopolis,
        date=day,
        page=page,
        query=query,
        clicks=clicks,
        impressions=impressions,
        ctr=clicks / impressions if impressions else 0,
        position=position,
    )


def test_page_trend_weights_positions_and_compares_with_the_28_days_before(world):
    url = "https://www.neopolisinfra.com/blog/flats-in-kokapet-2026"
    recent = TODAY - dt.timedelta(days=3)
    older = TODAY - dt.timedelta(days=40)
    _perf(world, recent, url, "flats in kokapet", 6, 100, 4.0)
    _perf(world, recent, url + ".html", "kokapet prices", 1, 50, 13.0)  # the .html form is the same page
    _perf(world, recent, "https://neopolisinfra.com/blog/other", "other", 9, 900, 1.0)
    _perf(world, older, url, "flats in kokapet", 2, 100, 10.0)

    trend = search_console.page_trend(world.neopolis, url, today=TODAY)

    assert trend["clicks"] == 7 and trend["impressions"] == 150
    assert trend["position"] == 7.0  # (4*100 + 13*50) / 150
    assert trend["previous_position"] == 10.0 and trend["position_change"] == 3.0
    assert [q["query"] for q in trend["queries"]] == ["flats in kokapet", "kokapet prices"]


def test_site_overview_totals_and_top_pages(world):
    day = TODAY - dt.timedelta(days=2)
    _perf(world, day, "https://www.neopolisinfra.com/blog/a", "q1", 5, 100, 3.0)
    _perf(world, day, "https://www.neopolisinfra.com/blog/b", "q2", 1, 300, 9.0)
    overview = search_console.site_overview(world.neopolis, today=TODAY)
    assert overview["clicks"] == 6 and overview["impressions"] == 400
    assert [p["page"] for p in overview["pages"]] == [
        "https://www.neopolisinfra.com/blog/b",
        "https://www.neopolisinfra.com/blog/a",
    ]


def test_matching_property_prefers_the_exact_site(world):
    props = [{"url": "https://www.neopolisinfra.com/", "permission": "siteOwner"}]
    assert search_console.matching_property(props, world.neopolis) == "https://www.neopolisinfra.com/"
    assert search_console.matching_property([{"url": "sc-domain:neopolisinfra.com"}], world.neopolis) == (
        "sc-domain:neopolisinfra.com"
    )
    assert search_console.matching_property([{"url": "https://else.example/"}], world.neopolis) == ""


def test_connected_is_decided_in_python_not_by_filtering_the_encrypted_column(world):
    empty = SearchConsoleConnection.objects.create(site=world.neopolis, property_url="sc-domain:x", refresh_token="")
    assert not search_console.is_connected(empty)
    assert SearchConsoleConnection.objects.filter(refresh_token="").count() == 0  # why: '' is stored encrypted


@override_settings(GSC_CLIENT_ID="id", GSC_CLIENT_SECRET="s")
def test_the_detail_page_shows_the_rankings_and_a_suggestion(client, world):
    post = approved_post(world)
    from apps.blog.models import BlogPost

    BlogPost.objects.filter(pk=post.pk).update(
        status="published", published_url="https://www.neopolisinfra.com/blog/flats-in-kokapet-2026"
    )
    _connect(world)
    from django.utils import timezone

    today = timezone.localdate()
    _perf(
        world,
        today - dt.timedelta(days=2),
        "https://www.neopolisinfra.com/blog/flats-in-kokapet-2026",
        "encumbrance certificate online",
        2,
        120,
        9.6,
    )
    client.force_login(world.owner)
    body = client.get(
        reverse("blog:detail", kwargs={"workspace_id": world.workspace.id, "post_id": post.pk})
    ).content.decode()
    assert "Search ranking" in body and "encumbrance certificate online" in body and "#9.6" in body
    assert "bottom of page 1" in body
    payload = json.dumps(body)
    assert REFRESH not in payload
