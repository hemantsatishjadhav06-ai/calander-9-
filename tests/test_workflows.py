"""The workflows' own guards (docs/specs/phase-3.md T10 and T11; spec D9).

GitHub runs these files, never this suite, so a guard written only in YAML can slip unseen. This module
reads ``.github/workflows/visual-baselines.yml`` and ``ci.yml`` and pins what a test can pin:

- the baseline run commits its images back to the branch, and only a job that runs no dependency,
  browser or project code holds the write token, and only for a branch of this repository (never a
  fork's pull request, never the default branch);
- a label added to the pull request cannot cancel a baseline run in progress (no workflow-level
  concurrency; each job queues instead of cancelling);
- CI's Visual job compares only once a baseline is committed, and then compares as before.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

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
        # Every label added to the pull request starts this workflow (its jobs then skip). A
        # workflow-level group with cancel-in-progress would cancel the run that is photographing.
        assert "concurrency" not in self.workflow
        for name, job in self.jobs.items():
            group = job.get("concurrency")
            assert isinstance(group, dict), f"{name} has no concurrency group of its own"
            assert group.get("cancel-in-progress") is False, name
            # One group per branch, whichever way the run was started.
            assert "github.head_ref || github.ref_name" in str(group["group"]), name

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

    def test_no_job_condition_uses_hash_files(self) -> None:
        # hashFiles() is not available in a job's `if` (GitHub evaluates it before the job has a
        # workspace), so a job-level guard on files must go through another job's output.
        for name in ("ci.yml", "visual-baselines.yml", "lighthouse-targets.yml"):
            for job_name, job in _load(name)["jobs"].items():
                assert "hashFiles" not in str(job.get("if", "")), f"{name}: {job_name}"
