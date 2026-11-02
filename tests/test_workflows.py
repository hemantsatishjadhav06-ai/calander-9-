"""The workflows' own guards (docs/specs/phase-3.md T10 and T11; spec D9).

GitHub runs these files, never this suite, so a guard written only in YAML can slip unseen. This module
reads ``.github/workflows/visual-baselines.yml`` and ``ci.yml`` and pins what a test can pin:

- the baseline run commits its images back to the branch, and only a job that runs no dependency,
  browser or project code holds the write token, and only for a branch of this repository (never a
  fork's pull request, never the default branch);
- a label added to the pull request cannot cancel a baseline run in progress, nor replace a pending
  Lighthouse targets measurement (no workflow-level concurrency; each job queues instead of cancelling);
- the specs input names what is photographed: blank is the default folder, whitespace alone or a path
  outside ``tests/e2e/visual/`` is refused (the step's own script is run here with bash);
- CI's Visual job compares once a baseline is committed in the tree or in the commit it is compared
  against, so a change that deletes every baseline fails the check instead of skipping it (the look
  job's own script is run here against small git histories), and then compares as before.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
SCREENSHOTS = "tests/e2e/__screenshots__"


def _load(name: str) -> dict[str, Any]:
    data = yaml.safe_load((WORKFLOWS / name).read_text())
    assert isinstance(data, dict), name
    return data


def _triggers(workflow: dict[Any, Any]) -> dict[str, Any]:
    # YAML 1.1 reads the bare key `on` as the boolean true.
    found = workflow.get("on", workflow.get(True))
    assert isinstance(found, dict)
    return found


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    steps = job.get("steps", [])
    assert isinstance(steps, list)
    return steps


def _script(job: dict[str, Any]) -> str:
    return "\n".join(str(step.get("run", "")) for step in _steps(job))


def _pushes(text: str) -> list[str]:
    """The lines of a script that run `git push` (with or without `git -c …` options before it)."""
    return [line for line in text.splitlines() if re.search(r"\bgit\b.*\spush\s", line)]


def _uses(job: dict[str, Any]) -> list[str]:
    return [str(step["uses"]) for step in _steps(job) if "uses" in step]


def _condition(value: Any) -> str:
    """An `if:` expression, its whitespace folded, so a test reads it as one line."""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _step(job: dict[str, Any], **match: str) -> dict[str, Any]:
    """The one step whose `name` or `id` is the given value."""
    found = [step for step in _steps(job) if all(step.get(key) == value for key, value in match.items())]
    assert len(found) == 1, match
    return found[0]


def _run_step(step: dict[str, Any], cwd: Path, tmp: Path, **env: str) -> tuple[int, str, dict[str, str]]:
    """Run a step's script as GitHub runs `shell: bash` (`bash --noprofile --norc -eo pipefail {0}`).

    Returns the exit status, the output (where `::error::` and `::notice` lines go) and what the step
    wrote to $GITHUB_ENV and $GITHUB_OUTPUT, read as `key=value` lines.
    """
    assert step.get("shell") == "bash", step.get("name")
    script = tmp / "step.sh"
    script.write_text(str(step["run"]))
    files = {"GITHUB_ENV": tmp / "github_env", "GITHUB_OUTPUT": tmp / "github_output"}
    for path in files.values():
        path.write_text("")
    done = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", str(script)],
        cwd=cwd,
        env={**_hermetic_env(tmp), **{key: str(path) for key, path in files.items()}, **env},
        capture_output=True,
        text=True,
        timeout=60,
    )
    written: dict[str, str] = {}
    for path in files.values():
        for line in path.read_text().splitlines():
            key, _, value = line.partition("=")
            written[key] = value
    return done.returncode, done.stdout + done.stderr, written


def _hermetic_env(tmp: Path) -> dict[str, str]:
    """PATH and a HOME of the test's own, so no person's git or shell configuration takes part."""
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp),
        "LANG": "C.UTF-8",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }


def _git(repo: Path, tmp: Path, *args: str) -> str:
    done = subprocess.run(
        [
            "git",
            "-c",
            "user.name=Workflow test",
            "-c",
            "user.email=workflow-test@e2e.test",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "init.defaultBranch=main",
            *args,
        ],
        cwd=repo,
        env=_hermetic_env(tmp),
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return done.stdout


def _assert_label_runs_cannot_cancel_or_replace(workflow: dict[str, Any]) -> None:
    """Every label added to the pull request starts a labelled workflow (its jobs then skip).

    A workflow-level group would put that run in the same group as the real one: with
    cancel-in-progress it cancels the run in progress, and even without it GitHub cancels a pending run
    of the group in favour of the newer one. Each job holds its own group instead, which a skipped job
    never enters, and queues.
    """
    assert "concurrency" not in workflow
    for name, job in workflow["jobs"].items():
        group = job.get("concurrency")
        assert isinstance(group, dict), f"{name} has no concurrency group of its own"
        assert group.get("cancel-in-progress") is False, name
        # One group per branch, whichever way the run was started (a dispatch and a label queue behind
        # each other).
        assert "github.head_ref || github.ref_name" in str(group["group"]), name


class TestVisualBaselinesWorkflow:
    workflow = _load("visual-baselines.yml")
    jobs: dict[str, dict[str, Any]] = workflow["jobs"]

    def _pushers(self) -> dict[str, dict[str, Any]]:
        return {name: job for name, job in self.jobs.items() if _pushes(_script(job))}

    def test_it_is_started_by_hand_or_by_its_label(self) -> None:
        triggers = _triggers(self.workflow)
        assert set(triggers) == {"workflow_dispatch", "pull_request"}
        assert triggers["pull_request"] == {"types": ["labeled"]}
        assert self.workflow["permissions"] == {"contents": "read"}

    def test_a_label_cannot_cancel_a_running_baseline(self) -> None:
        _assert_label_runs_cannot_cancel_or_replace(self.workflow)

    def test_the_photographs_are_still_uploaded_as_the_artifact(self) -> None:
        photographer = self.jobs["baselines"]
        uploads = [
            step for step in _steps(photographer) if str(step.get("uses", "")).startswith("actions/upload-artifact@")
        ]
        artifact = next(step for step in uploads if step["with"]["name"] == "visual-baselines")
        assert SCREENSHOTS + "/" in artifact["with"]["path"]
        assert "E2E_UPDATE_BASELINES" in str(photographer["steps"])

    def test_one_job_commits_the_baselines_back_and_pushes(self) -> None:
        pushers = self._pushers()
        assert list(pushers) == ["commit"], "exactly one job pushes, the commit job"
        commit = pushers["commit"]
        assert commit["needs"] in ("baselines", ["baselines"])
        script = _script(commit)
        # Only the baselines folder is staged, and a commit that would hold anything else stops.
        staged = [line.strip() for line in script.splitlines() if line.strip().startswith("git add")]
        assert staged and all(SCREENSHOTS in line for line in staged), staged
        assert "git diff --cached --quiet" in script, "an unchanged run commits nothing"
        # One commit whose subject starts with `visual:` and names the specs and the run.
        assert 'echo "visual: baselines for $SPECS (run $GITHUB_RUN_ID)"' in script
        assert script.count("git commit") == 1
        # Fast-forward only: a branch that moved on is never overwritten.
        pushes = _pushes(script)
        assert pushes
        for line in pushes:
            assert "--force" not in line and " -f" not in line and "+HEAD" not in line, line
            assert "HEAD:refs/heads/" in line, line

    def test_only_the_commit_job_may_write_and_it_runs_no_project_code(self) -> None:
        writers = {name for name, job in self.jobs.items() if (job.get("permissions") or {}).get("contents") == "write"}
        assert writers == {"commit"}
        assert self.jobs["commit"]["permissions"] == {"contents": "write"}
        # The job holding the write token installs nothing and runs no browser, test or server.
        script = _script(self.jobs["commit"])
        for runner in ("npm", "npx", "pip", "pip3", "python", "python3", "playwright", "node"):
            assert not re.search(rf"\b{runner}\b", script), runner
        assert all(
            uses.startswith(("actions/checkout@", "actions/download-artifact@")) for uses in _uses(self.jobs["commit"])
        )
        # The photographing job keeps the workflow's read-only token.
        assert self.jobs["baselines"].get("permissions", {"contents": "read"}) == {"contents": "read"}

    def test_the_push_is_guarded_to_a_branch_of_this_repository(self) -> None:
        condition = _condition(self.jobs["commit"].get("if"))
        # A pull request's head must be this repository: a fork's pull request is never pushed to.
        assert "github.event.pull_request.head.repo.full_name == github.repository" in condition
        # A dispatch runs on this repository's own ref, and only a branch is pushed to.
        assert "github.event_name == 'workflow_dispatch' && github.ref_type == 'branch'" in condition
        # Never the default branch.
        assert "!= github.event.repository.default_branch" in condition
        # No status function: GitHub adds success(), so a failed photograph run commits nothing.
        assert "always()" not in condition and "failure()" not in condition

    def test_the_token_reaches_only_the_push(self) -> None:
        commit = self.jobs["commit"]
        for step in _steps(commit):
            if str(step.get("uses", "")).startswith("actions/checkout@"):
                assert step["with"]["persist-credentials"] is False
        holders = [step for step in _steps(commit) if "github.token" in str(step.get("env", {}))]
        assert len(holders) == 1 and _pushes(str(holders[0]["run"]))
        for job in self.jobs.values():
            for step in _steps(job):
                assert "secrets." not in str(step), "no secret but the job's own token"

    def test_no_expression_is_written_into_a_script(self) -> None:
        # Inputs, branch names and outputs reach a script through the environment only.
        for name, job in self.jobs.items():
            assert "${{" not in _script(job), name

    @pytest.mark.parametrize(
        ("given", "checked"),
        [
            # No input (the label's run) or an emptied field: the whole folder.
            ("", "tests/e2e/visual"),
            ("tests/e2e/visual/shell.spec.ts", "tests/e2e/visual/shell.spec.ts"),
            (
                "  tests/e2e/visual/shell.spec.ts\ttests/e2e/visual/ ",
                "tests/e2e/visual/shell.spec.ts tests/e2e/visual/",
            ),
        ],
        ids=["empty", "one-spec", "two-paths-spaced"],
    )
    def test_the_specs_input_passes_on_only_checked_paths(self, tmp_path: Path, given: str, checked: str) -> None:
        step = _step(self.jobs["baselines"], name="Check the specs input")
        status, output, written = _run_step(step, tmp_path, tmp_path, SPECS=given)
        assert status == 0, output
        assert written == {"SPECS": checked, "specs": checked}

    @pytest.mark.parametrize(
        "given",
        [" ", "\t", " \t ", "\n", "tests/e2e/golden", "tests/e2e/visual/../golden", "--update-snapshots"],
        ids=["space", "tab", "space-and-tab", "newline", "outside", "dot-dot", "option"],
    )
    def test_the_specs_input_refuses_a_blank_selection_or_another_path(self, tmp_path: Path, given: str) -> None:
        # Whitespace alone selects no spec: passed on, the next step would run `npx playwright test`
        # with no filter, every spec in baseline-writing mode, and the commit would name no spec.
        step = _step(self.jobs["baselines"], name="Check the specs input")
        status, output, written = _run_step(step, tmp_path, tmp_path, SPECS=given)
        assert status != 0, output
        assert "::error::" in output
        assert written == {}, "nothing goes on to the next step or the commit"


class TestCiVisualJob:
    workflow = _load("ci.yml")
    jobs: dict[str, dict[str, Any]] = workflow["jobs"]

    def test_the_visual_job_compares_only_once_a_baseline_is_committed(self) -> None:
        visual = self.jobs["visual"]
        needs = visual.get("needs")
        needs = [needs] if isinstance(needs, str) else list(needs or [])
        assert len(needs) == 1, needs
        look = self.jobs[needs[0]]
        assert _condition(visual.get("if")) == f"needs.{needs[0]}.outputs.present == 'true'"
        # The job it waits for looks for a PNG under the baselines folder and says so when there is none.
        script = _script(look)
        assert SCREENSHOTS in script and "*.png" in script
        assert "::notice" in script
        output = look["outputs"]["present"]
        assert "steps." in output and ".outputs.present" in output
        assert "permissions" not in look, "it keeps the workflow's read-only token"

    def test_once_baselines_exist_it_compares_as_before(self) -> None:
        visual = self.jobs["visual"]
        assert visual["env"]["E2E_VISUAL"] == "1"
        assert visual["env"]["CI"] == "1"
        assert "E2E_UPDATE_BASELINES" not in str(visual), "the visual job compares and never writes"
        assert "npm run test:e2e -- tests/e2e/visual" in _script(visual)

    def _look(self) -> dict[str, Any]:
        return _step(self.jobs["visual-baselines-present"], id="look")

    def test_the_look_job_can_read_the_commit_before_without_a_token(self) -> None:
        look = self.jobs["visual-baselines-present"]
        checkout = next(step for step in _steps(look) if str(step.get("uses", "")).startswith("actions/checkout@"))
        # The checked-out commit and the one before it: for a pull request GitHub's merge commit and its
        # first parent, the base branch's head; for a push to main, main before the push's last commit.
        assert checkout["with"].get("fetch-depth") == 2
        assert checkout["with"]["persist-credentials"] is False
        assert "permissions" not in look and "secrets." not in str(look) and "github.token" not in str(look)
        assert "${{" not in _script(look), "nothing is interpolated into the script"

    @staticmethod
    def _history(tmp: Path, commits: Sequence[Mapping[str, bytes | None]], *, merge: bool = False) -> Path:
        """A repository whose commits apply each dict in turn ({path: content, or None to delete}).

        With `merge`, the last commit is made on a branch and merged into main with a merge commit, as
        GitHub builds `refs/pull/<n>/merge` (first parent: the base branch's head).
        """
        origin = tmp / "origin"
        origin.mkdir()
        _git(origin, tmp, "init", "--quiet")
        for index, files in enumerate(commits):
            if merge and index == len(commits) - 1:
                _git(origin, tmp, "checkout", "--quiet", "-b", "change")
            for relative, content in files.items():
                path = origin / relative
                if content is None:
                    _git(origin, tmp, "rm", "--quiet", relative)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
                    _git(origin, tmp, "add", relative)
            _git(origin, tmp, "commit", "--quiet", "--allow-empty", "-m", f"commit {index}")
        if merge:
            _git(origin, tmp, "checkout", "--quiet", "main")
            _git(origin, tmp, "merge", "--quiet", "--no-ff", "-m", "Merge change into main", "change")
        return origin

    def _look_in(self, tmp: Path, origin: Path, depth: int = 2) -> tuple[int, str, dict[str, str]]:
        # A shallow clone as actions/checkout makes it (fetch-depth), run where the job runs.
        clone = tmp / "clone"
        _git(tmp, tmp, "clone", "--quiet", f"--depth={depth}", origin.as_uri(), str(clone))
        work = tmp / "step"
        work.mkdir()
        return _run_step(self._look(), clone, work)

    KEEP = {f"{SCREENSHOTS}/.gitkeep": b""}
    PNG = f"{SCREENSHOTS}/visual/shell.spec.ts/home-light-desktop-chrome.png"

    def test_no_baseline_anywhere_skips_with_the_notice(self, tmp_path: Path) -> None:
        origin = self._history(tmp_path, [self.KEEP, {"README.md": b"x"}], merge=True)
        status, output, written = self._look_in(tmp_path, origin)
        assert status == 0, output
        assert written == {"present": "false"}
        assert "::notice" in output

    def test_a_baseline_in_the_tree_turns_the_comparison_on(self, tmp_path: Path) -> None:
        origin = self._history(tmp_path, [self.KEEP, {self.PNG: b"png"}], merge=True)
        status, output, written = self._look_in(tmp_path, origin)
        assert status == 0, output
        assert written == {"present": "true"}

    @pytest.mark.parametrize("merge", [True, False], ids=["pull-request", "push-to-main"])
    def test_deleting_every_baseline_still_compares_and_fails(self, tmp_path: Path, merge: bool) -> None:
        # The base (or main before the push) has a baseline and this change deletes it: the Visual job
        # must run and fail on the missing image, not skip (a skipped check counts as passing).
        origin = self._history(tmp_path, [{**self.KEEP, self.PNG: b"png"}, {self.PNG: None}], merge=merge)
        status, output, written = self._look_in(tmp_path, origin)
        assert status == 0, output
        assert written == {"present": "true"}
        assert "::warning title=Every baseline removed::" in output

    def test_without_the_commit_before_it_stops_instead_of_skipping(self, tmp_path: Path) -> None:
        # A checkout one commit deep cannot see the base; the job fails rather than guess "no baseline".
        origin = self._history(tmp_path, [{**self.KEEP, self.PNG: b"png"}, {self.PNG: None}], merge=True)
        status, output, written = self._look_in(tmp_path, origin, depth=1)
        assert status != 0, output
        assert "::error" in output
        assert written == {}

    def test_no_job_condition_uses_hash_files(self) -> None:
        # hashFiles() is not available in a job's `if` (GitHub evaluates it before the job has a
        # workspace), so a job-level guard on files must go through another job's output.
        for name in ("ci.yml", "visual-baselines.yml", "lighthouse-targets.yml"):
            for job_name, job in _load(name)["jobs"].items():
                assert "hashFiles" not in str(job.get("if", "")), f"{name}: {job_name}"


class TestLighthouseTargetsWorkflow:
    workflow = _load("lighthouse-targets.yml")

    def test_a_label_cannot_replace_a_pending_measurement(self) -> None:
        # Every label added to the pull request starts this workflow too; a workflow-level group would
        # let that run replace a measurement waiting for its turn.
        assert _triggers(self.workflow)["pull_request"] == {"types": ["labeled"]}
        _assert_label_runs_cannot_cancel_or_replace(self.workflow)
