"""Addresses on the Settings screen, and the 301 that moves an old settings page there (spec D1, D5).

``tab_url`` builds ``/workspace/<id>/settings/?tab=<key>`` (tabs are a query, never a path part).
``moved`` is what an old settings page answers to a GET once it has applied its own login,
permission and workspace checks: a permanent redirect to its tab, carrying the query values that
select something on it (``?claim=``, ``?open=``) and the section's anchor. POSTs never come here.
A move that lasts only while a switch is on says ``cacheable=False``: browsers keep a 301 for good
otherwise, and would never see the page again once the switch is turned off.

``returning_to`` is the other way: a form in a Settings tab that posts to an old page's handler
sends the tab's address as ``next``, and the handler goes back there (only to this workspace's
Settings screen) instead of to its old page.

This module imports nothing from the views, so every old page can use it without an import cycle.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urlsplit

from django.http import HttpRequest, HttpResponsePermanentRedirect
from django.urls import reverse
from django.utils.cache import add_never_cache_headers
from django.utils.http import url_has_allowed_host_and_scheme

#: Query values that select something on an old page; they travel with the redirect.
CARRIED = ("claim", "open")


def tab_url(workspace_id, tab: str, *, query: dict[str, str] | None = None, anchor: str = "") -> str:
    """The Settings screen open at *tab*, with *query* after it and *anchor* at the end."""
    url = reverse("settings:index", kwargs={"workspace_id": workspace_id})
    url = f"{url}?{urlencode([('tab', tab), *(query or {}).items()])}"
    return f"{url}#{anchor}" if anchor else url


def is_page_view(request: HttpRequest) -> bool:
    """A request for the page itself (GET or HEAD), the only kind an old page moves."""
    return request.method in ("GET", "HEAD")


def moved(
    request: HttpRequest, workspace_id, tab: str, *, anchor: str = "", cacheable: bool = True
) -> HttpResponsePermanentRedirect:
    """301 to *tab*, carrying ``CARRIED`` query values. Call it only after the page's own checks.

    ``cacheable=False`` (a move that depends on a switch) adds the never-cache headers.
    """
    carried = {key: request.GET[key] for key in CARRIED if request.GET.get(key)}
    response = HttpResponsePermanentRedirect(tab_url(workspace_id, tab, query=carried, anchor=anchor))
    if not cacheable:
        add_never_cache_headers(response)
    return response


def returning_to(request: HttpRequest, workspace_id) -> str | None:
    """The Settings tab a form was sent from (its ``next``), or None to keep the handler's own page.

    Only a path on this site to this workspace's Settings screen is taken; anything else (another
    host, another workspace, another page) is ignored, so the handler answers exactly as it did
    before. The address is rebuilt from its ``tab`` alone, never echoed back.
    """
    destination = request.POST.get("next", "")
    if not destination or not url_has_allowed_host_and_scheme(
        destination, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return None
    parts = urlsplit(destination)
    if parts.scheme or parts.netloc:
        return None
    if parts.path != reverse("settings:index", kwargs={"workspace_id": workspace_id}):
        return None
    tab = parse_qs(parts.query).get("tab", [""])[0]
    if not re.fullmatch(r"[a-z_]{1,32}", tab):
        return reverse("settings:index", kwargs={"workspace_id": workspace_id})
    return tab_url(workspace_id, tab)
