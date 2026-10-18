"""Infrastructure-failure, interruption, and resume tests with real child processes."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

from .support import Project, create_project, git, write_executable

SUCCESS = """\
import sys
from pathlib import Path

sys.stdin.read()
Path("feature.txt").write_text("done\\n")
"""


def _sleeping_harness(marker: Path) -> str:
    return f"""\
import signal
import time
from pathlib import Path

signal.signal(signal.SIGTERM, signal.SIG_DFL)
Path({str(marker)!r}).write_text("started")
time.sleep(60)
"""


def _start_run(project: Project) -> subprocess.Popen[str]:
    environment = os.environ.copy()
    environment["XDG_STATE_HOME"] = str(project.state)
    return subprocess.Popen(
        ["ralf-loop", "run", "--local", "--no-sandbox"],
        cwd=project.root,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _wait_for(path: Path, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            return
        time.sleep(0.05)
    raise AssertionError(f"{path} was not created in time")


def test_sigterm_preserves_in_progress_work_and_exits_nonzero(tmp_path: Path) -> None:
    marker = tmp_path / "harness-started"
    project = create_project(tmp_path, harness_source=_sleeping_harness(marker), auto=False)

    process = _start_run(project)
    try:
        _wait_for(marker)
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=30)
    finally:
        if process.poll() is None:
            process.kill()

    assert process.returncode == 130, (stdout, stderr)
    assert "status: in_progress" in project.issue_text()
    assert any("issue-1" in path for path in project.worktrees())


def test_restart_resumes_preserved_in_progress_work(tmp_path: Path) -> None:
    marker = tmp_path / "harness-started"
    project = create_project(tmp_path, harness_source=_sleeping_harness(marker), auto=False)
    process = _start_run(project)
    try:
        _wait_for(marker)
        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=30)
    finally:
        if process.poll() is None:
            process.kill()

    write_executable(project.harness, SUCCESS)
    project.run("run", "--no-sandbox", expect=0)

    assert "status: ready" in project.issue_text()


def test_ambiguous_preserved_state_blocks_without_mutation(tmp_path: Path) -> None:
    marker = tmp_path / "harness-started"
    project = create_project(tmp_path, harness_source=_sleeping_harness(marker), auto=False)
    process = _start_run(project)
    try:
        _wait_for(marker)
        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=30)
    finally:
        if process.poll() is None:
            process.kill()

    worktree = next(path for path in project.worktrees() if "issue-1" in path)
    git(project.root, "worktree", "remove", "--force", worktree)
    git(project.root, "worktree", "prune")

    project.run("run", "--no-sandbox", expect=0)

    assert "status: blocked" in project.issue_text()


def test_interrupted_run_leaves_no_partial_commit(tmp_path: Path) -> None:
    marker = tmp_path / "harness-started"
    project = create_project(tmp_path, harness_source=_sleeping_harness(marker), auto=False)
    process = _start_run(project)
    try:
        _wait_for(marker)
        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=30)
    finally:
        if process.poll() is None:
            process.kill()

    log = project.log()
    assert "ralf: implement issue 1" not in log
    assert "ralf: issue 1 ready" not in log
