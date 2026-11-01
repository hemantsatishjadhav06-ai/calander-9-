"""The screen registry: which pages are dark-ready, what each page renders, the rebuilt screens.

One plain module (docs/specs/phase-3.md, "The screen registry"), shared by every Phase 3 guard:
``context_processors.theme_context`` (the ``data-theme-ready`` flag on ``<html>``), recolor's
raw-colour rule, and the spacing, one-primary, inline-confirm and motion guards. It imports nothing
from Django, so ``tools/recolor.py`` can read it without settings.

- ``DARK_READY``: the ``(app_name, url_name)`` pages declared dark-ready. Only their ``<html>``
  carries ``data-theme-ready``, so no page turns dark until its screen's gate declares it.
- ``PAGE_TEMPLATES``: the root templates each page renders (``base.html`` is reached through
  ``{% extends %}``). recolor cannot follow URL → view → template without Django, so this map is how
  it finds a page's tree; ``apps/common/tests/test_screens.py`` renders every entry and checks it
  against the view, so the map cannot drift.
- ``SCREENS``: per rebuilt screen, its root templates, the fragments HTMX loads into its pages, its
  pages, the roles that may open them, and ``gated`` (flipped at its gate).
- ``template_tree(roots)``: the roots and every template they reach through a literal
  ``{% include %}`` or ``{% extends %}`` name; a dynamic include is listed in a screen's ``fragments``.

It grows at each screen's gate.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
#: Where the project's templates live: ``DIRS`` first, then any ``apps/*/templates`` (none today), sorted by
#: path, which is not ``INSTALLED_APPS`` order; ``find_template`` relies on the first only.
TEMPLATE_DIRS: tuple[Path, ...] = (ROOT / "templates", *sorted(ROOT.glob("apps/*/templates")))

#: A page, as ``request.resolver_match`` names it: ``(app_name, url_name)``.
Page = tuple[str, str]

#: The pages declared dark-ready. Empty until a screen's gate declares its pages.
DARK_READY: frozenset[Page] = frozenset()

#: The root templates each page renders, for every page in ``DARK_READY`` or in a screen's ``pages``.
PAGE_TEMPLATES: dict[Page, tuple[str, ...]] = {
    ("studio", "index"): ("studio/index.html",),
    ("calendar", "calendar"): ("calendar/calendar.html",),
}


@dataclass(frozen=True)
class Screen:
    """A rebuilt screen's parts, as the guards read them."""

    templates: tuple[str, ...]
    fragments: tuple[str, ...] = ()
    pages: tuple[Page, ...] = ()
    roles: tuple[str, ...] = ()
    gated: bool = False


#: The rebuilt screens by name (screen 1, ``new_post``, joins at its Start task).
SCREENS: dict[str, Screen] = {}

_COMMENTS_RE = re.compile(r"{%\s*comment\b.*?%}.*?{%\s*endcomment\s*%}|{#[^\n]*?#}", re.S)
_REFERENCE_RE = re.compile(r"""{%\s*(?:include|extends)\s+(["'])([^"']+)\1""")


def find_template(name: str, dirs: Sequence[Path] | None = None) -> Path | None:
    """The file the project's loader would use for *name*, or None (another package's, or none)."""
    for directory in TEMPLATE_DIRS if dirs is None else dirs:
        path = directory / name
        if path.is_file():
            return path
    return None


def template_tree(roots: Iterable[str], dirs: Sequence[Path] | None = None) -> tuple[str, ...]:
    """The roots and every template they reach through a literal include or extends, roots first.

    Comments are skipped; a name in a variable is not followed (list it in a screen's
    ``fragments``); a name no project directory holds (a package's own template) is left out.
    """
    seen: list[str] = []
    queue = list(roots)
    while queue:
        name = queue.pop(0)
        if name in seen:
            continue
        path = find_template(name, dirs)
        if path is None:
            continue
        seen.append(name)
        text = _COMMENTS_RE.sub("", path.read_text(encoding="utf-8"))
        queue.extend(match.group(2) for match in _REFERENCE_RE.finditer(text))
    return tuple(seen)
