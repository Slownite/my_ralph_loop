"""Shared helpers for real temporary-repository tests."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_TEMPLATE = """\
config_version = 1
target_branch = "main"
issue_directory = "docs/issues"

[harness]
profile = "custom"
command = ["{harness}"]

[run]
max_issues = {max_issues}
max_attempts_per_issue = {max_attempts}
attempt_timeout_seconds = {timeout}

[commands]
test = {test_command}

[merge]
auto = {auto}
push = {push}

[sandbox]
verification_network = false
environment_allowlist = []

[telemetry]
max_runs = 100
max_age_days = 30
"""

DEFAULT_ISSUE = """\
---
status: pending
---

# Add a feature

## Acceptance criteria

- [ ] A new file exists
"""


def git(project: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    )


def write_executable(path: Path, source: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env python3\n" + source)
    path.chmod(0o755)
    return path


@dataclass
class Project:
    """A real temporary repository with a fake external Harness."""

    root: Path
    state: Path
    harness: Path
    extra_environment: dict[str, str] = field(default_factory=dict)

    def run(self, *arguments: str, expect: int | None = None) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["XDG_STATE_HOME"] = str(self.state)
        environment.update(self.extra_environment)
        result = subprocess.run(
            ["ralf-loop", *arguments],
            cwd=self.root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        if expect is not None:
            assert result.returncode == expect, (
                f"expected exit {expect}, got {result.returncode}\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )
        return result

    def issue(self, number: int = 1) -> Path:
        matches = sorted((self.root / "docs" / "issues").glob(f"{number:03d}-*.md"))
        assert matches, f"issue {number} does not exist"
        return matches[0]

    def issue_text(self, number: int = 1) -> str:
        return self.issue(number).read_text()

    def log(self) -> str:
        return git(self.root, "log", "--oneline").stdout

    def worktrees(self) -> list[str]:
        return [
            line[len("worktree ") :]
            for line in git(self.root, "worktree", "list", "--porcelain").stdout.splitlines()
            if line.startswith("worktree ")
        ]


def create_project(
    directory: Path,
    *,
    harness_source: str,
    test_command: str = '["true"]',
    max_attempts: int = 3,
    max_issues: int = 1,
    timeout: int = 30,
    auto: bool = True,
    push: bool = False,
    extra_config: str = "",
    issues: dict[str, str] | None = None,
    tracked_files: dict[str, str] | None = None,
    remote: bool = False,
) -> Project:
    root = directory / "project"
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "ralf@example.test")
    git(root, "config", "user.name", "Ralf Test")

    (root / "seed.txt").write_text("seed\n")
    for relative, content in (tracked_files or {}).items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    issues_directory = root / "docs" / "issues"
    issues_directory.mkdir(parents=True)
    for name, content in (issues or {"001-add-feature.md": DEFAULT_ISSUE}).items():
        (issues_directory / name).write_text(content)

    harness = write_executable(directory / "fake-harness.py", harness_source)
    (root / "ralf.toml").write_text(
        CONFIG_TEMPLATE.format(
            harness=harness,
            max_issues=max_issues,
            max_attempts=max_attempts,
            timeout=timeout,
            test_command=test_command,
            auto="true" if auto else "false",
            push="true" if push else "false",
        )
        + extra_config
    )
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "project setup")

    if remote:
        _add_remote(directory, root)

    return Project(root=root, state=directory / "xdg-state", harness=harness)


def _add_remote(directory: Path, root: Path) -> None:
    origin = directory / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-q", "-b", "main", str(origin)],
        check=True,
        capture_output=True,
        text=True,
    )
    git(root, "remote", "add", "origin", str(origin))
    git(root, "push", "-q", "-u", "origin", "main")
