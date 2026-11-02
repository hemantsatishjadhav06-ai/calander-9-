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
  ``{% include %}`` or ``{% extends %}`` name, or through an inclusion tag's use (``{% ui_select %}``
  renders ``components/ui_select.html``); a dynamic include is listed in a screen's ``fragments``.
- ``inclusion_tags()``: those tags, ``{tag name: template}``, read with ``ast`` from every
  ``@register.inclusion_tag("…")`` in ``apps/*/templatetags/`` (a ``filename=`` keyword and a ``name=``
  override too); a form it cannot read raises, so no tag's template goes unseen. A tag that picks its
  template at run time (a simple tag that renders one itself, a compiled ``register.tag``) cannot be
  followed: list that template in its screen's ``fragments``, as a dynamic include is.

It grows at each screen's gate.
"""

from __future__ import annotations

import ast
import functools
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
#: Where the project's templates live: ``DIRS`` first, then any ``apps/*/templates`` (none today), sorted by
#: path, which is not ``INSTALLED_APPS`` order; ``find_template`` relies on the first only.
TEMPLATE_DIRS: tuple[Path, ...] = (ROOT / "templates", *sorted(ROOT.glob("apps/*/templates")))
#: The project's template tag libraries, where ``inclusion_tags`` reads which template each tag renders.
TAG_FILES: tuple[Path, ...] = tuple(sorted(ROOT.glob("apps/*/templatetags/*.py")))

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
#: Any tag's name; ``template_tree`` follows the ones ``inclusion_tags`` maps.
_TAG_RE = re.compile(r"{%\s*(\w+)")


def find_template(name: str, dirs: Sequence[Path] | None = None) -> Path | None:
    """The file the project's loader would use for *name*, or None (another package's, or none)."""
    for directory in TEMPLATE_DIRS if dirs is None else dirs:
        path = directory / name
        if path.is_file():
            return path
    return None


def _literal(node: ast.expr | None, path: Path, what: str) -> str:
    """The string *node* holds, or a ``ValueError`` naming the file and line: the tree cannot follow it."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    line = getattr(node, "lineno", "?")
    raise ValueError(
        f"{path}:{line}: an inclusion tag's {what} is not a literal string, so template_tree cannot follow it"
    )


def _inclusion_tag(call: ast.Call, function: str, path: Path) -> tuple[str, str]:
    """``(tag name, template)`` for ``register.inclusion_tag(…)`` applied to *function*.

    Reads the forms Django accepts by keyword or as the first argument: the template as the first
    argument or ``filename=``, the tag's name from ``name=`` or else the function's. Other keywords
    (``takes_context``) do not change the template. Any other positional argument is refused.
    """
    if len(call.args) > 1:
        raise ValueError(
            f"{path}:{call.lineno}: inclusion_tag with more than one positional argument; pass them by keyword"
        )
    keywords = {keyword.arg: keyword.value for keyword in call.keywords}
    if None in keywords:
        raise ValueError(f"{path}:{call.lineno}: inclusion_tag with **kwargs; template_tree cannot read its template")
    template = call.args[0] if call.args else keywords.get("filename")
    if template is None:
        raise ValueError(f"{path}:{call.lineno}: inclusion_tag without a template")
    name = _literal(keywords["name"], path, "name") if "name" in keywords else function
    return name, _literal(template, path, "template")


def inclusion_tags(files: Iterable[Path] | None = None) -> dict[str, str]:
    """``{tag name: template}`` for every ``inclusion_tag`` in *files* (default: the project's ``TAG_FILES``).

    Read with ``ast``, never imported, so it needs no settings. It reads the decorator
    (``@register.inclusion_tag("t.html")``, ``filename=``, ``name=``, ``takes_context=``) and the call
    form (``register.inclusion_tag("t.html")(function)``), and raises ``ValueError`` (with the file and
    line) on any other use: a template or name that is not a literal string, an ``inclusion_tag`` it
    cannot tie to a function, or one tag name for two templates (a page's ``{% load %}`` order would
    pick). A tag that renders a template chosen at run time is not an ``inclusion_tag`` and is not seen
    here: list its templates in the screen's ``fragments``.
    """
    if files is None:
        return dict(_project_tags())
    tags: dict[str, str] = {}
    where: dict[str, str] = {}
    for path in files:
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        parents = {child: parent for parent in ast.walk(module) for child in ast.iter_child_nodes(parent)}
        for node in ast.walk(module):
            if not (isinstance(node, ast.Attribute) and node.attr == "inclusion_tag"):
                continue
            call = parents.get(node)
            if not (isinstance(call, ast.Call) and call.func is node):
                raise ValueError(f"{path}:{node.lineno}: inclusion_tag used without its template")
            holder = parents.get(call)
            if isinstance(holder, ast.FunctionDef | ast.AsyncFunctionDef) and call in holder.decorator_list:
                function = holder.name
            elif isinstance(holder, ast.Call) and holder.func is call and len(holder.args) == 1 and not holder.keywords:
                if not isinstance(holder.args[0], ast.Name):
                    raise ValueError(
                        f"{path}:{holder.lineno}: inclusion_tag applied to something that is not a function's name"
                    )
                function = holder.args[0].id
            else:
                raise ValueError(
                    f"{path}:{call.lineno}: inclusion_tag that is neither a decorator nor applied to a function"
                )
            name, template = _inclusion_tag(call, function, path)
            if tags.get(name, template) != template:
                raise ValueError(
                    f"{path}:{call.lineno}: inclusion tag {name!r} renders {template!r} here and {tags[name]!r} in"
                    f" {where[name]}; which one a page gets depends on its {{% load %}} order"
                )
            tags[name] = template
            where[name] = f"{path}:{call.lineno}"
    return tags


@functools.cache
def _project_tags() -> tuple[tuple[str, str], ...]:
    """The project's own inclusion tags, read once per process."""
    return tuple(sorted(inclusion_tags(TAG_FILES).items()))


def template_tree(
    roots: Iterable[str], dirs: Sequence[Path] | None = None, tags: Mapping[str, str] | None = None
) -> tuple[str, ...]:
    """The roots and every template they reach, roots first.

    A template is reached through a literal include or extends name, or through the use of an
    inclusion tag in *tags* (default: the project's, from ``inclusion_tags()``), which reaches the
    template that tag renders; each reached template is read in turn, so its own includes and tags
    are followed too. Comments are skipped; a name in a variable is not followed, nor a tag that
    picks its template at run time (list either in a screen's ``fragments``); a name no project
    directory holds (a package's own template) is left out.
    """
    tags = inclusion_tags() if tags is None else tags
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
        # In the order the template names them: its literal includes and extends, and its tags' templates.
        found = [(match.start(), match.group(2)) for match in _REFERENCE_RE.finditer(text)]
        found += [(match.start(), tags[match.group(1)]) for match in _TAG_RE.finditer(text) if match.group(1) in tags]
        queue.extend(reached for _, reached in sorted(found))
    return tuple(seen)
