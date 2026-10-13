"""Google Search Console: how each website's articles rank, read with the site owner's permission.

A manager connects a website once (Google's OAuth 2.0 web flow, read-only
scope ``webmasters.readonly``) and picks the Search Console property that
matches it. A daily task then copies the last days of clicks, impressions,
click-through rate and average position per page and search query into
:class:`~apps.blog.models.SearchPerformance`, which the blog pages and the SEO
monitor read. Nothing here can change anything in Search Console.

* **One redirect URI.** Every connection comes back to the same callback
  (:func:`redirect_uri`, no workspace in the path), so the Google OAuth client
  needs exactly one authorised redirect URI. Which website and person the
  answer belongs to travels in ``state``, signed with ``django.core.signing``
  and bound to the person who started it; it expires after 15 minutes.
* **PKCE without a session.** The code verifier is derived from the state's
  nonce with an HMAC of ``SECRET_KEY``, so only this server can produce it.
* **The refresh token** lives only in the encrypted
  ``SearchConsoleConnection.refresh_token``; it is never logged, shown or put in
  a prompt. "Connected" is tested in Python (an empty token is stored
  encrypted, so it can't be filtered on).
* **No network in a web request except** the code exchange, the property list
  and the revoke on disconnect — the syncing happens in the worker.

``GSC_CLIENT_ID`` / ``GSC_CLIENT_SECRET`` switch it on. Without them the pages
say to ask the admin to connect Google Search Console and do nothing else.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import logging
import secrets
from dataclasses import dataclass
from urllib.parse import quote, urlencode, urlsplit

import httpx
from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.db.models import Max, Q, Sum
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import salted_hmac

from .models import BlogSite, SearchConsoleConnection, SearchPerformance

logger = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
SITES_URL = "https://www.googleapis.com/webmasters/v3/sites"
QUERY_URL = "https://www.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query"
SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"

STATE_SALT = "apps.blog.search_console.state"
PKCE_SALT = "apps.blog.search_console.pkce"
STATE_MAX_AGE = 15 * 60
TIMEOUT = 20

#: First sync after connecting reaches this far back.
BACKFILL_DAYS = 90
#: Later syncs re-read the last days already stored (Google revises fresh days).
REFRESH_DAYS = 3
#: Google's maximum page size, and how many pages one sync may read.
ROW_LIMIT = 25_000
MAX_PAGES = 20
#: Search Console keeps 16 months; so do we.
KEEP_DAYS = 490
#: The window the ranking panels and the SEO monitor compare.
WINDOW_DAYS = 28
#: A connection is synced again once its last sync is this old.
SYNC_EVERY = dt.timedelta(hours=20)


class SearchConsoleError(Exception):
    """Something about Search Console a person needs to know. The message is for people."""


# ---------------------------------------------------------------------------
# Configuration and connection state
# ---------------------------------------------------------------------------


def client_credentials() -> tuple[str, str]:
    return (
        (getattr(settings, "GSC_CLIENT_ID", "") or "").strip(),
        (getattr(settings, "GSC_CLIENT_SECRET", "") or "").strip(),
    )


def is_configured() -> bool:
    client_id, secret = client_credentials()
    return bool(client_id and secret)


def redirect_uri() -> str:
    return settings.APP_URL.rstrip("/") + reverse("blog_search_console_callback")


def has_token(connection: SearchConsoleConnection | None) -> bool:
    """Whether Google gave us lasting read access (checked in Python: the column is encrypted)."""
    return bool(connection is not None and (connection.refresh_token or "").strip())


def is_connected(connection: SearchConsoleConnection | None) -> bool:
    """Read access *and* a property picked: the connection can sync."""
    return has_token(connection) and bool((connection.property_url or "").strip())  # type: ignore[union-attr]


def connection_for(site: BlogSite) -> SearchConsoleConnection | None:
    return SearchConsoleConnection.objects.filter(site=site).first()


# ---------------------------------------------------------------------------
# HTTP (one function, so tests replace it and nothing reaches Google)
# ---------------------------------------------------------------------------


def _request(method: str, url: str, **kwargs) -> httpx.Response:
    return httpx.request(method, url, timeout=TIMEOUT, **kwargs)


def _call(method: str, url: str, **kwargs) -> httpx.Response:
    try:
        return _request(method, url, **kwargs)
    except httpx.HTTPError as exc:
        raise SearchConsoleError(
            f"Couldn't reach Google ({exc.__class__.__name__}). Try again in a few minutes."
        ) from exc


def _error_code(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return ""
    error = data.get("error") if isinstance(data, dict) else ""
    if isinstance(error, dict):
        return str(error.get("status") or error.get("message") or "")
    return str(error or "")


# ---------------------------------------------------------------------------
# The OAuth flow
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class State:
    user_id: str
    site_id: str
    workspace_id: str
    nonce: str


def make_state(user, site: BlogSite) -> State:
    return State(str(user.pk), str(site.pk), str(site.workspace_id), secrets.token_urlsafe(16))


def sign_state(state: State) -> str:
    return signing.dumps(
        {"u": state.user_id, "s": state.site_id, "w": state.workspace_id, "n": state.nonce}, salt=STATE_SALT
    )


def read_state(value: str, user) -> State:
    """The state Google sent back, if this server signed it for ``user`` in the last 15 minutes."""
    try:
        data = signing.loads(value or "", salt=STATE_SALT, max_age=STATE_MAX_AGE)
    except signing.SignatureExpired as exc:
        raise SearchConsoleError("That Google sign-in took too long. Start connecting again.") from exc
    except signing.BadSignature as exc:
        raise SearchConsoleError("That Google answer didn't come from a connect request made here.") from exc
    if not isinstance(data, dict) or str(data.get("u")) != str(user.pk):
        raise SearchConsoleError("That Google answer belongs to a connect request someone else started.")
    return State(str(data["u"]), str(data["s"]), str(data["w"]), str(data["n"]))


def pkce_verifier(nonce: str) -> str:
    # 64 hex characters: inside PKCE's 43–128, and only this server can derive it.
    return salted_hmac(PKCE_SALT, nonce, algorithm="sha256").hexdigest()


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorization_url(user, site: BlogSite) -> str:
    """Where to send a manager to grant read access for ``site``."""
    client_id, _secret = client_credentials()
    state = make_state(user, site)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": SCOPE,
        # A refresh token, every time (Google only sends one on consent).
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "false",
        "state": sign_state(state),
        "code_challenge": pkce_challenge(pkce_verifier(state.nonce)),
        "code_challenge_method": "S256",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str, state: State) -> str:
    """Trade Google's one-time code for a refresh token."""
    client_id, secret = client_credentials()
    response = _call(
        "POST",
        TOKEN_URL,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": secret,
            "redirect_uri": redirect_uri(),
            "grant_type": "authorization_code",
            "code_verifier": pkce_verifier(state.nonce),
        },
    )
    if response.status_code != 200:
        logger.warning("Search Console code exchange refused (%s %s)", response.status_code, _error_code(response))
        raise SearchConsoleError("Google didn't accept the sign-in. Try connecting again.")
    token = (response.json() or {}).get("refresh_token") or ""
    if not token:
        raise SearchConsoleError(
            "Google didn't give lasting access. Remove SM Bean from your Google account's third-party access, "
            "then connect again."
        )
    return token


def _token_cache_key(connection: SearchConsoleConnection) -> str:
    fingerprint = hashlib.sha256((connection.refresh_token or "").encode("utf-8")).hexdigest()[:16]
    return f"blog:gsc:access:{connection.pk}:{fingerprint}"


def access_token(connection: SearchConsoleConnection) -> str:
    """A short-lived access token, cached for most of its hour."""
    if not has_token(connection):
        raise SearchConsoleError("This website isn't connected to Google Search Console.")
    key = _token_cache_key(connection)
    cached = cache.get(key)
    if cached:
        return cached
    client_id, secret = client_credentials()
    response = _call(
        "POST",
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": secret,
            "refresh_token": connection.refresh_token,
            "grant_type": "refresh_token",
        },
    )
    if response.status_code != 200:
        logger.warning("Search Console token refresh refused (%s %s)", response.status_code, _error_code(response))
        if response.status_code in (400, 401):
            raise SearchConsoleError(
                "Google no longer accepts SM Bean's access to Search Console (it was removed or expired). "
                "A manager needs to connect it again."
            )
        raise SearchConsoleError(f"Google's sign-in service answered {response.status_code}. It will try again.")
    payload = response.json() or {}
    token = payload.get("access_token") or ""
    if not token:
        raise SearchConsoleError("Google's sign-in service gave no access token. It will try again.")
    cache.set(key, token, max(60, int(payload.get("expires_in", 3600)) - 300))
    return token


def revoke(connection: SearchConsoleConnection) -> None:
    """Best effort: tell Google to drop SM Bean's access. Never raises."""
    if not has_token(connection):
        return
    try:
        _request("POST", REVOKE_URL, data={"token": connection.refresh_token})
    except Exception as exc:  # noqa: BLE001 - disconnecting must work even when Google is unreachable
        logger.info("Search Console revoke failed: %s", exc.__class__.__name__)
    cache.delete(_token_cache_key(connection))


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


def list_properties(connection: SearchConsoleConnection) -> list[dict]:
    """The Search Console properties this Google account can read: ``[{"url", "permission"}]``."""
    token = access_token(connection)
    response = _call("GET", SITES_URL, headers={"Authorization": f"Bearer {token}"})
    if response.status_code != 200:
        logger.warning("Search Console property list refused (%s)", response.status_code)
        raise SearchConsoleError(f"Google wouldn't list the Search Console properties ({response.status_code}).")
    entries = (response.json() or {}).get("siteEntry") or []
    usable = []
    for entry in entries:
        url = str(entry.get("siteUrl") or "")
        permission = str(entry.get("permissionLevel") or "")
        if url and permission != "siteUnverifiedUser":
            usable.append({"url": url, "permission": permission})
    return sorted(usable, key=lambda p: p["url"])


def _bare_host(url: str) -> str:
    host = urlsplit(url if "://" in url else f"https://{url}").netloc.lower()
    return host.removeprefix("www.")


def matching_property(properties: list[dict], site: BlogSite) -> str:
    """The property that covers ``site``: its exact URL-prefix property, else its domain property."""
    origin = site.origin.rstrip("/") + "/"
    urls = [p["url"] for p in properties]
    if origin in urls:
        return origin
    domain = f"sc-domain:{_bare_host(site.origin)}"
    if domain in urls:
        return domain
    host = _bare_host(site.origin)
    for url in urls:
        if not url.startswith("sc-domain:") and _bare_host(url) == host:
            return url
    return ""


# ---------------------------------------------------------------------------
# Syncing (runs in the worker)
# ---------------------------------------------------------------------------


def _query(token: str, property_url: str, start: dt.date, end: dt.date, start_row: int) -> list[dict]:
    response = _call(
        "POST",
        QUERY_URL.format(site=quote(property_url, safe="")),
        headers={"Authorization": f"Bearer {token}"},
        json={
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "dimensions": ["date", "page", "query"],
            "rowLimit": ROW_LIMIT,
            "startRow": start_row,
        },
    )
    if response.status_code == 403:
        raise SearchConsoleError(
            f"Google says the connected account can't read {property_url} any more. "
            "A manager needs to connect an account that can."
        )
    if response.status_code != 200:
        logger.warning("Search Console query refused (%s %s)", response.status_code, _error_code(response))
        raise SearchConsoleError(f"Google's Search Console answered {response.status_code}. It will try again.")
    return (response.json() or {}).get("rows") or []


def sync_window(site: BlogSite, today: dt.date) -> tuple[dt.date, dt.date]:
    """The days to (re)read: 90 days on the first sync, else from 3 days before the newest stored day."""
    end = today - dt.timedelta(days=1)
    latest = SearchPerformance.objects.filter(site=site).aggregate(latest=Max("date"))["latest"]
    earliest = today - dt.timedelta(days=BACKFILL_DAYS)
    if latest is None or latest < earliest:
        return earliest, end
    return min(latest - dt.timedelta(days=REFRESH_DAYS), end), end


def _rows_to_objects(site: BlogSite, rows: list[dict]) -> list[SearchPerformance]:
    best: dict[tuple, SearchPerformance] = {}
    for row in rows:
        keys = row.get("keys") or []
        if len(keys) != 3:
            continue
        try:
            day = dt.date.fromisoformat(str(keys[0]))
        except ValueError:
            continue
        page, query = str(keys[1])[:500], str(keys[2])[:300]
        if not page or not query:
            continue
        item = SearchPerformance(
            site=site,
            date=day,
            page=page,
            query=query,
            clicks=max(0, int(row.get("clicks") or 0)),
            impressions=max(0, int(row.get("impressions") or 0)),
            ctr=float(row.get("ctr") or 0),
            position=float(row.get("position") or 0),
        )
        key = (day, page, query)
        # Two long queries cut to the same 300 characters: keep the bigger row.
        if key not in best or item.impressions > best[key].impressions:
            best[key] = item
    return list(best.values())


def sync(connection: SearchConsoleConnection, *, today: dt.date | None = None) -> int:
    """Copy the window's rows into SearchPerformance (upsert). Returns how many rows were stored.

    Raises :class:`SearchConsoleError` with a sentence for people; the task
    that calls it records the sentence on the connection and never raises.
    """
    if not is_connected(connection):
        raise SearchConsoleError("Pick the Search Console property for this website first.")
    site = connection.site
    today = today or timezone.localdate()
    start, end = sync_window(site, today)
    if start > end:
        return 0
    token = access_token(connection)
    stored = 0
    for page in range(MAX_PAGES):
        rows = _query(token, connection.property_url, start, end, page * ROW_LIMIT)
        objects = _rows_to_objects(site, rows)
        if objects:
            SearchPerformance.objects.bulk_create(
                objects,
                update_conflicts=True,
                unique_fields=["site", "date", "page", "query"],
                update_fields=["clicks", "impressions", "ctr", "position"],
                batch_size=2000,
            )
            stored += len(objects)
        if len(rows) < ROW_LIMIT:
            break
    SearchPerformance.objects.filter(site=site, date__lt=today - dt.timedelta(days=KEEP_DAYS)).delete()
    return stored


def due_connections(now: dt.datetime | None = None):
    """Connections whose last sync is old enough, in workspaces that are still in use."""
    now = now or timezone.now()
    candidates = SearchConsoleConnection.objects.select_related("site", "site__workspace").filter(
        Q(last_sync_at__isnull=True) | Q(last_sync_at__lt=now - SYNC_EVERY),
        site__is_enabled=True,
        site__workspace__is_archived=False,
        site__workspace__organization__deletion_requested_at__isnull=True,
    )
    return [c for c in candidates if is_connected(c)]


def run_sync(connection_id) -> int:
    """Sync one connection and record the outcome on it. Never raises (the worker task wraps it)."""
    connection = SearchConsoleConnection.objects.select_related("site").filter(pk=connection_id).first()
    if connection is None or not is_connected(connection):
        return 0
    try:
        stored = sync(connection)
    except SearchConsoleError as exc:
        SearchConsoleConnection.objects.filter(pk=connection.pk).update(
            last_error=str(exc)[:1000], last_sync_at=timezone.now()
        )
        return 0
    except Exception:
        logger.exception("Search Console sync crashed for connection %s", connection.pk)
        SearchConsoleConnection.objects.filter(pk=connection.pk).update(
            last_error="The last sync hit an unexpected error. It will try again tomorrow.",
            last_sync_at=timezone.now(),
        )
        return 0
    SearchConsoleConnection.objects.filter(pk=connection.pk).update(last_error="", last_sync_at=timezone.now())
    return stored


# ---------------------------------------------------------------------------
# Reading the numbers back
# ---------------------------------------------------------------------------


def page_filter(url: str) -> Q:
    """Rows for one article, whichever form of its address Google reports (www or not, .html or not)."""
    path = urlsplit(url).path.rstrip("/")
    if path.endswith(".html"):
        path = path[: -len(".html")]
    if not path:
        return Q(pk__in=[])
    return Q(page__endswith=path) | Q(page__endswith=path + ".html") | Q(page__endswith=path + "/")


def _totals(rows) -> dict:
    agg = rows.aggregate(clicks=Sum("clicks"), impressions=Sum("impressions"))
    clicks, impressions = int(agg["clicks"] or 0), int(agg["impressions"] or 0)
    position = 0.0
    if impressions:
        weighted = sum(r.position * r.impressions for r in rows.only("position", "impressions"))
        position = weighted / impressions
    return {
        "clicks": clicks,
        "impressions": impressions,
        "ctr": (clicks / impressions) if impressions else 0.0,
        # Google's own page position is impression-weighted like this.
        "position": round(position, 1),
    }


def _top_queries(rows, limit: int) -> list[dict]:
    totals: dict[str, dict] = {}
    for row in rows.only("query", "clicks", "impressions", "position"):
        item = totals.setdefault(row.query, {"query": row.query, "clicks": 0, "impressions": 0, "weighted": 0.0})
        item["clicks"] += row.clicks
        item["impressions"] += row.impressions
        item["weighted"] += row.position * row.impressions
    queries = []
    for item in totals.values():
        impressions = item["impressions"]
        queries.append(
            {
                "query": item["query"],
                "clicks": item["clicks"],
                "impressions": impressions,
                "position": round(item["weighted"] / impressions, 1) if impressions else 0.0,
            }
        )
    queries.sort(key=lambda q: (-q["impressions"], -q["clicks"], q["query"]))
    return queries[:limit]


def page_trend(site: BlogSite, url: str, *, today: dt.date | None = None, queries: int = 5) -> dict:
    """The last 28 days of one article against the 28 before.

    ``position_change`` is how many places it climbed (positive) or slipped
    (negative); None when either window has no impressions.
    """
    today = today or timezone.localdate()
    end = today - dt.timedelta(days=1)
    start = end - dt.timedelta(days=WINDOW_DAYS - 1)
    previous_start = start - dt.timedelta(days=WINDOW_DAYS)
    rows = SearchPerformance.objects.filter(site=site).filter(page_filter(url))
    current = rows.filter(date__gte=start, date__lte=end)
    previous = rows.filter(date__gte=previous_start, date__lt=start)
    now, before = _totals(current), _totals(previous)
    change = None
    if now["impressions"] and before["impressions"]:
        change = round(before["position"] - now["position"], 1)
    return {
        **now,
        "previous_position": before["position"] if before["impressions"] else None,
        "position_change": change,
        "queries": _top_queries(current, queries),
        "start": start,
        "end": end,
    }


def site_overview(site: BlogSite, *, today: dt.date | None = None, pages: int = 5) -> dict:
    """The site's last 28 days: totals and the pages Google showed most."""
    today = today or timezone.localdate()
    end = today - dt.timedelta(days=1)
    start = end - dt.timedelta(days=WINDOW_DAYS - 1)
    rows = SearchPerformance.objects.filter(site=site, date__gte=start, date__lte=end)
    top = (
        rows.values("page")
        .annotate(clicks=Sum("clicks"), impressions=Sum("impressions"))
        .order_by("-impressions", "-clicks", "page")[:pages]
    )
    return {**_totals(rows), "pages": list(top), "start": start, "end": end}
