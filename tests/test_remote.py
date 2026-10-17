"""Remote synchronization and optional publishing tests using local bare remotes."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .support import Project, create_project, git

SUCCESS = """\
import sys
from pathlib import Path

sys.stdin.read()
Path("feature.txt").write_text("done\\n")
"""


def _remote_head(project: Project) -> str:
    return subprocess.run(
        ["git", "rev-parse", "main"],
        cwd=project.root.parent / "origin.git",
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _advance_remote(project: Project, message: str = "remote advance") -> None:
    other = project.root.parent / "other"
    subprocess.run(
        ["git", "clone", "-q", str(project.root.parent / "origin.git"), str(other)],
        check=True,
        capture_output=True,
        text=True,
    )
    git(other, "config", "user.email", "other@example.test")
    git(other, "config", "user.name", "Other")
    (other / "remote.txt").write_text(message)
    git(other, "add", ".")
    git(other, "commit", "-q", "-m", message)
    git(other, "push", "-q", "origin", "main")


def test_remote_push_is_disabled_by_default(tmp_path: Path) -> None:
    project = create_project(tmp_path, harness_source=SUCCESS, remote=True, auto=True)

    project.run("run", "--no-sandbox", expect=0)

    assert "status: done" in project.issue_text()
    assert _remote_head(project) != git(project.root, "rev-parse", "main").stdout.strip()


def test_explicit_push_publishes_after_done(tmp_path: Path) -> None:
    project = create_project(tmp_path, harness_source=SUCCESS, remote=True, auto=True, push=True)

    project.run("run", "--no-sandbox", expect=0)

    assert "status: done" in project.issue_text()
    assert _remote_head(project) == git(project.root, "rev-parse", "main").stdout.strip()


def test_remote_fast_forwards_the_target(tmp_path: Path) -> None:
    project = create_project(tmp_path, harness_source=SUCCESS, remote=True, auto=False)
    _advance_remote(project)

    project.run("run", "--no-sandbox", expect=0)

    log = subprocess.run(
        ["git", "log", "--format=%s"],
        cwd=project.root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "remote advance" in log
    assert "status: ready" in project.issue_text()


def test_diverged_target_stops_before_mutation(tmp_path: Path) -> None:
    project = create_project(tmp_path, harness_source=SUCCESS, remote=True, auto=False)
    _advance_remote(project)
    (project.root / "local.txt").write_text("local\n")
    git(project.root, "add", ".")
    git(project.root, "commit", "-q", "-m", "local advance")

    result = project.run("run", "--no-sandbox")

    assert result.returncode == 2
    assert "diverged" in result.stderr
    assert "status: pending" in project.issue_text()


def test_dry_run_reports_divergence_from_the_last_known_upstream(tmp_path: Path) -> None:
    project = create_project(tmp_path, harness_source=SUCCESS, remote=True, auto=False)
    _advance_remote(project)
    git(project.root, "fetch", "origin")
    (project.root / "local.txt").write_text("local\n")
    git(project.root, "add", ".")
    git(project.root, "commit", "-q", "-m", "local advance")

    result = project.run("run", "--dry-run", "--no-sandbox")

    assert result.returncode == 2
    assert "diverged" in result.stderr
    assert "status: pending" in project.issue_text()


def test_push_failure_is_infrastructure_failure_and_preserves_local_work(tmp_path: Path) -> None:
    project = create_project(tmp_path, harness_source=SUCCESS, remote=True, auto=True, push=True)
    hook = project.root.parent / "origin.git" / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)

    result = project.run("run", "--no-sandbox")

    assert result.returncode == 4
    assert "status: done" in project.issue_text()
    assert _remote_head(project) != git(project.root, "rev-parse", "main").stdout.strip()
