"""Hash the tests that enforce CLAUDE.md's invariants, so Phase 3 cannot edit them unseen (spec D11).

``tests/fixtures/protected_tests.json`` lists D11's tests by node id, with the SHA-256 of each one's
source on ``045978b``, written once and never regenerated in Phase 3. ``tests/test_protected_tests.py``
recomputes every hash from the working tree (no git history, so it runs in CI's shallow checkout).

A node id is either

- ``path::name`` or ``path::Class::name``: the test's own source, from its first decorator to its
  last line, found with ``ast``; an edit beside it (another test, a helper, lines above it) leaves
  its hash alone, while one character changed inside it, or a decorator added, changes it; or
- ``path`` alone: the whole file, for files D11 protects whole (the golden browser specs among them).

Usage::

    python tools/protected_tests.py                  # each fixture node's hash, from the working tree
    python tools/protected_tests.py --check          # exit 1 and name every node that changed
    python tools/protected_tests.py --ref 045978b    # the hashes on a commit (how the fixture was written)
    python tools/protected_tests.py --json NODE ...  # only these nodes, as the fixture's "nodes" map
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "protected_tests.json"

Reader = Callable[[str], bytes]


def _split(node: str) -> tuple[str, list[str]]:
    path, *names = node.split("::")
    return path, [name.split("[", 1)[0] for name in names]


def node_source(text: str, names: list[str]) -> str:
    """The source of the function or class *names* reaches in *text*, decorators included."""
    body: list[ast.stmt] = ast.parse(text).body
    found: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | None = None
    for name in names:
        matches = [
            stmt
            for stmt in body
            if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) and stmt.name == name
        ]
        if not matches:
            raise LookupError(name)
        found = matches[-1]  # a later definition replaces an earlier one, for Python and pytest alike
        body = found.body
    if found is None:
        raise LookupError("no test named")
    start = min([found.lineno, *(decorator.lineno for decorator in found.decorator_list)])
    end = found.end_lineno or found.lineno
    return "\n".join(text.splitlines()[start - 1 : end])


def _working_tree(root: Path) -> Reader:
    return lambda path: (root / path).read_bytes()


def _commit(ref: str, root: Path = ROOT) -> Reader:
    def read(path: str) -> bytes:
        return subprocess.run(["git", "show", f"{ref}:{path}"], cwd=root, capture_output=True, check=True).stdout

    return read


def digest(node: str, root: Path = ROOT, read: Reader | None = None) -> str:
    """The SHA-256 of *node*'s source: the test's own lines, or the whole file for a bare path."""
    path, names = _split(node)
    data = (read or _working_tree(root))(path)
    if names:
        data = node_source(data.decode("utf-8"), names).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def changed(expected: Mapping[str, str], root: Path = ROOT) -> list[str]:
    """The nodes whose source no longer hashes as *expected* (or is gone), in the fixture's order."""
    different = []
    for node, sha in expected.items():
        try:
            same = digest(node, root) == sha
        except (OSError, LookupError, SyntaxError, UnicodeDecodeError):
            same = False
        if not same:
            different.append(node)
    return different


def load(fixture: Path = FIXTURE) -> dict[str, str]:
    return dict(json.loads(fixture.read_text(encoding="utf-8"))["nodes"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hash the tests that enforce the invariants (spec D11).")
    parser.add_argument("nodes", nargs="*", help="node ids (default: the fixture's)")
    parser.add_argument("--root", type=Path, default=ROOT, help="the tree to read (default: this repository)")
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--ref", help="read the sources from this commit instead of the working tree")
    parser.add_argument("--check", action="store_true", help="compare with the fixture; exit 1 on any change")
    parser.add_argument("--json", action="store_true", help='print {"node": "sha256", ...}')
    args = parser.parse_args(argv)

    if args.check:
        different = changed(load(args.fixture), args.root)
        for node in different:
            print(f"changed: {node}")
        print("protected tests: " + (f"{len(different)} changed" if different else "unchanged"))
        return 1 if different else 0

    nodes = args.nodes or list(load(args.fixture))
    read = _commit(args.ref, args.root) if args.ref else _working_tree(args.root)
    hashes = {node: digest(node, args.root, read) for node in nodes}
    if args.json:
        print(json.dumps(hashes, indent=2))
    else:
        for node, sha in hashes.items():
            print(f"{sha}  {node}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
