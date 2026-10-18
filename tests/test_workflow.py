"""End-to-end workflow tests over real temporary repositories and fake Harnesses."""

from __future__ import annotations

import fcntl
import json
import subprocess
from pathlib import Path

import pytest

from ralf.git import GitError, GitRepository
from ralf.issues import IssueStatus
from ralf.orchestrator import InfrastructureFailure, Workflow
from ralf.plan import PreflightError, build_plan, load_settings
from ralf.sandbox import SandboxUnavailable

from .support import DEFAULT_ISSUE, Project, create_project, git, write_executable

SUCCESS = """\
import sys
from pathlib import Path

sys.stdin.read()
Path("feature.txt").write_text("done\\n")
print("harness ran")
"""

NOOP = """\
import sys

sys.stdin.read()
print("nothing to see")
"""

FAILURE = """\
import sys

sys.stdin.read()
print("boom", file=sys.stderr)
raise SystemExit(3)
"""

TAMPER_ISSUE = """\
import sys
from pathlib import Path

sys.stdin.read()
Path("docs/issues/001-add-feature.md").write_text("tampered")
"""

DELETE_TEST = """\
import sys
from pathlib import Path

sys.stdin.read()
Path("tests/test_sample.py").unlink()
Path("feature.txt").write_text("done\\n")
"""


def test_pending_issue_becomes_ready_without_merging(tmp_path: Path) -> None:
    project = create_project(tmp_path, harness_source=SUCCESS, auto=False)

    project.run("run", "--no-sandbox", expect=0)

    text = project.issue_text()
    assert "status: ready" in text
    assert "branch: ralf/issue-1-add-feature" in text
    assert "attempts: 1" in text
    assert "ralf: merge issue 1" not in project.log()
    assert any("issue-1" in path for path in project.worktrees())
    assert git(project.root, "rev-parse", "--verify", "ralf/issue-1-add-feature").stdout.strip()


def test_finalize_merges_ready_issue_and_commits_done(tmp_path: Path) -> None:
    project = create_project(tmp_path, harness_source=SUCCESS, auto=False)
    project.run("run", "--no-sandbox", expect=0)

    project.run("finalize", "1", "--no-sandbox", expect=0)

    assert "status: done" in project.issue_text()
    log = project.log()
    assert "ralf: merge issue 1" in log
    assert "ralf: done issue 1" in log
    assert (project.root / "feature.txt").read_text() == "done\n"
    assert not any("issue-1" in path for path in project.worktrees())


def test_auto_merge_runs_the_whole_queue(tmp_path: Path) -> None:
    project = create_project(tmp_path, harness_source=SUCCESS, auto=True)

    project.run("run", "--no-sandbox", expect=0)

    assert "status: done" in project.issue_text()
    assert (project.root / "feature.txt").read_text() == "done\n"


def test_zero_diff_success_consumes_attempts_and_blocks(tmp_path: Path) -> None:
    project = create_project(tmp_path, harness_source=NOOP, max_attempts=2, auto=False)

    result = project.run("run", "--no-sandbox")

    assert result.returncode == 3
    text = project.issue_text()
    assert "status: blocked" in text
    assert "attempts: 2" in text
    assert any("issue-1" in path for path in project.worktrees())


def test_protected_path_edit_is_rejected(tmp_path: Path) -> None:
    project = create_project(tmp_path, harness_source=TAMPER_ISSUE, max_attempts=1, auto=False)

    result = project.run("run", "--no-sandbox")

    assert result.returncode == 3
    assert "status: blocked" in project.issue_text()


def test_pre_existing_test_deletion_is_rejected(tmp_path: Path) -> None:
    project = create_project(
        tmp_path,
        harness_source=DELETE_TEST,
        max_attempts=1,
        auto=False,
        tracked_files={"tests/test_sample.py": "def test_sample():\n    assert True\n"},
    )

    result = project.run("run", "--no-sandbox")

    assert result.returncode == 3
    assert "status: blocked" in project.issue_text()


def test_explicit_test_deletion_exception_is_honoured(tmp_path: Path) -> None:
    project = create_project(
        tmp_path,
        harness_source=DELETE_TEST,
        max_attempts=1,
        auto=False,
        tracked_files={"tests/test_sample.py": "def test_sample():\n    assert True\n"},
        extra_config='\n[guards]\nallowed_test_deletions = ["tests/test_sample.py"]\n',
    )

    project.run("run", "--no-sandbox", expect=0)

    assert "status: ready" in project.issue_text()


def test_infrastructure_failure_preserves_work_without_consuming_attempt(tmp_path: Path) -> None:
    project = create_project(tmp_path, harness_source=FAILURE, max_attempts=3, auto=False)

    result = project.run("run", "--no-sandbox")

    assert result.returncode == 4
    text = project.issue_text()
    assert "status: in_progress" in text
    assert "attempts: 0" in text
    assert any("issue-1" in path for path in project.worktrees())


def test_retry_resumes_blocked_work_with_a_fresh_allowance(tmp_path: Path) -> None:
    project = create_project(tmp_path, harness_source=NOOP, max_attempts=1, auto=False)
    project.run("run", "--no-sandbox", expect=3)
    assert "status: blocked" in project.issue_text()

    write_executable(project.harness, SUCCESS)
    project.run("retry", "1", "--no-sandbox", expect=0)

    text = project.issue_text()
    assert "status: ready" in text
    assert "attempts: 2" in text


def test_verification_failure_consumes_an_attempt_and_retries(tmp_path: Path) -> None:
    counter = tmp_path / "verification-count"
    verifier = write_executable(
        tmp_path / "verify.py",
        f"""\
import sys
from pathlib import Path

path = Path({str(counter)!r})
count = int(path.read_text()) if path.exists() else 0
count += 1
path.write_text(str(count))
raise SystemExit(0 if count >= 2 else 1)
""",
    )
    project = create_project(
        tmp_path,
        harness_source=SUCCESS,
        test_command=json.dumps([str(verifier)]),
        max_attempts=3,
        auto=False,
    )

    project.run("run", "--no-sandbox", expect=0)

    text = project.issue_text()
    assert "status: ready" in text
    assert "attempts: 2" in text


def _refs(project: Project) -> str:
    return git(project.root, "for-each-ref", "--format=%(refname) %(objectname)").stdout


def _state_entries(project: Project) -> list[str]:
    if not project.state.exists():
        return []
    return sorted(path.relative_to(project.state).as_posix() for path in project.state.rglob("*"))


def test_dry_run_reports_a_plan_without_mutation(tmp_path: Path) -> None:
    project = create_project(tmp_path, harness_source=SUCCESS, auto=True, remote=True)
    head = git(project.root, "rev-parse", "HEAD").stdout
    refs_before = _refs(project)
    issue_before = project.issue_text()
    config_before = (project.root / "ralf.toml").read_text()
    state_before = _state_entries(project)
    worktrees_before = project.worktrees()

    result = project.run("run", "--dry-run", "--no-sandbox", expect=0)

    assert "run plan" in result.stdout
    assert "0001 pending" in result.stdout
    assert "harness executable:" in result.stdout
    assert "origin" in result.stdout
    assert git(project.root, "rev-parse", "HEAD").stdout == head
    assert _refs(project) == refs_before
    assert project.issue_text() == issue_before
    assert (project.root / "ralf.toml").read_text() == config_before
    assert project.worktrees() == worktrees_before
    assert _state_entries(project) == state_before


def test_missing_bubblewrap_blocks_a_plan_unless_the_run_overrides_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(tmp_path, harness_source=SUCCESS, auto=False)
    monkeypatch.chdir(project.root)
    settings = load_settings(project.root / "ralf.toml")
    repository = GitRepository(project.root)

    def unavailable(*_args: object, **_kwargs: object) -> None:
        raise SandboxUnavailable("isolation executable was not found")

    monkeypatch.setattr("ralf.plan.require_bubblewrap", unavailable)

    with pytest.raises(PreflightError, match="isolation executable"):
        build_plan(settings, repository, no_sandbox=False, remote=None, fetch=False)

    plan = build_plan(settings, repository, no_sandbox=True, remote=None, fetch=False)
    assert plan.sandbox == "disabled_by_override"


def test_status_commit_failure_is_an_infrastructure_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(tmp_path, harness_source=SUCCESS, auto=False)
    workflow = Workflow(project.root, project.root / "ralf.toml", no_sandbox=True, local=True)
    failed = subprocess.CompletedProcess(["git", "commit"], 1, stdout="", stderr="index is locked")

    def failing_commit(message: str) -> str:
        raise GitError(("commit",), failed)

    monkeypatch.setattr(workflow.repository, "commit", failing_commit)

    with pytest.raises(InfrastructureFailure):
        workflow._commit_status(
            project.issue(1),
            IssueStatus.READY,
            branch="ralf/issue-1-add-feature",
            attempts=1,
            message="ralf: issue 1 ready",
        )


def test_malformed_issue_blocks_the_plan(tmp_path: Path) -> None:
    project = create_project(tmp_path, harness_source=SUCCESS, auto=False)
    (project.root / "docs" / "issues" / "bad.md").write_text("---\nstatus: pending\n---\n")
    git(project.root, "add", ".")
    git(project.root, "commit", "-q", "-m", "malformed")

    result = project.run("run", "--no-sandbox")

    assert result.returncode == 2
    assert "bad.md" in result.stderr


def test_repository_lock_prevents_concurrent_runs(tmp_path: Path) -> None:
    project = create_project(tmp_path, harness_source=SUCCESS, auto=False)
    git_directory = Path(git(project.root, "rev-parse", "--absolute-git-dir").stdout.strip())
    handle = (git_directory / "ralf.lock").open("w")
    fcntl.flock(handle, fcntl.LOCK_EX)
    try:
        result = project.run("run", "--no-sandbox")
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()

    assert result.returncode == 2
    assert "another Ralf process" in result.stderr


def test_status_json_exposes_workflow_state(tmp_path: Path) -> None:
    project = create_project(tmp_path, harness_source=SUCCESS, auto=False)
    project.run("run", "--no-sandbox", expect=0)

    result = project.run("status", "--json", expect=0)

    state = json.loads(result.stdout)
    assert state["target_branch"] == "main"
    assert state["issues"][0]["status"] == "ready"
    assert state["issues"][0]["attempts"] == 1
    assert state["issues"][0]["worktree_preserved"] is True


def test_run_respects_max_issues_without_touching_the_rest(tmp_path: Path) -> None:
    project = create_project(
        tmp_path,
        harness_source=SUCCESS,
        auto=True,
        max_issues=1,
        issues={"001-first.md": DEFAULT_ISSUE, "002-second.md": DEFAULT_ISSUE},
    )

    project.run("run", "--no-sandbox", expect=0)

    assert "status: done" in project.issue(1).read_text()
    assert "status: pending" in project.issue(2).read_text()


def test_pending_issues_are_processed_by_numeric_prefix(tmp_path: Path) -> None:
    project = create_project(
        tmp_path,
        harness_source=SUCCESS,
        auto=False,
        max_issues=2,
        issues={"002-second.md": DEFAULT_ISSUE, "001-first.md": DEFAULT_ISSUE},
    )

    project.run("run", "--no-sandbox", expect=0)

    assert "status: ready" in project.issue(1).read_text()
    assert "status: ready" in project.issue(2).read_text()


def test_run_without_remote_skips_remote_planning(tmp_path: Path) -> None:
    project = create_project(tmp_path, harness_source=SUCCESS, auto=False)

    result = project.run("run", "--dry-run", "--no-sandbox", expect=0)

    assert "no remote" in result.stdout


def test_each_attempt_is_a_fresh_harness_process(tmp_path: Path) -> None:
    project = create_project(tmp_path, harness_source=SUCCESS, auto=False)

    project.run("run", "--no-sandbox", expect=0)

    state = json.loads(project.run("status", "--json", expect=0).stdout)
    assert state["issues"][0]["status"] == "ready"


def test_commit_history_orders_in_progress_ready_and_done(tmp_path: Path) -> None:
    project = create_project(tmp_path, harness_source=SUCCESS, auto=True)

    project.run("run", "--no-sandbox", expect=0)

    log = subprocess.run(
        ["git", "log", "--format=%s", "--reverse"],
        cwd=project.root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    start = log.index("ralf: start issue 1")
    ready = log.index("ralf: issue 1 ready")
    merge = log.index("ralf: merge issue 1")
    done = log.index("ralf: done issue 1")
    assert start < ready < merge < done
