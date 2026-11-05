"""Guard the tests that enforce CLAUDE.md's invariants, so Phase 3 cannot edit them unseen or turn them off (spec D11).

Three checks, each from the working tree (no git history, so they run in CI's shallow checkout);
``tests/test_protected_tests.py`` runs all three.

1. **Own source.** ``tests/fixtures/protected_tests.json`` lists D11's tests by node id, with the
   SHA-256 of each one's source on ``045978b``, written once and never regenerated in Phase 3. A node
   id is either

   - ``path::name`` or ``path::Class::name``: the test's own source, from its first decorator to its
     last line, found with ``ast``; an edit beside it (another test, a helper, lines above it) leaves
     its hash alone, while one character changed inside it, or a decorator added, changes it; or
   - ``path`` alone: the whole file, for files D11 protects whole (the golden browser specs among them).

2. **Context.** ``tests/fixtures/protected_context.json`` holds, for every per-test node, the SHA-256 of
   what in its own file decides, from outside its own source, whether and how it runs, also written
   from ``045978b``. Its module part: every module-level statement other than the node's own
   definition (or the class around it) that touches ``pytestmark`` or ``pytest_plugins`` or names the
   node or a class around it, as an identifier, an attribute or a string (so a later rebinding,
   ``del``, ``setattr`` or ``__code__`` swap); the module-level fixtures (autouse or not: a module's
   fixture overrides a conftest fixture of the same name); and the xunit module and function setup and
   teardown. Its class part, for every ``path::Class::name`` node: the enclosing class's header
   (decorators and bases) and every statement of its body that is not a test (fixtures,
   ``setup_method`` and the like, attributes, ``pytestmark``, ``__test__``, an assignment or ``del`` of
   the node's name, every other method). In a file pytest does not collect (``live_verify``'s
   ``Command``) nothing is a test, so the class part is every statement but the node's own def; there
   the context is all that guards the node beyond its own source, since collection never sees the file.
   A fixture is a function under a decorator whose callee is ``fixture`` (``@pytest.fixture``,
   ``@fixture(...)``) or under any decorator called with ``autouse=``; a ``test_*`` function under
   anything else (``@pytest.mark.usefixtures(...)`` among them) is a test. Nothing, when a node has
   none of these. A neighbouring test added or edited leaves it alone, unless it names the node.

3. **Collection.** :func:`collection_problems` runs pytest's own collection once, from the rootdir with
   the suite's settings (``pyproject.toml``), through ``tools/protected_collect.py``, which ignores
   every unprotected file: only the protected modules are imported, while every ``conftest.py``,
   ``collect_ignore``, ``--ignore`` and deselection applies as in the full run. It reports a per-test
   node not collected exactly once; a test function defined in a whole-file entry (module ``test_*``
   functions, ``test_*`` methods of ``Test*`` classes, ``test*`` methods of ``TestCase`` classes) that
   is not collected; a protected item deselected, one parametrized case among others included (``-k``,
   ``--deselect``, a hook that reports it through ``pytest_deselected``); a node id pinned in
   ``tests/fixtures/protected_collected.json`` that is not collected now (every item collected from the
   protected tests on ``045978b``, written once from a clean checkout of it with ``--collected``: a case
   a hook removes without reporting it, renames or drops fails, while ids added beside them pass); a
   protected item marked skip, skipif or xfail (or unittest's skip or expectedFailure); a protected item
   whose collected function is not the def the hash covers (a later rebinding, a lambda, a wrapper
   written in the repository; a ``__code__`` swapped in place keeps the name and line it compares, and
   the context's module part holds the statement that swaps it); and a per-test node that uses a
   fixture its own module or class registers whose function the context does not hash (one under an
   alias of ``pytest.fixture``, one imported from another file, an xunit hook bound by assignment).

Outside the guard: code outside the protected files, and names built at run time. A ``conftest.py``
that skips at run time (a ``pytest_runtest_setup`` hook, an autouse fixture, a fixture the test
requests), the code of a plugin or helper module a protected file loads (the ``pytest_plugins`` line or
import that loads it is hashed, its own code is not), another module that reaches into a protected one,
a statement that builds a protected name from parts (``globals()["test_" + rest]``), and the value a
parametrized case takes from code outside its file (its id is pinned, the value is not) are not hashed;
the collection check sees only what collection decides.

Usage::

    python tools/protected_tests.py                  # each fixture node's hash, from the working tree
    python tools/protected_tests.py --check          # exit 1 and name every node that changed
    python tools/protected_tests.py --ref 045978b    # the hashes on a commit (how the fixture was written)
    python tools/protected_tests.py --json NODE ...  # only these nodes, as the fixture's "nodes" map
    python tools/protected_tests.py --context ...    # the same, for each per-test node's context
    python tools/protected_tests.py --collect        # exit 1 and print every collection problem
    python tools/protected_tests.py --collected --root CHECKOUT --ref 045978b
                                                     # the ids protected_collected.json pins, from a
                                                     # clean checkout of that commit
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "protected_tests.json"
CONTEXT = ROOT / "tests" / "fixtures" / "protected_context.json"
COLLECTED = ROOT / "tests" / "fixtures" / "protected_collected.json"
COLLECTED_ABOUT = (
    "Spec D11 (docs/specs/03-rebuild-screens.md): every node id pytest collected from the protected Python "
    "tests of protected_tests.json on the ref below (each item of a whole-file entry and each case of a "
    "per-test node, not their unprotected neighbours), in collection order, with the suite's settings, "
    "through tools/protected_collect.py; none was deselected or marked skip, skipif or xfail. Written once "
    "from a clean checkout of the ref with tools/protected_tests.py --collected --root <checkout> --ref <ref>; "
    "never regenerated in Phase 3. tests/test_protected_tests.py requires every id to be collected from the "
    "working tree, so a parametrized case removed (by a hook that reports it as deselected or not, or by -k), "
    "renamed or dropped fails; an id added beside them is allowed."
)

#: pyproject.toml's ``python_files``, ``python_classes`` and ``python_functions`` (a test keeps them equal).
TEST_FILES = ("tests.py", "test_*.py")
TEST_CLASSES = ("Test*",)
TEST_FUNCTIONS = ("test_*",)
#: Module-level functions pytest and unittest run around a module's tests.
MODULE_HOOKS = frozenset(
    {"setup_module", "teardown_module", "setup_function", "teardown_function", "setUpModule", "tearDownModule"}
)
#: Module-level names that decide whether and how a module's tests run: its marks, and the plugins it
#: loads (whose hooks can skip at run time, which collection never sees).
MODULE_SWITCHES = frozenset({"pytestmark", "pytest_plugins"})
#: Marks that turn a test off or excuse its failure (the last two are unittest's own decorators).
OFF_MARKS = frozenset({"skip", "skipif", "xfail", "unittest_skip", "unittest_expecting_failure"})
#: The OFF_MARKS a protected test already carried on 045978b, by node id. None did: every protected
#: file was collected with tools/protected_collect.py in a clean checkout of 045978b, and no item
#: carried one. So none is allowed.
ALLOWED_OFF_MARKS: Mapping[str, frozenset[str]] = {}

#: The collection plugin, its directory (put on PYTHONPATH) and its two environment variables.
PLUGIN = "protected_collect"
PLUGIN_DIR = Path(__file__).resolve().parent
COLLECT_FILES = "PROTECTED_COLLECT_FILES"
COLLECT_OUT = "PROTECTED_COLLECT_OUT"
COLLECT_TIMEOUT = 300

Reader = Callable[[str], bytes]
Definition = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
Function = ast.FunctionDef | ast.AsyncFunctionDef


def _split(node: str) -> tuple[str, list[str]]:
    path, *names = node.split("::")
    return path, [name.split("[", 1)[0] for name in names]


def _matches(name: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)


def is_test_file(path: str) -> bool:
    """Whether pytest collects *path* in the full run (its name matches ``python_files``)."""
    return _matches(PurePosixPath(path).name, TEST_FILES)


def _start(stmt: ast.stmt) -> int:
    """A statement's first line: its first decorator's, if it has one."""
    return min([stmt.lineno, *(decorator.lineno for decorator in getattr(stmt, "decorator_list", []))])


def _chain(tree: ast.Module, names: list[str]) -> list[Definition]:
    """The definitions *names* reaches, outermost first."""
    body: list[ast.stmt] = tree.body
    chain: list[Definition] = []
    for name in names:
        matches = [stmt for stmt in body if isinstance(stmt, Definition) and stmt.name == name]
        if not matches:
            raise LookupError(name)
        chain.append(matches[-1])  # a later definition replaces an earlier one, for Python and pytest alike
        body = matches[-1].body
    if not chain:
        raise LookupError("no test named")
    return chain


def node_source(text: str, names: list[str]) -> str:
    """The source of the function or class *names* reaches in *text*, decorators included."""
    found = _chain(ast.parse(text), names)[-1]
    return "\n".join(text.splitlines()[_start(found) - 1 : found.end_lineno or found.lineno])


def _callee(expr: ast.expr) -> str:
    """The name a decorator calls, or a base class names: ``fixture`` for ``@pytest.fixture`` and
    ``@fixture(scope="module")``, ``TestCase`` for ``unittest.TestCase``."""
    target = expr.func if isinstance(expr, ast.Call) else expr
    if isinstance(target, ast.Name):
        return target.id
    return target.attr if isinstance(target, ast.Attribute) else ""


def _is_fixture(stmt: ast.stmt) -> bool:
    """A function under a decorator that calls ``fixture``, or under any decorator called with ``autouse=``.

    By the decorator's callee, not its text: ``@pytest.mark.usefixtures(...)`` is a test's mark, not a
    fixture. An alias called without ``autouse=`` (``@ff`` after ``ff = pytest.fixture``) escapes this;
    the collection check catches what it hides.
    """
    return isinstance(stmt, Function) and any(
        _callee(decorator) == "fixture"
        or (isinstance(decorator, ast.Call) and any(keyword.arg == "autouse" for keyword in decorator.keywords))
        for decorator in stmt.decorator_list
    )


def _is_test(stmt: ast.stmt) -> bool:
    """A test function or method by pytest's name rule; a fixture named like one is not a test."""
    return isinstance(stmt, Function) and _matches(stmt.name, TEST_FUNCTIONS) and not _is_fixture(stmt)


def _mentions(stmt: ast.stmt, names: Iterable[str]) -> bool:
    """Whether *stmt*, anywhere inside it, holds one of *names* as an identifier or a string.

    Every identifier and string field counts: a name, an attribute, an import's name or alias, a
    keyword, a parameter, a ``global``, a nested definition's name, a string constant (``setattr(C,
    "name", ...)``, ``globals()["name"]``). A name computed at run time (``"test_" + rest``) escapes it.
    """
    wanted = set(names)
    for node in ast.walk(stmt):
        for _, value in ast.iter_fields(node):
            values = value if isinstance(value, list) else [value]
            if any(isinstance(item, str) and item in wanted for item in values):
                return True
    return False


def _span(stmt: ast.stmt) -> tuple[int, int]:
    return _start(stmt), stmt.end_lineno or stmt.lineno


def _context_spans(tree: ast.Module, lines: list[str], names: list[str], path: str) -> list[tuple[int, int]]:
    """The first and last line of each part of a per-test node's context (see the module doc), in order."""
    chain = _chain(tree, names)
    spans = [
        _span(stmt)
        for stmt in tree.body
        if stmt is not chain[0]
        and (
            _mentions(stmt, MODULE_SWITCHES | {definition.name for definition in chain})
            or (isinstance(stmt, Function) and (stmt.name in MODULE_HOOKS or _is_fixture(stmt)))
        )
    ]
    collected = is_test_file(path)  # in a file pytest does not collect, nothing is a test
    for owner, inner in zip(chain[:-1], chain[1:], strict=True):
        if not isinstance(owner, ast.ClassDef):
            continue
        first, last = _start(owner), max(owner.lineno, _start(owner.body[0]) - 1)
        while last > first and (not lines[last - 1].strip() or lines[last - 1].lstrip().startswith("#")):
            last -= 1  # blank lines and comments before the first statement are not the header
        spans.append((first, last))
        spans.extend(_span(stmt) for stmt in owner.body if stmt is not inner and not (collected and _is_test(stmt)))
    return spans


def context_source(text: str, names: list[str], path: str) -> str:
    """What in its own file decides, from outside a per-test node's own source, whether and how it runs."""
    lines = text.splitlines()
    spans = _context_spans(ast.parse(text), lines, names, path)
    return "\n\n".join("\n".join(lines[first - 1 : last]) for first, last in spans)


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


def context_digest(node: str, root: Path = ROOT, read: Reader | None = None) -> str:
    """The SHA-256 of a per-test node's context (:func:`context_source`)."""
    path, names = _split(node)
    if not names:
        raise ValueError(f"{node} is hashed whole; it has no separate context")
    text = (read or _working_tree(root))(path).decode("utf-8")
    return hashlib.sha256(context_source(text, names, path).encode("utf-8")).hexdigest()


def changed(expected: Mapping[str, str], root: Path = ROOT, *, context: bool = False) -> list[str]:
    """The nodes whose source (or, with *context*, context) no longer hashes as *expected*, in order."""
    hash_of = context_digest if context else digest
    different = []
    for node, sha in expected.items():
        try:
            same = hash_of(node, root) == sha
        except (OSError, LookupError, SyntaxError, UnicodeDecodeError, ValueError):
            same = False
        if not same:
            different.append(node)
    return different


def _last_of_each_name(body: list[ast.stmt]) -> list[Definition]:
    last = {stmt.name: stmt for stmt in body if isinstance(stmt, Definition)}
    return [stmt for stmt in body if isinstance(stmt, Definition) and last[stmt.name] is stmt]


def defined_tests(text: str) -> dict[tuple[str, int], str]:
    """The tests a file defines, as pytest and unittest find them: ``(name, first line)`` → ``[Class::]name``."""
    found: dict[tuple[str, int], str] = {}
    unittest_cases: set[str] = set()
    for stmt in _last_of_each_name(ast.parse(text).body):
        if _is_test(stmt):
            found[(stmt.name, _start(stmt))] = stmt.name
        elif isinstance(stmt, ast.ClassDef):
            bases = {_callee(base) for base in stmt.bases}
            case = any(name.endswith("TestCase") or name in unittest_cases for name in bases)
            if case:
                unittest_cases.add(stmt.name)
            elif not _matches(stmt.name, TEST_CLASSES):
                continue
            for method in _last_of_each_name(stmt.body):
                if not isinstance(method, Function) or _is_fixture(method):
                    continue
                if method.name.startswith("test") if case else _matches(method.name, TEST_FUNCTIONS):
                    found[(method.name, _start(method))] = f"{stmt.name}::{method.name}"
    return found


def collected(files: list[str], root: Path = ROOT) -> tuple[dict[str, Any] | None, str]:
    """Run pytest's collection of *files* as the full suite would, once; ``(result, output)``.

    The result is ``tools/protected_collect.py``'s JSON, or ``None`` when the run failed (then the
    output says why).
    """
    with tempfile.TemporaryDirectory() as scratch:
        out = Path(scratch) / "collected.json"
        # pyproject.toml chooses the settings, as for the suite (pytest-django exports the running
        # suite's choice); the run is not part of a coverage measurement.
        env = {
            name: value
            for name, value in os.environ.items()
            if name != "DJANGO_SETTINGS_MODULE" and not name.startswith("COV_CORE_")
        }
        env[COLLECT_FILES] = "\n".join(files)
        env[COLLECT_OUT] = str(out)
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(PLUGIN_DIR), env.get("PYTHONPATH")]))
        command = [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "-p", PLUGIN]
        try:
            run = subprocess.run(
                command, cwd=root, env=env, capture_output=True, text=True, timeout=COLLECT_TIMEOUT, check=False
            )
        except subprocess.TimeoutExpired as error:
            return None, f"collection did not finish in {COLLECT_TIMEOUT} s: {error}"
        output = f"{run.stdout}{run.stderr}"
        # 0: collected; 5: nothing collected (every protected item dropped), which the checks below report.
        if run.returncode not in (0, 5) or not out.exists():
            return None, f"collection failed (exit {run.returncode}):\n{output}"
        return json.loads(out.read_text(encoding="utf-8")), output


def _python_targets(nodes: Iterable[str]) -> list[tuple[str, str, list[str]]]:
    """``(node, path, names)`` for each node in *nodes* that lives in a file pytest collects."""
    targets = [(node, *_split(node)) for node in nodes]
    return [(node, path, names) for node, path, names in targets if is_test_file(path)]


def _protects(path: str, nodeid: str, whole: set[str], per_test: set[str]) -> bool:
    """Whether the item *nodeid* (in *path*) belongs to a protected node: its file is protected whole,
    or its id without the parameters (``path::name[case]`` → ``path::name``) is a per-test node."""
    return path in whole or nodeid.split("[", 1)[0] in per_test


def collection_problems(
    nodes: Iterable[str],
    root: Path = ROOT,
    allowed: Mapping[str, frozenset[str]] = ALLOWED_OFF_MARKS,
    pinned: Iterable[str] | None = None,
) -> list[str]:
    """Every way the protected Python tests in *nodes* would not run as written (see the module doc).

    *pinned*: the node ids that must still be collected (default: ``protected_collected.json``'s); only
    those that belong to a protected node among *nodes* count.
    """
    targets = _python_targets(nodes)
    files = sorted({path for _, path, _ in targets})
    if not files:
        return []
    result, output = collected(files, root)
    if result is None:
        return [output]
    return _problems(result, targets, root, allowed, load_collected() if pinned is None else pinned)


def collected_ids(nodes: Iterable[str], root: Path = ROOT) -> tuple[list[str], list[str]]:
    """The node ids collected from the protected Python tests in *nodes*, in collection order, and the
    problems the same collection shows (pinning nothing): how ``protected_collected.json`` is written."""
    targets = _python_targets(nodes)
    files = sorted({path for _, path, _ in targets})
    if not files:
        return [], []
    result, output = collected(files, root)
    if result is None:
        return [], [output]
    whole = {path for _, path, names in targets if not names}
    per_test = {node for node, _, names in targets if names}
    ids = [item["nodeid"] for item in result["items"] if _protects(item["path"], item["nodeid"], whole, per_test)]
    return ids, _problems(result, targets, root, ALLOWED_OFF_MARKS, ())


def _problems(
    result: dict[str, Any],
    targets: list[tuple[str, str, list[str]]],
    root: Path,
    allowed: Mapping[str, frozenset[str]],
    pinned: Iterable[str],
) -> list[str]:
    """The collection problems of one collection *result* of *targets*' files, each reported once."""
    files = sorted({path for _, path, _ in targets})
    items: list[dict[str, Any]] = result["items"]
    deselected = set(result["deselected"])
    whole = {path for _, path, names in targets if not names}
    per_test = {node for node, _, names in targets if names}
    problems: list[str] = []

    def report(problem: str) -> None:
        if problem not in problems:
            problems.append(problem)

    def missing(node: str) -> str:
        return f"{node}: not collected" + (" (deselected)" if node in deselected else "")

    trees: dict[str, str] = {}
    for path in files:
        try:
            trees[path] = (root / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            report(f"{path}: missing")

    for node, path, names in targets:
        if path not in trees:
            continue
        if not names:
            ran = {tuple(item["definition"]) for item in items if item["path"] == path}
            for (name, line), qualname in defined_tests(trees[path]).items():
                if (path, name, line) not in ran:
                    report(missing(f"{path}::{qualname}"))
            continue
        matches = [item for item in items if item["nodeid"] == node]
        if len(matches) != 1:
            report(f"{node}: collected {len(matches)} times" if matches else missing(node))
            continue
        try:
            tree = ast.parse(trees[path])
            line = _start(_chain(tree, names)[-1])
            spans = _context_spans(tree, trees[path].splitlines(), names, path)
        except (LookupError, SyntaxError):
            report(f"{node}: its def is gone")
            continue
        filename, name, first = matches[0]["code"]
        if (filename, name, first) != (path, names[-1], line):
            report(f"{node}: runs {name} ({filename}, line {first}), not its def (line {line})")
        # A fixture its own module or class registers must be one the context hashes: not one under an
        # alias of pytest.fixture, nor one imported from another file.
        for fixture in matches[0]["fixtures"]:
            filename, _, first = fixture["code"]
            if filename != path or not any(start <= first <= end for start, end in spans):
                report(
                    f"{node}: uses fixture {fixture['name']} ({filename}, line {first}), "
                    "which its hashed context does not cover"
                )

    # One surviving case satisfies the check above, so a deselected protected item (``-k``,
    # ``--deselect``, a hook that reports it) is a problem by its own id, and so is an id pinned from the
    # baseline that is not collected now (a case removed by a hook that does not report it, or renamed).
    ids = {item["nodeid"] for item in items}
    for nodeid in [*result["deselected"], *pinned]:
        if _protects(nodeid.split("::", 1)[0], nodeid, whole, per_test) and nodeid not in ids:
            report(missing(nodeid))

    for item in items:
        if not _protects(item["path"], item["nodeid"], whole, per_test):
            continue
        off = set(item["markers"]) & OFF_MARKS - allowed.get(item["nodeid"], frozenset())
        if off:
            report(f"{item['nodeid']}: marked {', '.join(sorted(off))}")
        if item["path"] in whole:
            filename, name, first = item["code"]
            own = filename == item["path"] or item["wrapper_from_library"]
            if not own or tuple(item["definition"][:2]) != (item["path"], item["name"]):
                report(
                    f"{item['nodeid']}: runs {name} ({filename}, line {first}), not a test defined in {item['path']}"
                )
    return problems


def load(fixture: Path = FIXTURE) -> dict[str, str]:
    return dict(json.loads(fixture.read_text(encoding="utf-8"))["nodes"])


def load_collected(fixture: Path = COLLECTED) -> list[str]:
    """The node ids pinned in ``protected_collected.json``."""
    return list(json.loads(fixture.read_text(encoding="utf-8"))["nodes"])


def _checkout_of(root: Path, ref: str) -> str | None:
    """*ref*'s full SHA when *root* is a clean checkout of it (its HEAD, nothing changed or untracked)."""

    def git(*args: str) -> str | None:
        run = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
        return run.stdout.strip() if run.returncode == 0 else None

    head, wanted = git("rev-parse", "HEAD"), git("rev-parse", "--verify", f"{ref}^{{commit}}")
    clean = git("status", "--porcelain") == ""
    return head if head is not None and head == wanted and clean else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Guard the tests that enforce the invariants (spec D11).")
    parser.add_argument("nodes", nargs="*", help="node ids (default: the fixture's)")
    parser.add_argument("--root", type=Path, default=ROOT, help="the tree to read (default: this repository)")
    parser.add_argument("--fixture", type=Path, help="default: protected_tests.json, or with --context its context")
    parser.add_argument("--ref", help="read the sources from this commit instead of the working tree")
    parser.add_argument("--check", action="store_true", help="compare with the fixture; exit 1 on any change")
    parser.add_argument("--json", action="store_true", help='print {"node": "sha256", ...}')
    parser.add_argument("--context", action="store_true", help="hash each per-test node's context, not its source")
    parser.add_argument("--collect", action="store_true", help="run the collection check; exit 1 on any problem")
    parser.add_argument(
        "--collected",
        action="store_true",
        help="print the ids collected from the protected Python tests as protected_collected.json "
        "(with --ref: --root must be a clean checkout of it)",
    )
    args = parser.parse_args(argv)
    fixture = args.fixture or (CONTEXT if args.context else FIXTURE)

    if args.collected:
        if not args.ref:
            parser.error("--collected needs --ref, the commit --root is a clean checkout of")
        sha = _checkout_of(args.root, args.ref)
        if sha is None:
            print(f"{args.root} is not a clean checkout of {args.ref}", file=sys.stderr)
            return 1
        ids, problems = collected_ids(args.nodes or load(fixture), args.root)
        for problem in problems:
            print(problem, file=sys.stderr)
        if problems or not ids:
            print(
                f"protected tests on {args.ref}: {len(problems)} collection problems, {len(ids)} ids", file=sys.stderr
            )
            return 1
        print(json.dumps({"about": COLLECTED_ABOUT, "ref": sha, "nodes": ids}, indent=2))
        return 0

    if args.collect:
        problems = collection_problems(args.nodes or load(fixture), args.root)
        for problem in problems:
            print(problem)
        print("protected tests: " + (f"{len(problems)} collection problems" if problems else "collected as written"))
        return 1 if problems else 0

    if args.check:
        different = changed(load(fixture), args.root, context=args.context)
        for node in different:
            print(f"changed: {node}")
        what = "protected tests' context" if args.context else "protected tests"
        print(f"{what}: " + (f"{len(different)} changed" if different else "unchanged"))
        return 1 if different else 0

    if args.nodes:
        nodes = args.nodes
    elif args.context:  # the context covers the per-test nodes of the own-source fixture
        nodes = [node for node in load(args.fixture or FIXTURE) if "::" in node]
    else:
        nodes = list(load(fixture))
    read = _commit(args.ref, args.root) if args.ref else _working_tree(args.root)
    hash_of = context_digest if args.context else digest
    hashes = {node: hash_of(node, args.root, read) for node in nodes}
    if args.json:
        print(json.dumps(hashes, indent=2))
    else:
        for node, sha in hashes.items():
            print(f"{sha}  {node}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
