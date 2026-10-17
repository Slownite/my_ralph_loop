"""Public Git value validation and repository operations.

Ralf, not the Harness, owns every Git mutation. This module is the single place
where Ralf talks to Git, so the safe defaults (no hooks, no interactive signing)
and the classification of Git failures stay consistent.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

_SAFE_CONFIG = (
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "tag.gpgsign=false",
    "-c",
    "advice.detachedHead=false",
)


def is_valid_branch_name(branch: str) -> bool:
    """Return whether Git accepts a branch name without requiring a repository."""

    result = subprocess.run(
        ["git", "check-ref-format", "--branch", branch],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


@dataclass(frozen=True, slots=True)
class Change:
    """One path-level change between two trees."""

    status: str
    path: str
    previous_path: str | None = None


class GitError(RuntimeError):
    """A Git command Ralf owns failed."""

    def __init__(
        self, arguments: tuple[str, ...], result: subprocess.CompletedProcess[str]
    ) -> None:
        self.arguments = arguments
        self.result = result
        detail = result.stderr.strip() or result.stdout.strip() or "no output"
        super().__init__(f"git {' '.join(arguments)} failed: {detail}")


class GitRepository:
    """The repository Ralf operates on, rooted at its working tree."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _run(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        command = ("git", *_SAFE_CONFIG, *arguments)
        result = subprocess.run(
            command,
            cwd=self.root,
            check=False,
            capture_output=True,
            text=True,
        )
        if check and result.returncode != 0:
            raise GitError(arguments, result)
        return result

    def git_directory(self) -> Path:
        """Return the absolute Git directory, including for linked worktrees."""

        return Path(self._run("rev-parse", "--absolute-git-dir").stdout.strip())

    # -- inspection -------------------------------------------------------

    def current_branch(self) -> str:
        return self._run("branch", "--show-current").stdout.strip()

    def head(self) -> str:
        return self._run("rev-parse", "HEAD").stdout.strip()

    def branch_exists(self, name: str) -> bool:
        result = self._run("rev-parse", "--verify", "--quiet", f"refs/heads/{name}", check=False)
        return result.returncode == 0

    def is_clean(self) -> bool:
        return self._run("status", "--porcelain").stdout.strip() == ""

    def has_remote(self, name: str = "origin") -> bool:
        return name in self._run("remote").stdout.split()

    def upstream(self, name: str = "origin", branch: str | None = None) -> str:
        reference = branch or self.current_branch()
        return f"refs/remotes/{name}/{reference}"

    def has_upstream(self, name: str = "origin", branch: str | None = None) -> bool:
        return (
            self._run("rev-parse", "--verify", "--quiet", self.upstream(name, branch)).returncode
            == 0
        )

    def is_ancestor(self, older: str, newer: str) -> bool:
        return self._run("merge-base", "--is-ancestor", older, newer, check=False).returncode == 0

    def staged_changes(self, base: str) -> list[Change]:
        """Return staged-and-working changes relative to a base, including new files."""

        self._run("add", "--all")
        return _parse_name_status(self._run("diff", "--cached", "--name-status", "-M", base).stdout)

    def merge_base(self, first: str, second: str) -> str:
        return self._run("merge-base", first, second).stdout.strip()

    def abort_merge(self) -> None:
        self._run("merge", "--abort", check=False)

    def worktrees(self) -> list[Path]:
        output = self._run("worktree", "list", "--porcelain").stdout
        paths: list[Path] = []
        for line in output.splitlines():
            if line.startswith("worktree "):
                paths.append(Path(line[len("worktree ") :]))
        return paths

    # -- mutation ---------------------------------------------------------

    def fetch(self, remote: str = "origin") -> None:
        self._run("fetch", "--prune", remote)

    def fast_forward(self, target: str) -> None:
        """Move the current branch forward only when the target is an ancestor."""

        self._run("merge", "--ff-only", target)

    def create_branch(self, branch: str, start: str) -> None:
        self._run("branch", branch, start)

    def switch(self, branch: str) -> None:
        self._run("switch", branch)

    def worktree_add(self, path: Path, branch: str) -> None:
        self._run("worktree", "add", "--force", str(path), branch)

    def worktree_remove(self, path: Path) -> None:
        self._run("worktree", "remove", "--force", str(path))

    def stage_all(self) -> None:
        self._run("add", "--all")

    def has_staged_changes(self) -> bool:
        return self._run("diff", "--cached", "--quiet", check=False).returncode == 1

    def commit(self, message: str) -> str:
        self._run("commit", "--no-verify", "-m", message)
        return self.head()

    def merge_no_ff(self, branch: str, message: str) -> str:
        self._run("merge", "--no-ff", "--no-edit", "-m", message, branch)
        return self.head()

    def push(self, remote: str, branch: str) -> None:
        self._run("push", remote, f"refs/heads/{branch}:refs/heads/{branch}")


def _parse_name_status(output: str) -> list[Change]:
    """Parse ``git diff --name-status`` output, including renames and copies."""

    changes: list[Change] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        status = fields[0]
        if status.startswith(("R", "C")):
            changes.append(Change(status=status[0], path=fields[2], previous_path=fields[1]))
        else:
            changes.append(Change(status=status[0], path=fields[1]))
    return changes
