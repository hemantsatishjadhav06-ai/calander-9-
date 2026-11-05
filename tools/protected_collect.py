"""A pytest plugin for the protected-test guard's collection check (spec D11).

``tools/protected_tests.collected`` loads it (``-p protected_collect``, with this directory on
``PYTHONPATH``) into one ``pytest --collect-only`` run from the rootdir; the suite itself never loads
it. Given the protected files (``PROTECTED_COLLECT_FILES``: one path per line, relative to the
rootdir), it ignores every other file, so the run walks the same directories as the full suite, loads
every ``conftest.py`` and applies every ``collect_ignore``, ``--ignore``, ``norecursedirs`` and
deselection as the suite would, while importing only the protected modules. When collection ends it
writes, as JSON, to the path in ``PROTECTED_COLLECT_OUT``: the node ids that were deselected, and each
item that survived from those files with

- ``markers``: the name of every mark on it (``item.iter_markers()``, so class and module marks too),
  plus ``unittest_skip`` and ``unittest_expecting_failure`` for unittest's own decorators;
- ``code``: ``[file, co_name, co_firstlineno]`` of the function pytest would call;
- ``definition``: the same for that function unwrapped (``inspect.unwrap``), the def it decorates;
- ``wrapper_from_library``: whether ``code`` is a wrapper from the standard library or an installed
  package (``override_settings``, ``mock.patch``), rather than something written in the repository;
- ``fixtures``: each fixture it uses that its own module or one of its classes registers (the
  fixture's ``baseid`` is in its file: overrides, autouse fixtures, imported ones), as ``name`` and the
  ``code`` of the function that runs; for a wrapper written in a library (pytest's xunit
  ``setup_method`` and ``setup_function`` fixtures), the functions it closes over instead.

Files under the rootdir are named relative to it; others by their absolute path.
"""

from __future__ import annotations

import inspect
import json
import os
import sysconfig
from pathlib import Path
from typing import Any

import pytest

FILES = "PROTECTED_COLLECT_FILES"
OUT = "PROTECTED_COLLECT_OUT"

_protected: set[Path] = set()
_deselected: list[str] = []
_libraries = tuple(
    {str(Path(sysconfig.get_paths()[key]).resolve()) for key in ("stdlib", "platstdlib", "purelib", "platlib")}
)


def pytest_configure(config: pytest.Config) -> None:
    root = config.rootpath
    _protected.update((root / line).resolve() for line in os.environ.get(FILES, "").splitlines() if line.strip())


@pytest.hookimpl(tryfirst=True)
def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    """Skip every unprotected file; leave directories and protected files to the usual rules."""
    if collection_path.is_dir() or collection_path.resolve() in _protected:
        return None
    return True


def pytest_deselected(items: list[pytest.Item]) -> None:
    _deselected.extend(item.nodeid for item in items)


def _name(filename: str, root: Path) -> str:
    resolved = Path(filename).resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _code(function: Any, root: Path) -> list[Any]:
    code = getattr(function, "__code__", None)
    if code is None:
        return [None, type(function).__name__, None]
    return [_name(code.co_filename, root), code.co_name, code.co_firstlineno]


def _from_library(function: Any) -> bool:
    code = getattr(function, "__code__", None)
    return code is not None and str(Path(code.co_filename).resolve()).startswith(
        tuple(library + os.sep for library in _libraries)
    )


def _fixture_functions(fixture: Any) -> list[Any]:
    """The functions a fixture runs: its own, or, for a wrapper written in a library (pytest's xunit
    ``setup_method``, ``setup_function`` and the like), the functions it closes over."""
    function = inspect.unwrap(getattr(fixture, "__func__", fixture))
    if not _from_library(function):
        return [function]
    inner = []
    for cell in getattr(function, "__closure__", None) or ():
        try:
            value = cell.cell_contents
        except ValueError:  # an empty cell
            continue
        value = getattr(value, "__func__", value)  # a bound method or classmethod
        if callable(value) and hasattr(value, "__code__"):
            inner.append(inspect.unwrap(value))
    return inner or [function]


def _own_fixtures(item: pytest.Item, root: Path) -> list[dict[str, Any]]:
    """The fixtures *item* uses that its own module or one of its classes registers, overrides included."""
    module = item.nodeid.split("::", 1)[0]
    info = getattr(item, "_fixtureinfo", None)
    found: list[dict[str, Any]] = []
    for name, fixturedefs in info.name2fixturedefs.items() if info is not None else ():
        for fixturedef in fixturedefs:
            if fixturedef.baseid.split("::", 1)[0] != module:
                continue  # a conftest's or a plugin's
            found.extend(
                {"name": name, "code": _code(function, root)} for function in _fixture_functions(fixturedef.func)
            )
    return found


def _record(item: pytest.Item, root: Path) -> dict[str, Any]:
    obj = getattr(item, "obj", None)
    function = getattr(obj, "__func__", obj)
    definition = inspect.unwrap(function) if callable(function) else function
    owner = getattr(item, "cls", None)
    marks = {mark.name for mark in item.iter_markers()}
    if getattr(function, "__unittest_skip__", False) or getattr(owner, "__unittest_skip__", False):
        marks.add("unittest_skip")
    if getattr(function, "__unittest_expecting_failure__", False):
        marks.add("unittest_expecting_failure")
    from_library = definition is not function and _from_library(function)
    return {
        "nodeid": item.nodeid,
        "path": _name(str(item.path), root),
        "name": getattr(item, "originalname", item.name),
        "markers": sorted(marks),
        "code": _code(function, root),
        "definition": _code(definition, root),
        "wrapper_from_library": from_library,
        "fixtures": _own_fixtures(item, root),
    }


@pytest.hookimpl(trylast=True)
def pytest_collection_finish(session: pytest.Session) -> None:
    out = os.environ.get(OUT)
    if not out:
        return
    root = session.config.rootpath
    payload = {"items": [_record(item, root) for item in session.items], "deselected": _deselected}
    Path(out).write_text(json.dumps(payload, indent=1), encoding="utf-8")
