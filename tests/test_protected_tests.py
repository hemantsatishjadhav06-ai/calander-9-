"""The protected-test guard (spec D11; docs/specs/phase-3.md, T1 and gate item 10).

The tests that enforce ``CLAUDE.md``'s invariants are never edited in Phase 3. Their sources were
hashed once, from ``045978b``, into ``tests/fixtures/protected_tests.json`` by
``tools/protected_tests.py``; this module recomputes every hash from the working tree. It reads no
git history, so it runs in CI's shallow checkout. A failure here means the change is wrong, not the
fixture: the fixture is never regenerated in Phase 3.

The guard is per test where D11 protects tests inside a file that also holds ordinary ones
(``test_setup.py``): an edit beside a protected test passes, an edit to it fails. Files D11 protects
whole (the golden browser specs, the accessibility sweep, the provider-readiness and Telegram privacy
tests, the gate and publisher tests) are hashed whole.

A protected test can also be turned off without one character of its own source changing: a module
``pytestmark`` or ``pytest_plugins``, a module fixture that overrides one it requests, a mark or an
autouse fixture on its class, a later rebinding, ``del`` or ``setattr`` of its name, a ``conftest.py``
or an ``addopts`` that ignores, deselects, removes or marks it, or one parametrized case of it, at
collection. Two more checks close those. The context hashes
(``tests/fixtures/protected_context.json``, also written from ``045978b``) cover, for each per-test
node, the module's statements that touch ``pytestmark`` or ``pytest_plugins`` or name the node or a
class around it, its fixtures and xunit setup, and, for a node in a class, the class's header and every
statement of its body that is not a test (in a file pytest does not collect, such as ``live_verify``'s
``Command``, nothing is: every statement but the node's own def). The collection check runs pytest's own
collection of the protected files once, as the full suite would (``pyproject.toml``, every
``conftest.py``), and fails when a protected test is not collected, is marked skip, skipif or xfail,
would run anything but the def its hash covers, or uses a fixture of its own module or class that the
context does not hash (under an alias of ``pytest.fixture``, or imported). One parametrized case counts
as much as a whole test: a deselected protected item (``-k``, ``--deselect``, a hook that reports it
through ``pytest_deselected``) fails by its own node id, and every node id collected from the protected
tests on ``045978b`` (``tests/fixtures/protected_collected.json``, written once from a clean checkout of
it) must still be collected, so a case a hook removes without reporting it, renames or drops fails; ids
added beside them pass.

Outside the guard: a skip at run time from code outside the protected files, such as a
``conftest.py`` hook (``pytest_runtest_setup``) or fixture, or the code of a plugin or helper module a
protected file loads (the line that loads it is context); a protected name built at run time from
parts (``globals()["test_" + rest]``); and the value a parametrized case takes from code outside its
file (its id is pinned, the value behind it is not). Collection does not see a run-time skip; the full
run reports it as skipped.
"""

import hashlib
import json
import time
import tomllib
from pathlib import Path

import pytest

from tools import protected_tests

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "protected_tests.json"
CONTEXT = ROOT / "tests" / "fixtures" / "protected_context.json"
COLLECTED = ROOT / "tests" / "fixtures" / "protected_collected.json"

GOLDEN = "tests/e2e/golden/"
SETUP = "apps/studio/tests/test_setup.py"
LIVE_VERIFY = "apps/common/management/commands/live_verify.py"
#: D11's list, as node ids: every one must stay in the fixture.
REQUIRED = (
    # The golden browser paths (01–12, 05-06, 11-inputs).
    *(
        GOLDEN + name
        for name in (
            "01-sign-in.spec.ts",
            "02-onboarding.spec.ts",
            "03-ask-the-team.spec.ts",
            "04-compose.spec.ts",
            "05-approve-and-schedule.spec.ts",
            "05-06-role-variants.spec.ts",
            "06-request-changes.spec.ts",
            "07-calendar-drag.spec.ts",
            "08-client-portal.spec.ts",
            "09-inbox.spec.ts",
            "10-brand-and-timezone.spec.ts",
            "11-isolation.spec.ts",
            "11-isolation-inputs.spec.ts",
            "12-two-factor.spec.ts",
        )
    ),
    # Dialogs labelled and trapped, words never in the icon greys, every control named.
    "apps/common/tests/test_a11y_sweep.py",
    # Invariant 9: readiness copy names no setting, worker or provider; Set up's names are owners' only.
    f"{SETUP}::test_readiness_speaks_plainly_and_points_at_set_up",
    f"{SETUP}::TestSetupPage::test_owners_see_the_exact_names_and_others_are_told_to_ask",
    "apps/studio/tests/test_chat_provider_readiness.py",
    # Invariant 4: private Telegram stays private.
    f"{SETUP}::TestToday::test_private_telegram_jobs_stay_out_of_the_card",
    "apps/telegram/tests/test_web_privacy.py",
    # Invariant 1: the gate and the publisher's re-check.
    "apps/approvals/test_gate.py",
    "apps/publisher/tests.py",
    "apps/publisher/test_claim_and_success.py",
    "apps/publisher/test_connection_budget.py",
    "apps/publisher/test_delivery_controls.py",
    "apps/publisher/test_failure_notification.py",
    "apps/publisher/test_first_comment.py",
    "apps/publisher/test_linkedin_publishing.py",
    "apps/publisher/test_media_handling.py",
    "apps/publisher/test_neopolis_launch_recovery.py",
    "apps/publisher/test_publish_confirmation.py",
    "apps/publisher/test_round5_integrity.py",
    "apps/publisher/test_token_expired_flags_account.py",
    # Invariant 2: live_verify's isolation check (``isolation.workspace``) and the run that holds it.
    f"{LIVE_VERIFY}::Command::check_isolation_and_approval",
    f"{LIVE_VERIFY}::Command::_workflow_fixture",
)

MODULE = """import pytest


def helper():
    return 1


@pytest.mark.django_db
def test_protected():
    assert helper() == 1


def test_neighbour():
    assert True


class TestGroup:
    def test_method(self):
        assert "word" == "word"

    def test_other(self):
        assert 2 == 2
"""


def _tree(tmp_path, module=MODULE, spec="test('x', () => {});\n"):
    (tmp_path / "pkg").mkdir(exist_ok=True)
    (tmp_path / "pkg" / "test_mod.py").write_text(module, encoding="utf-8")
    (tmp_path / "golden.spec.ts").write_text(spec, encoding="utf-8")
    return tmp_path


NODES = (
    "pkg/test_mod.py::test_protected",
    "pkg/test_mod.py::TestGroup::test_method",
    "golden.spec.ts",
)


def _expected(root):
    return {node: protected_tests.digest(node, root) for node in NODES}


# ─────────────────────────────── The real fixture ───────────────────────────────


def test_no_protected_test_changed_since_045978b():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fixture["ref"].startswith("045978b")
    changed = protected_tests.changed(fixture["nodes"], ROOT)
    assert not changed, (
        "These protected invariant tests differ from their source on 045978b (spec D11). "
        "Change the implementation, not the test: " + ", ".join(changed)
    )


def test_no_protected_tests_context_changed_since_045978b():
    fixture = json.loads(CONTEXT.read_text(encoding="utf-8"))
    assert fixture["ref"] == json.loads(FIXTURE.read_text(encoding="utf-8"))["ref"]
    assert list(fixture["nodes"]) == [node for node in protected_tests.load(FIXTURE) if "::" in node]
    # A class node's context holds at least its class's header, wherever the class lives (live_verify's
    # Command too, in a file pytest does not collect); the SHA-256 of nothing would mean it holds none.
    nothing = hashlib.sha256(b"").hexdigest()
    assert [node for node, sha in fixture["nodes"].items() if node.count("::") > 1 and sha == nothing] == []
    changed = protected_tests.changed(fixture["nodes"], ROOT, context=True)
    assert not changed, (
        "What decides whether these protected tests run (their module's pytestmark or autouse setup, their "
        "class's marks, fixtures, setup or attributes) differs from 045978b (spec D11): " + ", ".join(changed)
    )


def test_the_collected_ids_were_pinned_from_045978b_for_every_protected_python_test():
    fixture = json.loads(COLLECTED.read_text(encoding="utf-8"))
    assert fixture["ref"] == json.loads(FIXTURE.read_text(encoding="utf-8"))["ref"]
    pinned = fixture["nodes"]
    assert len(pinned) == len(set(pinned))
    python = [node for node in protected_tests.load(FIXTURE) if protected_tests.is_test_file(node.split("::")[0])]
    whole = {node for node in python if "::" not in node}
    per_test = {node for node in python if "::" in node}
    stray = [node for node in pinned if node.split("::")[0] not in whole and node.split("[")[0] not in per_test]
    assert stray == [], "every pinned id is an item of a protected Python test, not a neighbour"
    assert whole <= {node.split("::")[0] for node in pinned}, "every whole-file entry's items are pinned"
    assert per_test <= {node.split("[")[0] for node in pinned}, "every per-test node is pinned"


def test_every_protected_test_is_collected_unmarked_and_runs_its_own_def():
    began = time.monotonic()
    problems = protected_tests.collection_problems(
        protected_tests.load(FIXTURE), ROOT, pinned=protected_tests.load_collected(COLLECTED)
    )
    assert not problems, "Protected invariant tests would not run as written (spec D11):\n" + "\n".join(problems)
    assert time.monotonic() - began < 60


def test_the_guard_collects_with_the_suites_settings():
    options = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["pytest"]["ini_options"]
    assert tuple(options["python_files"]) == protected_tests.TEST_FILES
    assert tuple(options["python_classes"]) == protected_tests.TEST_CLASSES
    assert tuple(options["python_functions"]) == protected_tests.TEST_FUNCTIONS
    names = ("python_files", "python_classes", "python_functions")
    scratch = "[pytest]\n" + "".join(f"{key} = {' '.join(options[key])}\n" for key in names)
    assert scratch == INI
    assert protected_tests.ALLOWED_OFF_MARKS == {}, "045978b's protected tests carried no skip, skipif or xfail"


def test_the_fixture_holds_every_test_d11_protects():
    nodes = set(json.loads(FIXTURE.read_text(encoding="utf-8"))["nodes"])
    missing = [node for node in REQUIRED if node not in nodes]
    assert not missing, f"protected tests missing from the fixture: {missing}"


# ─────────────────────────────── The guard on fixture files ───────────────────────────────


def test_a_one_character_change_to_a_protected_test_fails(tmp_path):
    root = _tree(tmp_path)
    expected = _expected(root)
    _tree(root, MODULE.replace("assert helper() == 1", "assert helper() == 2"))
    assert protected_tests.changed(expected, root) == ["pkg/test_mod.py::test_protected"]


def test_a_one_character_change_to_a_protected_method_fails(tmp_path):
    root = _tree(tmp_path)
    expected = _expected(root)
    _tree(root, MODULE.replace('"word" == "word"', '"word" == "Word"'))
    assert protected_tests.changed(expected, root) == ["pkg/test_mod.py::TestGroup::test_method"]


def test_a_change_to_a_neighbouring_function_passes(tmp_path):
    root = _tree(tmp_path)
    expected = _expected(root)
    moved = MODULE.replace("def test_neighbour():\n    assert True", "def test_neighbour():\n    assert 1 + 1 == 2")
    moved = moved.replace("assert 2 == 2", "assert 3 == 3")
    moved = moved.replace("import pytest\n", "import pytest\n\nEXTRA = 'lines above shift every test down'\n")
    _tree(root, moved)
    assert protected_tests.changed(expected, root) == []


def test_a_decorator_belongs_to_its_test(tmp_path):
    root = _tree(tmp_path)
    expected = _expected(root)
    _tree(root, MODULE.replace("@pytest.mark.django_db\n", "@pytest.mark.skip\n@pytest.mark.django_db\n"))
    assert protected_tests.changed(expected, root) == ["pkg/test_mod.py::test_protected"]


def test_a_whole_file_entry_changes_with_any_character(tmp_path):
    root = _tree(tmp_path)
    expected = _expected(root)
    _tree(root, spec="test('x', () => {}); \n")
    assert protected_tests.changed(expected, root) == ["golden.spec.ts"]


def test_a_removed_test_or_file_counts_as_changed(tmp_path):
    root = _tree(tmp_path)
    expected = _expected(root)
    _tree(root, MODULE.replace("def test_protected():", "def test_renamed():"))
    (root / "golden.spec.ts").unlink()
    assert protected_tests.changed(expected, root) == ["pkg/test_mod.py::test_protected", "golden.spec.ts"]


def test_the_command_line_check_names_the_changed_test(tmp_path, capsys):
    root = _tree(tmp_path)
    fixture = tmp_path / "protected.json"
    fixture.write_text(json.dumps({"ref": "test", "nodes": _expected(root)}), encoding="utf-8")
    assert protected_tests.main(["--check", "--root", str(root), "--fixture", str(fixture)]) == 0

    _tree(root, MODULE.replace("assert helper() == 1", "assert helper() == 2"))
    assert protected_tests.main(["--check", "--root", str(root), "--fixture", str(fixture)]) == 1
    assert "pkg/test_mod.py::test_protected" in capsys.readouterr().out


# ─────────────────────── Turning a protected test off without editing it ───────────────────────
#
# Each case leaves every own-source hash unchanged; the context hashes (the module's pytestmark,
# pytest_plugins, fixtures, xunit setup and statements naming the test, and the enclosing class's
# decorators, fixtures, setup and attributes) and the collection check (pytest's own collection, run
# as the suite runs it) must catch it.

GUARDED = """import pytest


def helper():
    return 1


@pytest.mark.django_db
def test_protected():
    assert helper() == 1


def test_neighbour():
    assert True


class TestGroup:
    word = "word"

    def setup_method(self):
        self.count = 2

    def test_method(self):
        assert self.word == "word"

    def test_other(self):
        assert self.count == 2
"""

WHOLE = """import unittest


class EngineTest(unittest.TestCase):
    def test_engine(self):
        self.assertEqual(1, 1)


def test_plain():
    assert True
"""

#: The suite's collection settings (pyproject.toml), for a scratch tree.
INI = "[pytest]\npython_files = tests.py test_*.py\npython_classes = Test*\npython_functions = test_*\n"

PROTECTED = "pkg/test_mod.py::test_protected"
METHOD = "pkg/test_mod.py::TestGroup::test_method"
WHOLE_FILE = "pkg/tests.py"
WHOLE_TESTS = (f"{WHOLE_FILE}::EngineTest::test_engine", f"{WHOLE_FILE}::test_plain")


def _suite(root, module=GUARDED, files=None):
    """A scratch suite: a module holding two protected tests and their neighbours, and a protected file."""
    (root / "pytest.ini").write_text(INI, encoding="utf-8")
    (root / "pkg").mkdir(exist_ok=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "test_mod.py").write_text(module, encoding="utf-8")
    (root / "pkg" / "tests.py").write_text(WHOLE, encoding="utf-8")
    for name, text in (files or {}).items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    return root


def _baseline(root):
    hashes = {node: protected_tests.digest(node, root) for node in (PROTECTED, METHOD, WHOLE_FILE)}
    context = {node: protected_tests.context_digest(node, root) for node in (PROTECTED, METHOD)}
    return hashes, context


def _caught(root, baseline, pinned=None):
    """(context hashes that changed, collection problems), once the own-source hashes say nothing.

    *pinned*: the node ids that must still be collected (default: the real fixture's, none of which is
    in a scratch suite).
    """
    hashes, context = baseline
    assert protected_tests.changed(hashes, root) == [], "the case must leave every own-source hash alone"
    problems = protected_tests.collection_problems(list(hashes), root, pinned=pinned)
    return protected_tests.changed(context, root, context=True), problems


def test_an_untouched_suite_and_edits_beside_the_protected_tests_pass(tmp_path):
    root = _suite(tmp_path)
    baseline = _baseline(root)
    assert _caught(root, baseline) == ([], [])

    beside = GUARDED.replace("def test_neighbour():\n    assert True", "def test_neighbour():\n    assert 2 == 2")
    beside = beside.replace("assert self.count == 2", "assert self.count >= 2")
    beside = beside.replace(
        "    def test_other", "    def test_added(self):\n        assert True\n\n    def test_other"
    )
    beside += "\n\ndef test_new():\n    assert helper() == 1\n"
    _suite(root, beside)
    assert _caught(root, baseline) == ([], [])


@pytest.mark.parametrize(
    "addition",
    [
        'pytestmark = pytest.mark.skip(reason="off")\n',
        'pytestmark = [pytest.mark.xfail(reason="off")]\n',
    ],
)
def test_a_module_pytestmark_is_caught(tmp_path, addition):
    root = _suite(tmp_path)
    baseline = _baseline(root)
    _suite(root, GUARDED.replace("import pytest\n", f"import pytest\n\n{addition}"))
    context, problems = _caught(root, baseline)
    assert context == [PROTECTED, METHOD]
    mark = "skip" if "skip" in addition else "xfail"
    assert problems == [f"{PROTECTED}: marked {mark}", f"{METHOD}: marked {mark}"]


def test_a_module_level_autouse_fixture_is_caught(tmp_path):
    root = _suite(tmp_path)
    baseline = _baseline(root)
    off = '@pytest.fixture(autouse=True)\ndef _off():\n    pytest.skip("off")\n\n\n'
    _suite(root, GUARDED.replace("def helper():", off + "def helper():"))
    context, _problems = _caught(root, baseline)
    assert context == [PROTECTED, METHOD]


def test_a_skip_on_the_enclosing_class_is_caught(tmp_path):
    root = _suite(tmp_path)
    baseline = _baseline(root)
    _suite(root, GUARDED.replace("class TestGroup:", '@pytest.mark.skip(reason="off")\nclass TestGroup:'))
    context, problems = _caught(root, baseline)
    assert context == [METHOD]
    assert problems == [f"{METHOD}: marked skip"]


@pytest.mark.parametrize(
    "rebinding, node",
    [
        ("test_protected = lambda: None\n", PROTECTED),
        ("def _noop():\n    pass\n\n\ntest_protected = _noop\n", PROTECTED),
        ("TestGroup.test_method = lambda self: None\n", METHOD),
    ],
)
def test_a_later_rebinding_of_the_name_is_caught(tmp_path, rebinding, node):
    root = _suite(tmp_path)
    baseline = _baseline(root)
    _suite(root, GUARDED + "\n\n" + rebinding)
    _context, problems = _caught(root, baseline)
    assert len(problems) == 1 and problems[0].startswith(f"{node}: runs "), problems


@pytest.mark.parametrize(
    "deletion, node",
    [("del test_protected\n", PROTECTED), ("del TestGroup.test_method\n", METHOD)],
)
def test_a_later_del_of_the_name_is_caught(tmp_path, deletion, node):
    root = _suite(tmp_path)
    baseline = _baseline(root)
    _suite(root, GUARDED + "\n\n" + deletion)
    _context, problems = _caught(root, baseline)
    assert problems == [f"{node}: not collected"]


DESELECT = """def pytest_collection_modifyitems(config, items):
    dropped = [item for item in items if item.name == "test_protected"]
    config.hook.pytest_deselected(items=dropped)
    items[:] = [item for item in items if item not in dropped]
"""

SKIP_ALL = """import pytest


def pytest_collection_modifyitems(items):
    for item in items:
        item.add_marker(pytest.mark.skip(reason="off"))
"""


@pytest.mark.parametrize(
    "files, expected",
    [
        ({"pkg/conftest.py": 'collect_ignore = ["tests.py"]\n'}, [f"{node}: not collected" for node in WHOLE_TESTS]),
        ({"conftest.py": 'collect_ignore = ["pkg/tests.py"]\n'}, [f"{node}: not collected" for node in WHOLE_TESTS]),
        ({"conftest.py": 'collect_ignore_glob = ["pkg/*"]\n'}, None),
        # A conftest anywhere in the tree takes part in every run's collection.
        ({"elsewhere/conftest.py": DESELECT}, [f"{PROTECTED}: not collected (deselected)"]),
        ({"elsewhere/conftest.py": SKIP_ALL}, None),
    ],
)
def test_a_conftest_that_drops_or_skips_protected_tests_is_caught(tmp_path, files, expected):
    root = _suite(tmp_path)
    baseline = _baseline(root)
    _suite(root, files=files)
    _context, problems = _caught(root, baseline)
    if expected is not None:
        assert problems == expected
    else:
        assert {PROTECTED, METHOD, *WHOLE_TESTS} <= {problem.split(": ", 1)[0] for problem in problems}, problems


@pytest.mark.parametrize(
    "old, new",
    [
        (
            '    word = "word"\n',
            '    word = "word"\n\n    @pytest.fixture(autouse=True)\n    def _off(self):\n        pytest.skip("off")\n',
        ),
        ("self.count = 2", 'pytest.skip("off")'),
        ('word = "word"', 'word = "Word"'),
        ('    word = "word"\n', '    word = "word"\n    __test__ = False\n'),
        ("class TestGroup:", "class TestGroup(Skipping):"),
    ],
)
def test_an_edit_to_the_class_around_a_protected_method_is_caught(tmp_path, old, new):
    module = GUARDED.replace("class TestGroup:", "class Skipping:\n    pass\n\n\nclass TestGroup:")
    root = _suite(tmp_path, module)
    baseline = _baseline(root)
    _suite(root, module.replace(old, new, 1))
    context, _problems = _caught(root, baseline)
    assert context == [METHOD]


# A module's own fixture overrides a conftest fixture of the same name, so a fixture added beside the
# protected tests can skip one that requests it, autouse or not.

REQUESTING = GUARDED.replace("def test_protected():", "def test_protected(world):")
WORLD = "import pytest\n\n\n@pytest.fixture\ndef world():\n    return 1\n"
OFF_WORLD = 'import pytest\n\n\n@pytest.fixture\ndef world():\n    pytest.skip("off")\n'


@pytest.mark.parametrize(
    "fixture",
    [
        '@pytest.fixture\ndef world():\n    pytest.skip("off")\n',
        '@pytest.fixture()\ndef world():\n    pytest.skip("off")\n',
        '@pytest.fixture(name="world")\ndef _anything():\n    pytest.skip("off")\n',
        'from pytest import fixture\n\n\n@fixture\ndef world():\n    pytest.skip("off")\n',
    ],
    ids=["bare", "called", "renamed", "imported-decorator"],
)
def test_a_module_fixture_that_overrides_a_requested_one_is_caught(tmp_path, fixture):
    root = _suite(tmp_path, REQUESTING, files={"pkg/conftest.py": WORLD})
    baseline = _baseline(root)
    _suite(root, REQUESTING.replace("def helper():", f"{fixture}\n\ndef helper():"))
    context, problems = _caught(root, baseline)
    assert context == [PROTECTED, METHOD]
    assert problems == []


ALIAS = "ff = pytest.fixture\n\n\ndef helper():"
AUTOUSE_ALIAS = "auto = pytest.fixture(autouse=True)\n\n\ndef helper():"
ALIASED_OVERRIDE = '@ff\ndef world():\n    pytest.skip("off")\n\n\ndef helper():'
ASSIGNED_HOOK = 'def _off(function):\n    pytest.skip("off")\n\n\nsetup_function = _off\n\n\ndef helper():'
#: The autouse fixture pytest writes for a module's setup_function (named after the module's import name).
XUNIT = "_xunit_setup_function_fixture_pkg.test_mod"


def _named_like_a_test(decorator):
    """An edit that adds, above TestGroup's setup_method, a fixture named like a test that skips."""
    return (
        "    def setup_method",
        f'    {decorator}\n    def test_zz(self):\n        pytest.skip("off")\n\n    def setup_method',
    )


def test_an_autouse_fixture_named_like_a_test_under_an_alias_is_context(tmp_path):
    """The review's case: ``@ff(autouse=True)`` is a fixture by its ``autouse=``, whatever ``ff`` names."""
    root = _suite(tmp_path)
    baseline = _baseline(root)
    old, new = _named_like_a_test("@ff(autouse=True)")
    _suite(root, GUARDED.replace("def helper():", ALIAS, 1).replace(old, new, 1))
    assert _caught(root, baseline) == ([METHOD], [])


@pytest.mark.parametrize(
    "edits, files, expected",
    [
        # Under an alias that already says autouse=True, the context takes the fixture for a test.
        ([("def helper():", AUTOUSE_ALIAS), _named_like_a_test("@auto")], {}, [(METHOD, "test_zz")]),
        # An alias at module level, overriding the conftest fixture the protected test requests.
        ([("def helper():", ALIAS), ("def helper():", ALIASED_OVERRIDE)], {}, [(PROTECTED, "world")]),
        # A fixture imported from another file is the module's own fixture too.
        (
            [("def helper():", "from pkg.helpers import world  # noqa: F401\n\n\ndef helper():")],
            {"pkg/helpers.py": OFF_WORLD},
            [(PROTECTED, "world")],
        ),
        # An xunit hook bound by assignment: pytest's wrapper, autouse in the whole module, runs a
        # function the context leaves out.
        ([("def helper():", ASSIGNED_HOOK)], {}, [(PROTECTED, XUNIT), (METHOD, XUNIT)]),
    ],
    ids=["aliased-autouse-in-class", "aliased-module-override", "imported-module-override", "assigned-xunit-hook"],
)
def test_a_fixture_the_context_cannot_see_is_caught_by_the_collection(tmp_path, edits, files, expected):
    root = _suite(tmp_path, REQUESTING, files={"pkg/conftest.py": WORLD})
    baseline = _baseline(root)
    module = REQUESTING
    for old, new in edits:
        module = module.replace(old, new, 1)
    _suite(root, module, files=files)
    _context, problems = _caught(root, baseline)
    assert [problem.split(" (", 1)[0] for problem in problems] == [
        f"{node}: uses fixture {name}" for node, name in expected
    ], problems
    assert all(problem.endswith(", which its hashed context does not cover") for problem in problems)


def test_a_neighbour_marked_usefixtures_is_a_test_not_context(tmp_path):
    module = GUARDED.replace("    def test_other", '    @pytest.mark.usefixtures("tmp_path")\n    def test_other')
    root = _suite(tmp_path, module)
    baseline = _baseline(root)
    _suite(root, module.replace("assert self.count == 2", "assert self.count >= 2"))
    assert _caught(root, baseline) == ([], [])


DESELECT_PLAIN = DESELECT.replace('"test_protected"', '"test_plain"')


def test_a_whole_file_test_marked_usefixtures_must_be_collected(tmp_path):
    whole = "import pytest\n" + WHOLE.replace("def test_plain", '@pytest.mark.usefixtures("tmp_path")\ndef test_plain')
    root = _suite(tmp_path, files={WHOLE_FILE: whole})
    assert ("test_plain", whole.splitlines().index('@pytest.mark.usefixtures("tmp_path")') + 1) in (
        protected_tests.defined_tests(whole)
    )
    baseline = _baseline(root)
    _suite(root, files={WHOLE_FILE: whole, "elsewhere/conftest.py": DESELECT_PLAIN})
    _context, problems = _caught(root, baseline)
    assert problems == [f"{WHOLE_FILE}::test_plain: not collected (deselected)"]


# ─────────────────── One case of a parametrized protected test ───────────────────
#
# One surviving case satisfies the check that every test a whole-file entry defines was collected. So a
# deselected protected item is a problem by its own node id, and every node id the protected tests had
# when the baseline was pinned (for the real tree, 045978b's: tests/fixtures/protected_collected.json)
# must still be collected: a case removed by a hook that never reports it, or renamed, fails; a case
# added passes the collection (in a whole-file entry, the file's hash catches the edit).

PARAMETRIZED = (
    "import pytest\n"
    + WHOLE
    + '\n\n@pytest.mark.parametrize("case", ["kept", "gone"])\ndef test_cases(case):\n    assert case\n'
)
CASES = (f"{WHOLE_FILE}::test_cases[kept]", f"{WHOLE_FILE}::test_cases[gone]")

DESELECT_CASE = """def pytest_collection_modifyitems(config, items):
    dropped = [item for item in items if item.name == "test_cases[gone]"]
    config.hook.pytest_deselected(items=dropped)
    items[:] = [item for item in items if item not in dropped]
"""

REMOVE_CASE = """def pytest_collection_modifyitems(items):
    items[:] = [item for item in items if item.name != "test_cases[gone]"]
"""

RENAME_CASES = """def pytest_make_parametrize_id(config, val, argname):
    return f"{val}-renamed" if argname == "case" else None
"""


def _pinned(root):
    """The node ids the scratch suite's protected tests have now, as ``--collected`` pins them."""
    pinned, problems = protected_tests.collected_ids([PROTECTED, METHOD, WHOLE_FILE], root)
    assert problems == [] and set(CASES) <= set(pinned), (pinned, problems)
    return pinned


@pytest.mark.parametrize(
    "files, expected",
    [
        ({"elsewhere/conftest.py": DESELECT_CASE}, [f"{CASES[1]}: not collected (deselected)"]),
        ({"elsewhere/conftest.py": REMOVE_CASE}, [f"{CASES[1]}: not collected"]),
        ({"pytest.ini": INI + 'addopts = -k "not gone"\n'}, [f"{CASES[1]}: not collected (deselected)"]),
        ({"conftest.py": RENAME_CASES}, [f"{case}: not collected" for case in CASES]),
    ],
    ids=["deselected-through-the-hook", "removed-without-the-hook", "k-in-addopts", "renamed"],
)
def test_one_case_of_a_parametrized_protected_test_must_still_be_collected(tmp_path, files, expected):
    root = _suite(tmp_path, files={WHOLE_FILE: PARAMETRIZED})
    pinned = _pinned(root)
    baseline = _baseline(root)
    _suite(root, files={WHOLE_FILE: PARAMETRIZED, **files})
    _context, problems = _caught(root, baseline, pinned)
    assert problems == expected


def test_a_deselected_case_is_caught_without_a_pinned_baseline(tmp_path):
    root = _suite(tmp_path, files={WHOLE_FILE: PARAMETRIZED})
    baseline = _baseline(root)
    _suite(root, files={WHOLE_FILE: PARAMETRIZED, "elsewhere/conftest.py": DESELECT_CASE})
    _context, problems = _caught(root, baseline, pinned=[])
    assert problems == [f"{CASES[1]}: not collected (deselected)"]


def test_a_case_added_to_a_parametrized_protected_test_passes_the_collection(tmp_path):
    root = _suite(tmp_path, files={WHOLE_FILE: PARAMETRIZED})
    pinned = _pinned(root)
    _suite(root, files={WHOLE_FILE: PARAMETRIZED.replace('["kept", "gone"]', '["kept", "gone", "added"]')})
    assert protected_tests.collection_problems([PROTECTED, METHOD, WHOLE_FILE], root, pinned=pinned) == []


# ─────────────────── A protected method in a file pytest does not collect ───────────────────
#
# live_verify's Command holds two protected nodes. pytest never collects that file, so the collection
# check cannot help: the context alone must catch what turns the method off or stops the run that holds
# it, in the class (its header, attributes, every other method) and at module level (a statement that
# names the method or its class).

COMMANDS = """class Base:
    def check(self):
        return None


class Command(Base):
    help = "Check the deployment."

    def handle(self):
        self.check()
        self.record("checked")

    def record(self, line):
        print(line)

    def check(self):
        assert 1 + 1 == 2


def helper():
    return 1
"""

COMMAND = "pkg/commands.py::Command::check"
CHECK_BODY = "        assert 1 + 1 == 2\n"


def _command_baseline(root):
    (root / "pkg").mkdir(exist_ok=True)
    (root / "pkg" / "commands.py").write_text(COMMANDS, encoding="utf-8")
    return protected_tests.digest(COMMAND, root), protected_tests.context_digest(COMMAND, root)


def _command_caught(root, baseline, module):
    """Whether the context of COMMAND changed once *module* replaces the file (its own source must not)."""
    (root / "pkg" / "commands.py").write_text(module, encoding="utf-8")
    source, context = baseline
    assert protected_tests.changed({COMMAND: source}, root) == [], "the case must leave the method's own hash alone"
    assert protected_tests.collection_problems([COMMAND], root) == [], "pytest never collects this file"
    return protected_tests.changed({COMMAND: context}, root, context=True) == [COMMAND]


def test_edits_beside_a_protected_class_in_a_file_pytest_does_not_collect_pass(tmp_path):
    baseline = _command_baseline(tmp_path)
    beside = COMMANDS.replace("    return 1\n", "    return 2\n")
    beside += "\n\ndef other():\n    return helper()\n"
    assert not _command_caught(tmp_path, baseline, beside)


@pytest.mark.parametrize(
    "module",
    [
        # Case X3: rebound by an assignment in the class, after the def.
        COMMANDS.replace(CHECK_BODY, CHECK_BODY + "\n    check = lambda self: None  # noqa: E731\n"),
        COMMANDS.replace(CHECK_BODY, CHECK_BODY + "\n    del check\n"),
        # Case X4: rebound, deleted or set at module level.
        COMMANDS + "\n\nCommand.check = lambda self: None\n",
        COMMANDS + "\n\ndel Command.check\n",
        COMMANDS + '\n\nsetattr(Command, "check", lambda self: None)\n',
        COMMANDS + "\n\n_command = Command\n_command.check = Base.check\n",
        # The run that holds it: the class's other methods, its header, and their rebinding.
        COMMANDS.replace("        self.check()\n", ""),
        COMMANDS.replace("class Command(Base):", "@staticmethod\nclass Command(Base):"),
        COMMANDS + "\n\nCommand.handle = lambda self: None\n",
    ],
    ids=[
        "in-class-assignment",
        "in-class-del",
        "module-assignment",
        "module-del",
        "module-setattr",
        "module-alias",
        "edited-handle",
        "class-decorator",
        "module-rebinds-handle",
    ],
)
def test_a_protected_method_in_a_file_pytest_does_not_collect_is_guarded_by_its_context(tmp_path, module):
    baseline = _command_baseline(tmp_path)
    assert _command_caught(tmp_path, baseline, module)


# ─────────────────── What collection cannot see, in a protected test's own file ───────────────────

OFF_PLUGIN = 'import pytest\n\n\ndef pytest_runtest_setup(item):\n    pytest.skip("off")\n'


def test_a_module_pytest_plugins_is_context(tmp_path):
    """A plugin the module loads can skip at run time, which collection never sees."""
    root = _suite(tmp_path, files={"pkg/_offplugin.py": OFF_PLUGIN})
    baseline = _baseline(root)
    _suite(root, GUARDED.replace("import pytest\n", 'import pytest\n\npytest_plugins = ["pkg._offplugin"]\n'))
    assert _caught(root, baseline) == ([PROTECTED, METHOD], [])


CODE_SWAP = (
    "_f = {name}\n"
    "_f.__code__ = (lambda *a, **k: None).__code__.replace(\n"
    "    co_name=_f.__code__.co_name, co_firstlineno=_f.__code__.co_firstlineno\n"
    ")\n"
)


@pytest.mark.parametrize("name, node", [("test_protected", PROTECTED), ("TestGroup.test_method", METHOD)])
def test_a_swapped_code_object_is_context(tmp_path, name, node):
    """A swapped ``__code__`` keeps the name and first line collection compares; the statement naming it is context."""
    root = _suite(tmp_path)
    baseline = _baseline(root)
    _suite(root, GUARDED + "\n\n" + CODE_SWAP.format(name=name))
    assert _caught(root, baseline) == ([node], [])
