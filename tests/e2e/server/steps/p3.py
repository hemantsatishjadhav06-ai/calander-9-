"""Steps for the Phase 3 specs (docs/specs/phase-3.md).

Fixtures:

- ``dark_ready``: declares pages dark-ready in this process, the way ``fakes.py`` puts its stand-ins in
  place: it replaces ``apps.common.screens.DARK_READY``, which ``context_processors.theme_context``
  reads on every render, so the next request for a declared page carries ``data-theme-ready`` on
  ``<html>``. ``{"add": ["app_name:url_name", …]}`` adds pages to the set; ``{"clear": true}`` puts
  back the registry's own set (the pages the code declares, as the server started with them);
  both together clear first. Answers the set as ``{"ready": ["app_name:url_name", …]}``, sorted.
  A spec that adds a page clears it after each test (``test.afterEach``), so no other spec meets it.
"""

from __future__ import annotations

from typing import Any

from apps.common import screens

from ..registry import PayloadError, fixture

#: The registry's own declared pages, as this process started with them.
DECLARED: frozenset[screens.Page] = screens.DARK_READY

_KEYS = frozenset({"add", "clear"})


def _page(name: Any) -> screens.Page:
    """``"app_name:url_name"`` as a page, refused unless the URL conf has that name."""
    from django.urls import get_resolver

    if not isinstance(name, str) or name.count(":") < 1:
        raise PayloadError(f"Each page in 'add' is 'app_name:url_name', like 'accounts:settings'; got {name!r}.")
    app_name, _, url_name = name.rpartition(":")
    resolver = get_resolver()
    for namespace in app_name.split(":"):
        if namespace not in resolver.namespace_dict:
            raise PayloadError(f"No URL namespace {namespace!r} (in {name!r}).")
        resolver = resolver.namespace_dict[namespace][1]
    if not url_name or url_name not in resolver.reverse_dict:
        raise PayloadError(f"No URL named {name!r}.")
    return (app_name, url_name)


@fixture("dark_ready")
def dark_ready(payload: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(payload) - _KEYS)
    if unknown:
        raise PayloadError(f"Unknown key(s) {', '.join(unknown)}; use 'add' and 'clear'.")
    clear = payload.get("clear", False)
    if not isinstance(clear, bool):
        raise PayloadError("'clear' must be true or false.")
    add = payload.get("add")
    if add is not None and (not isinstance(add, list) or not add):
        raise PayloadError("'add' must be a non-empty list of 'app_name:url_name'.")
    if not clear and add is None:
        raise PayloadError('Say what to do: {"add": ["app_name:url_name", …]} or {"clear": true}.')
    pages = frozenset(_page(name) for name in add or ())

    ready = (DECLARED if clear else screens.DARK_READY) | pages
    screens.DARK_READY = ready
    return {"ready": sorted(f"{app_name}:{url_name}" for app_name, url_name in ready)}
