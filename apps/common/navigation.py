"""The app's navigation: six places, the Settings gear and the phone bar.

Spec R1 (docs/specs/02-cut-and-merge.md). ``build_nav(request, context)`` turns
the request's resolved URL and the values ``sidebar_context`` has already worked
out for it (the approvals and inbox counts, whether any platform has analytics)
into plain values a template can loop over. It reads nothing else but the
workspace's switches, through ``request_features``, which a request reads once
and shares with the templates' ``features``.

- **Items, in order:** Home, Approvals, Calendar, Inbox, Analytics (only while
  a platform has analytics), Activity, then Blog (only with the ``blog``
  switch). Settings is the gear, kept apart from the items.
- **Phone bar:** Home, Approvals, Calendar, Inbox, and More, a button that
  opens the drawer. More is lit on a place the bar does not show. The post page
  and the composer have none: their own action bar sits where it would.
- **One place is lit**, from ``request.resolver_match``; see ``_place``.
- **The command palette** (``build_palette``) offers the same places, Settings
  and the Settings tabs this person may use.

Activity is ``studio:team`` (its path is ``/studio/activity/``). Approvals and
Settings point at their own screens, or at where that work was done before
those routes existed.

``sidebar_context`` hands templates a lazy ``nav`` and ``nav_palette``: a page
builds them once from the values the context already has, and an HTMX fragment,
which never reads them, never builds them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from django.urls import NoReverseMatch, reverse

from apps.common.features import request_features


@dataclass(frozen=True)
class NavItem:
    """One destination. ``url`` is None for a button (the phone bar's More);
    ``count`` is None for an item that never shows one."""

    key: str
    label: str
    url: str | None
    count: int | None = None
    active: bool = False


@dataclass(frozen=True)
class Nav:
    """The sidebar's items, its gear and the phone bar; empty without a workspace.
    ``phone`` is also empty on a page whose own bar takes the bottom of a phone."""

    items: tuple[NavItem, ...] = ()
    settings: NavItem | None = None
    phone: tuple[NavItem, ...] = ()

    @property
    def active_key(self) -> str | None:
        """The lit place: an item's key, ``"settings"``, or None."""
        lit = [item.key for item in (*self.items, *filter(None, [self.settings])) if item.active]
        return lit[0] if lit else None


# Activity: the team at work, a job, the routines, and the actions on them that
# answer with their page (a routine that fails to save shows the form again).
_ACTIVITY = frozenset({"activity", "team", "team_board", "job", "routines", "routines_create"})

# Settings that still have their own page in the agency, and the actions on
# them that answer with that page (a house style or upload that fails to save).
_AGENCY_SETTINGS = frozenset(
    {
        "setup",
        "settings_hub",
        "brand",
        "autopilot",
        "trust",
        "memory",
        "memory_house_style",
        "memory_upload",
        "outcomes",
    }
)

# Apps where every page is a setting: the Settings screen, members, the
# client-portal admin, connected accounts and Telegram.
_SETTINGS_APPS = frozenset({"settings", "members", "client_portal_admin", "social_accounts", "telegram"})

# Settings pages inside apps that also hold other pages.
_SETTINGS_PAGES = frozenset(
    {
        ("workspaces", "settings"),
        ("workspaces", "approvals_settings"),
        ("notifications", "preferences"),
    }
)

# The phone bar shows these items; More stands for the rest.
_PHONE_KEYS = ("home", "approvals", "calendar", "inbox")

# Pages with a bar of their own along the bottom of a phone, which the phone bar
# would cover: the post page's Approve & schedule (studio/detail.html) and the
# composer's action bar (composer/compose.html, which fills the screen).
_NO_PHONE_BAR = frozenset({("studio", "detail"), ("composer", "compose"), ("composer", "compose_edit")})

# Screens that refuse a plain client (they approve in the client portal): the
# agency's pages (``studio.views._workspace``), Approvals and Settings.
_REFUSED_TO_CLIENTS = frozenset({"home", "approvals", "activity", "settings"})


def _place(app: str, name: str, tab: str | None) -> str | None:
    """The key of the place a page belongs to, or None for a page outside them."""
    if app == "studio":
        if name in _ACTIVITY:
            return "activity"
        if name in _AGENCY_SETTINGS:
            return "settings"
        return "home"
    if app in _SETTINGS_APPS or (app, name) in _SETTINGS_PAGES:
        return "settings"
    if app == "approvals":
        return "approvals"
    if app == "calendar":
        return "approvals" if name == "calendar" and tab == "approvals" else "calendar"
    if app in {"inbox", "analytics", "blog"}:
        return app
    return None


def _lit_place(request) -> str | None:
    match = getattr(request, "resolver_match", None)
    if match is None:
        return None
    return _place(match.app_name, match.url_name or "", request.GET.get("tab"))


def _has_phone_bar(request) -> bool:
    match = getattr(request, "resolver_match", None)
    return match is None or (match.app_name, match.url_name) not in _NO_PHONE_BAR


def _new_or_today(workspace_id, new: str, today: str, query: str = "") -> str:
    """*new*'s URL once its route exists, else *today*'s with *query*."""
    kwargs = {"workspace_id": workspace_id}
    try:
        return reverse(new, kwargs=kwargs)
    except NoReverseMatch:
        return reverse(today, kwargs=kwargs) + query


def _count(context: Mapping[str, Any], key: str) -> int:
    return int(context.get(key) or 0)


def build_nav(request, context: Mapping[str, Any] | None = None) -> Nav:
    """The navigation for *request*.

    *context* is what ``sidebar_context`` returned for this request; its counts
    are reused, never queried again. Without it, ``sidebar_context`` is called,
    so a caller that already has the context should pass it.
    """
    workspace = getattr(request, "workspace", None)
    if workspace is None:
        return Nav()
    if context is None:
        from apps.common.context_processors import sidebar_context

        context = sidebar_context(request)

    ws = workspace.id
    kwargs = {"workspace_id": ws}
    places: list[tuple[str, str, str, int | None]] = [
        ("home", "Home", reverse("studio:index", kwargs=kwargs), None),
        (
            "approvals",
            "Approvals",
            _new_or_today(ws, "approvals:index", "calendar:calendar", "?mode=list&tab=approvals"),
            _count(context, "sidebar_pending_approvals"),
        ),
        ("calendar", "Calendar", reverse("calendar:calendar", kwargs=kwargs), None),
        ("inbox", "Inbox", reverse("inbox:feed", kwargs=kwargs), _count(context, "sidebar_unread_inbox_count")),
    ]
    if context.get("analytics_enabled_platforms"):
        places.append(("analytics", "Analytics", reverse("analytics:index", kwargs=kwargs), None))
    places.append(("activity", "Activity", reverse("studio:team", kwargs=kwargs), None))
    if request_features(request)["blog"]:
        places.append(("blog", "Blog", reverse("blog:list", kwargs=kwargs), None))

    lit = _lit_place(request)
    items = tuple(NavItem(key, label, url, count, key == lit) for key, label, url, count in places)
    settings = NavItem(
        "settings", "Settings", _new_or_today(ws, "settings:index", "studio:setup"), None, lit == "settings"
    )

    shown = {item.key for item in items} | {"settings"}
    more = NavItem("more", "More", None, None, lit in shown and lit not in _PHONE_KEYS)
    phone = (*(item for item in items if item.key in _PHONE_KEYS), more) if _has_phone_bar(request) else ()
    return Nav(items=items, settings=settings, phone=phone)


@dataclass(frozen=True)
class PaletteEntry:
    """One destination in the command palette. ``section`` names where it lives
    (``"Settings"`` for a Settings tab), and is searched with the label."""

    key: str
    label: str
    url: str
    section: str = ""

    @property
    def search(self) -> str:
        return f"{self.label} {self.section}".strip().lower()


def build_palette(request, nav: Nav) -> tuple[PaletteEntry, ...]:
    """The places *nav* shows, then Settings and the tabs the Settings screen
    would show this person (its own checks, ``views_settings.usable_tabs``).

    A plain client is offered none of the screens that refuse them, and so no
    Settings tab. Reading the tabs' checks costs at most one query, and only
    when a page renders the palette.
    """
    if not nav.items:
        return ()
    from apps.studio.views import is_plain_client

    membership = getattr(request, "workspace_membership", None)
    client = is_plain_client(membership)
    entries = [
        PaletteEntry(item.key, item.label, item.url or "")
        for item in nav.items
        if not (client and item.key in _REFUSED_TO_CLIENTS)
    ]
    if client or membership is None or nav.settings is None:
        return tuple(entries)

    from apps.studio.settings_links import tab_url
    from apps.studio.views_settings import usable_tabs

    workspace = request.workspace
    tabs = usable_tabs(request)
    if tabs:
        entries.append(PaletteEntry("settings", nav.settings.label, nav.settings.url or ""))
        entries.extend(
            PaletteEntry(f"settings-{tab.key}", tab.label, tab_url(workspace.id, tab.key), "Settings") for tab in tabs
        )
    return tuple(entries)
