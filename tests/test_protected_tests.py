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
``pytestmark``, a mark or an autouse fixture on its class, a later rebinding or ``del`` of its name,
a ``conftest.py`` that ignores, deselects or skips it. Two more checks close those. The context hashes
(``tests/fixtures/protected_context.json``, also written once from ``045978b``) cover, for each
per-test node, the module's ``pytestmark`` and autouse or xunit setup, and the enclosing class's
header and every statement of its body that is not a ``test_*`` test. The collection check runs
pytest's own collection of the protected files once, as the full suite would (``pyproject.toml``,
every ``conftest.py``), and fails when a protected test is not collected, is marked skip, skipif or
xfail, or would run anything but the def its hash covers.
"""

import json
import time
import tomllib
from pathlib import Path

import pytest

from tools import protected_tests

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "protected_tests.json"
CONTEXT = ROOT / "tests" / "fixtures" / "protected_context.json"

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
    changed = protected_tests.changed(fixture["nodes"], ROOT, context=True)
    assert not changed, (
        "What decides whether these protected tests run (their module's pytestmark or autouse setup, their "
        "class's marks, fixtures, setup or attributes) differs from 045978b (spec D11): " + ", ".join(changed)
    )


def test_every_protected_test_is_collected_unmarked_and_runs_its_own_def():
    began = time.monotonic()
    problems = protected_tests.collection_problems(protected_tests.load(FIXTURE), ROOT)
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
# Each case leaves every own-source hash unchanged; the context hashes (the module's pytestmark and
# the enclosing class's decorators, fixtures, setup and attributes) and the collection check (pytest's
# own collection, run as the suite runs it) must catch it.

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


def _caught(root, baseline):
    """(context hashes that changed, collection problems), once the own-source hashes say nothing."""
    hashes, context = baseline
    assert protected_tests.changed(hashes, root) == [], "the case must leave every own-source hash alone"
    return protected_tests.changed(context, root, context=True), protected_tests.collection_problems(list(hashes), root)


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
