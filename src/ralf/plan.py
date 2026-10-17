"""Repository preflight, one exact execution plan, and the single-process lock."""

from __future__ import annotations

import fcntl
import os
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from ralf.config import validate_config
from ralf.git import GitError, GitRepository
from ralf.harness import probe_executable, resolve_harness
from ralf.issues import IssueStatus, issue_files, issue_number, load_issue, validate_issues
from ralf.sandbox import SandboxUnavailable, require_bubblewrap
from ralf.settings import Settings


class PreflightError(RuntimeError):
    """Validation or preflight blocked work before any mutation."""

    def __init__(self, messages: list[str]) -> None:
        self.messages = messages
        super().__init__("; ".join(messages))


@dataclass(frozen=True, slots=True)
class PlannedIssue:
    number: int
    status: IssueStatus
    branch: str | None


@dataclass(frozen=True, slots=True)
class RunPlan:
    """One exact, inspectable execution plan."""

    target_branch: str
    issues: tuple[PlannedIssue, ...]
    selected: int | None
    harness_profile: str
    harness_command: tuple[str, ...]
    harness_executable: str
    harness_version: str | None
    verification_commands: tuple[tuple[str, tuple[str, ...]], ...]
    sandbox: str
    auto_merge: bool
    push: bool
    remote: str | None
    max_issues: int
    max_attempts_per_issue: int
    attempt_timeout_seconds: float

    def describe(self) -> str:
        lines = ["ralf-loop run plan"]
        lines.append(f"  target branch: {self.target_branch}")
        lines.append(f"  harness: {self.harness_profile} ({' '.join(self.harness_command)})")
        lines.append(
            f"  harness executable: {self.harness_executable} "
            f"({self.harness_version or 'version unknown'})"
        )
        lines.append(f"  sandbox: {self.sandbox}")
        lines.append(f"  auto-merge: {'on' if self.auto_merge else 'off'}")
        lines.append(f"  push: {'on' if self.push else 'off'} ({self.remote or 'no remote'})")
        lines.append(
            f"  limits: {self.max_issues} issue(s), {self.max_attempts_per_issue} attempt(s)"
        )
        if self.verification_commands:
            for name, arguments in self.verification_commands:
                lines.append(f"  verify {name}: {' '.join(arguments)}")
        else:
            lines.append("  verify: no verification commands configured")
        lines.append("  issues:")
        for issue in self.issues:
            marker = "->" if issue.number == self.selected else "  "
            branch = f" [{issue.branch}]" if issue.branch else ""
            lines.append(f"  {marker} {issue.number:04d} {issue.status.value}{branch}")
        return "\n".join(lines)


class RepositoryLock:
    """One Ralf process per repository, enforced with a Linux flock."""

    def __init__(self, repository: GitRepository) -> None:
        self.path = repository.git_directory() / "ralf.lock"
        self._handle: int | None = None

    def __enter__(self) -> RepositoryLock:
        handle = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            os.close(handle)
            raise PreflightError(
                ["another Ralf process holds the repository lock for this project"]
            ) from error
        self._handle = handle
        return self

    def __exit__(
        self,
        _type: type[BaseException] | None,
        _value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        if self._handle is None:
            return
        handle = self._handle
        fcntl.flock(handle, fcntl.LOCK_UN)
        os.close(handle)
        self._handle = None
        self.path.unlink(missing_ok=True)


def load_settings(config_path: Path) -> Settings:
    from ralf.config import load_config

    diagnostics = validate_config(config_path)
    if diagnostics:
        raise PreflightError([f"{item.path}: {item.message}" for item in diagnostics])
    return Settings.from_config(load_config(config_path))


def build_plan(
    settings: Settings,
    repository: GitRepository,
    *,
    no_sandbox: bool,
    remote: str | None,
    fetch: bool = True,
) -> RunPlan:
    """Validate the whole repository and produce one exact plan without mutation."""

    messages: list[str] = []
    issue_directory = Path(settings.issue_directory)
    issue_diagnostics = validate_issues(issue_directory, issue_directory)
    messages.extend(f"{item.path}: {item.message}" for item in issue_diagnostics)

    current = repository.current_branch()
    if not current:
        messages.append("the repository is in a detached HEAD state")
    elif current != settings.target_branch:
        messages.append(
            f'target branch "{settings.target_branch}" must be checked out, not "{current}"'
        )

    if repository.is_clean() is False:
        messages.append("the target working tree must be clean before a run")

    selected_remote = remote or (settings.remote if settings.remote else None)
    if selected_remote is not None and not repository.has_remote(selected_remote):
        messages.append(f'configured remote "{selected_remote}" does not exist')
        selected_remote = None
    elif selected_remote is None and repository.has_remote("origin"):
        selected_remote = "origin"

    if selected_remote is not None:
        if fetch:
            try:
                repository.fetch(selected_remote)
            except GitError as error:
                messages.append(f"could not fetch remote: {error}")
        upstream = repository.upstream(selected_remote)
        if repository.has_upstream(selected_remote):
            target = settings.target_branch
            if not repository.is_ancestor(target, upstream) and not repository.is_ancestor(
                upstream, target
            ):
                messages.append(
                    f'target branch "{target}" has diverged from '
                    f"{selected_remote}; refusing to rewrite it"
                )

    if not no_sandbox:
        try:
            require_bubblewrap()
        except SandboxUnavailable as error:
            messages.append(str(error))

    if messages:
        raise PreflightError(messages)

    planned: list[PlannedIssue] = []
    selected: int | None = None
    for path in issue_files(issue_directory):
        issue = load_issue(path)
        planned.append(PlannedIssue(issue.number, issue.status, issue.branch))
        if selected is None and issue.status == IssueStatus.PENDING:
            selected = issue_number(path)

    harness = resolve_harness(settings.harness)
    probe = probe_executable(harness)

    return RunPlan(
        target_branch=settings.target_branch,
        issues=tuple(planned),
        selected=selected,
        harness_profile=harness.profile,
        harness_command=harness.command,
        harness_executable=probe.executable,
        harness_version=probe.version,
        verification_commands=settings.verification_commands,
        sandbox="disabled_by_override" if no_sandbox else "bubblewrap",
        auto_merge=settings.auto_merge,
        push=settings.push,
        remote=selected_remote,
        max_issues=settings.max_issues,
        max_attempts_per_issue=settings.max_attempts_per_issue,
        attempt_timeout_seconds=settings.attempt_timeout_seconds,
    )
