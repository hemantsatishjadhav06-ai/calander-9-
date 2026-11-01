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
"""

import json
from pathlib import Path

from tools import protected_tests

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "protected_tests.json"

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
