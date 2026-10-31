"""Addresses on the Settings screen, and the 301 that moves an old settings page there (spec D1, D5).

``tab_url`` builds ``/workspace/<id>/settings/?tab=<key>`` (tabs are a query, never a path part).
``moved`` is what an old settings page answers to a GET once it has applied its own login,
permission and workspace checks: a permanent redirect to its tab, carrying the query values that
select something on it (``?claim=``, ``?open=``) and the section's anchor. POSTs never come here.
A move that lasts only while a switch is on says ``cacheable=False``: browsers keep a 301 for good
otherwise, and would never see the page again once the switch is turned off.

This module imports nothing from the views, so every old page can use it without an import cycle.
"""

from __future__ import annotations

from urllib.parse import urlencode

from django.http import HttpRequest, HttpResponsePermanentRedirect
from django.urls import reverse
from django.utils.cache import add_never_cache_headers

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
