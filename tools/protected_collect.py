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
  package (``override_settings``, ``mock.patch``), rather than something written in the repository.

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
    code = getattr(function, "__code__", None)
    from_library = (
        definition is not function
        and code is not None
        and str(Path(code.co_filename).resolve()).startswith(tuple(library + os.sep for library in _libraries))
    )
    return {
        "nodeid": item.nodeid,
        "path": _name(str(item.path), root),
        "name": getattr(item, "originalname", item.name),
        "markers": sorted(marks),
        "code": _code(function, root),
        "definition": _code(definition, root),
        "wrapper_from_library": from_library,
    }


@pytest.hookimpl(trylast=True)
def pytest_collection_finish(session: pytest.Session) -> None:
    out = os.environ.get(OUT)
    if not out:
        return
    root = session.config.rootpath
    payload = {"items": [_record(item, root) for item in session.items], "deselected": _deselected}
    Path(out).write_text(json.dumps(payload, indent=1), encoding="utf-8")
