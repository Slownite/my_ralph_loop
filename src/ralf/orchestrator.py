"""The Ralf workflow engine.

Ralf—not the Harness—owns Issue state, Git mutations, worktrees, verification,
merges, and optional pushes. Infrastructure failures preserve work and stop;
implementation failures consume bounded attempts and become ``blocked``.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path

from ralf.git import Change, GitError, GitRepository
from ralf.guards import (
    Violation,
    eligible_changes,
    protected_path_violations,
    test_deletion_violations,
)
from ralf.harness import HarnessSpec, resolve_harness
from ralf.issues import (
    Issue,
    IssueStatus,
    find_issue,
    issue_files,
    issue_number,
    issue_slug,
    load_issue,
    write_issue_status,
)
from ralf.plan import RepositoryLock, RunPlan, build_plan, load_settings
from ralf.process import CommandHarness, ProcessOutcome, ProcessResult
from ralf.resources import issue_prompt
from ralf.sandbox import Mount, SandboxPolicy
from ralf.settings import Settings
from ralf.telemetry import Telemetry, new_run_id, repository_state_directory

MAX_DIAGNOSTIC_BYTES = 32 * 1024


class WorkflowError(RuntimeError):
    """The workflow cannot proceed under the current repository state."""


class InfrastructureFailure(WorkflowError):
    """Process or Git infrastructure failed; work is preserved."""


class Interrupted(WorkflowError):
    """The user stopped Ralf; work is preserved."""


class BlockedError(WorkflowError):
    """Work is preserved but requires a deliberate retry or human intervention."""


@dataclass(frozen=True, slots=True)
class Verification:
    failures: tuple[str, ...]
    diagnostics: str

    @property
    def passed(self) -> bool:
        return not self.failures


class Workflow:
    """One repository-bound Ralf workflow."""

    def __init__(
        self,
        repository_root: Path,
        config_path: Path,
        *,
        no_sandbox: bool = False,
        remote: str | None = None,
        auto_merge: bool | None = None,
        push: bool | None = None,
        max_issues: int | None = None,
    ) -> None:
        self.root = repository_root.resolve()
        self.config_path = config_path
        self.repository = GitRepository(self.root)
        self.settings: Settings = load_settings(config_path)
        self.harness: HarnessSpec = resolve_harness(self.settings.harness)
        self.no_sandbox = no_sandbox
        self.remote = remote
        self.auto_merge = self.settings.auto_merge if auto_merge is None else auto_merge
        self.push = self.settings.push if push is None else push
        self.max_issues = self.settings.max_issues if max_issues is None else max_issues
        state = repository_state_directory(self.root)
        self.telemetry = Telemetry(
            state, max_runs=self.settings.max_runs, max_age_days=self.settings.max_age_days
        )
        self.worktrees = state / "worktrees"

    # -- helpers ----------------------------------------------------------

    @property
    def issue_directory(self) -> Path:
        return Path(self.settings.issue_directory)

    def _issue_path(self, number: int) -> Path:
        for path in issue_files(self.issue_directory):
            if issue_number(path) == number:
                return path
        raise WorkflowError(f"issue {number} does not exist in the issue queue")

    def _branch_name(self, path: Path) -> str:
        return f"ralf/issue-{issue_number(path)}-{issue_slug(path)}"

    def _worktree_path(self, number: int) -> Path:
        return self.worktrees / f"issue-{number}"

    def _protected_roots(self) -> tuple[str, ...]:
        return (self.settings.issue_directory, "ralf.toml")

    def _agent_policy(self) -> SandboxPolicy:
        mounts = [Mount(path) for path in self.harness.read_only_mounts]
        mounts += [Mount(path, writable=True) for path in self.harness.writable_state]
        mounts += list(self.settings.extra_mounts)
        return SandboxPolicy(network=True, mounts=tuple(mounts))

    def _verification_policy(self) -> SandboxPolicy:
        return SandboxPolicy(
            network=self.settings.verification_network, mounts=self.settings.extra_mounts
        )

    def _allowlist(self) -> tuple[str, ...]:
        names = {*self.harness.environment_allowlist, *self.settings.environment_allowlist, "PATH"}
        return tuple(sorted(names))

    def _guard(self, changes: list[Change]) -> list[Violation]:
        violations = protected_path_violations(changes, protected_roots=self._protected_roots())
        violations += test_deletion_violations(
            changes, allowed_deletions=self.settings.allowed_test_deletions
        )
        return violations

    def _commit_status(
        self,
        path: Path,
        status: IssueStatus,
        *,
        branch: str | None,
        attempts: int,
        message: str,
    ) -> None:
        write_issue_status(path, status=status, branch=branch, attempts=attempts)
        self.repository.stage_all()
        if self.repository.has_staged_changes():
            self.repository.commit(message)

    def _build_prompt(self, number: int, issue: Issue, attempt: int, diagnostics: str) -> str:
        lines = [
            issue_prompt().strip(),
            "",
            f"# Issue {number:04d}",
            "",
            issue.body,
            "",
            "## Verification commands",
            "",
        ]
        if self.settings.verification_commands:
            for name, arguments in self.settings.verification_commands:
                lines.append(f"- {name}: {' '.join(arguments)}")
        else:
            lines.append("- none configured")
        if diagnostics:
            lines += ["", "## Previous attempt diagnostics", "", diagnostics]
        return "\n".join(lines) + "\n"

    # -- verification and attempts ---------------------------------------

    def _run_verification(self, worktree: Path, run_id: str, number: int) -> Verification:
        runner = CommandHarness(
            command=(),
            environment_allowlist=self._allowlist(),
            timeout_seconds=self.settings.attempt_timeout_seconds,
            policy=self._verification_policy(),
        )
        failures: list[str] = []
        collected: list[str] = []
        for name, arguments in self.settings.verification_commands:
            result = runner.run_arguments(arguments, worktree=worktree, no_sandbox=self.no_sandbox)
            self.telemetry.record(
                "verification", run=run_id, issue=number, name=name, **result.to_record()
            )
            if not result.ok:
                failures.append(name)
                collected.append(f"## {name}\n{result.stdout}\n{result.stderr}")
        return Verification(tuple(failures), _tail("\n".join(collected)))

    def _run_attempts(
        self,
        path: Path,
        number: int,
        branch: str,
        worktree: Path,
        base: str,
        starting_attempts: int,
        run_id: str,
    ) -> IssueStatus:
        worktree_repository = GitRepository(worktree)
        runner = CommandHarness(
            command=self.harness.command,
            environment_allowlist=self._allowlist(),
            timeout_seconds=self.settings.attempt_timeout_seconds,
            policy=self._agent_policy(),
        )
        diagnostics = ""
        consumed = 0
        while consumed < self.settings.max_attempts_per_issue:
            issue = load_issue(path)
            cumulative = starting_attempts + consumed
            self.telemetry.record(
                "attempt_start",
                run=run_id,
                issue=number,
                attempt=cumulative + 1,
                profile=self.harness.profile,
            )
            result = runner.run(
                self._build_prompt(number, issue, cumulative + 1, diagnostics),
                worktree=worktree,
                no_sandbox=self.no_sandbox,
            )
            self._record_process(run_id, number, cumulative + 1, result)
            if result.interrupted:
                self.telemetry.record("interruption", run=run_id, issue=number)
                raise Interrupted(f"issue {number} was interrupted")
            if result.outcome is not ProcessOutcome.SUCCESS:
                self.telemetry.record(
                    "infrastructure_failure",
                    run=run_id,
                    issue=number,
                    outcome=result.outcome.value,
                )
                raise InfrastructureFailure(
                    f"harness for issue {number} failed: {result.outcome.value}"
                )

            changes = worktree_repository.staged_changes(base)
            violations = self._guard(changes)
            if violations:
                consumed += 1
                diagnostics = _violation_diagnostics(violations)
                self._record_attempt_outcome(run_id, number, cumulative + 1, "guard")
                continue
            if not eligible_changes(changes, protected_roots=self._protected_roots()):
                consumed += 1
                diagnostics = "the harness produced no eligible changes"
                self._record_attempt_outcome(run_id, number, cumulative + 1, "no_diff")
                continue

            verification = self._run_verification(worktree, run_id, number)
            if not verification.passed:
                consumed += 1
                diagnostics = verification.diagnostics
                self._record_attempt_outcome(run_id, number, cumulative + 1, "verification")
                continue

            changes = worktree_repository.staged_changes(base)
            violations = self._guard(changes)
            if violations:
                consumed += 1
                diagnostics = _violation_diagnostics(violations)
                self._record_attempt_outcome(
                    run_id, number, cumulative + 1, "guard_after_verification"
                )
                continue

            try:
                commit = worktree_repository.commit(f"ralf: implement issue {number}")
            except GitError as error:
                raise InfrastructureFailure(f"could not commit issue {number}: {error}") from error
            self.telemetry.record("commit", run=run_id, issue=number, commit=commit[:12])
            self._commit_status(
                path,
                IssueStatus.READY,
                branch=branch,
                attempts=cumulative + 1,
                message=f"ralf: issue {number} ready",
            )
            self.telemetry.record("issue_ready", run=run_id, issue=number, attempts=cumulative + 1)
            return IssueStatus.READY

        self._commit_status(
            path,
            IssueStatus.BLOCKED,
            branch=branch,
            attempts=starting_attempts + consumed,
            message=f"ralf: block issue {number}",
        )
        self.telemetry.record(
            "issue_blocked", run=run_id, issue=number, attempts=starting_attempts + consumed
        )
        raise BlockedError(f"issue {number} exhausted its attempt allowance")

    def _record_process(
        self, run_id: str, number: int, attempt: int, result: ProcessResult
    ) -> None:
        self.telemetry.record(
            "harness_result", run=run_id, issue=number, attempt=attempt, **result.to_record()
        )
        self.telemetry.write_transcript(run_id, attempt, "stdout", result.stdout)
        self.telemetry.write_transcript(run_id, attempt, "stderr", result.stderr)

    def _record_attempt_outcome(self, run_id: str, number: int, attempt: int, reason: str) -> None:
        self.telemetry.record(
            "attempt_outcome", run=run_id, issue=number, attempt=attempt, reason=reason
        )

    # -- identity ---------------------------------------------------------

    def _identity_valid(self, issue: Issue, number: int) -> bool:
        if not issue.branch or not self.repository.branch_exists(issue.branch):
            return False
        worktree = self._worktree_path(number)
        if not worktree.is_dir():
            return False
        if worktree.resolve() not in {path.resolve() for path in self.repository.worktrees()}:
            return False
        try:
            return GitRepository(worktree).current_branch() == issue.branch
        except GitError:
            return False

    # -- public workflow --------------------------------------------------

    def take_to_ready(self, number: int, run_id: str) -> IssueStatus:
        path = self._issue_path(number)
        issue = load_issue(path)
        if issue.status is not IssueStatus.PENDING:
            raise WorkflowError(f"issue {number} is not pending")
        branch = self._branch_name(path)
        self._commit_status(
            path,
            IssueStatus.IN_PROGRESS,
            branch=branch,
            attempts=issue.attempts,
            message=f"ralf: start issue {number}",
        )
        base = self.repository.head()
        if self.repository.branch_exists(branch):
            raise WorkflowError(f'branch "{branch}" already exists for issue {number}')
        self.repository.create_branch(branch, base)
        worktree = self._worktree_path(number)
        worktree.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.repository.worktree_add(worktree, branch)
        except GitError as error:
            raise InfrastructureFailure(
                f"could not create worktree for issue {number}: {error}"
            ) from error
        return self._run_attempts(path, number, branch, worktree, base, issue.attempts, run_id)

    def resume(self, number: int, run_id: str) -> IssueStatus:
        """Resume an in-progress or blocked issue with a fresh per-run allowance."""

        path = self._issue_path(number)
        issue = load_issue(path)
        if issue.status not in (IssueStatus.IN_PROGRESS, IssueStatus.BLOCKED):
            raise WorkflowError(f"issue {number} is not resumable")
        if not self._identity_valid(issue, number):
            self._commit_status(
                path,
                IssueStatus.BLOCKED,
                branch=issue.branch,
                attempts=issue.attempts,
                message=f"ralf: block issue {number}",
            )
            raise WorkflowError(f"issue {number} preserved state is ambiguous; refusing to resume")
        assert issue.branch is not None
        self._commit_status(
            path,
            IssueStatus.IN_PROGRESS,
            branch=issue.branch,
            attempts=issue.attempts,
            message=f"ralf: start issue {number}",
        )
        base = self.repository.merge_base(self.settings.target_branch, issue.branch)
        worktree = self._worktree_path(number)
        return self._run_attempts(
            path, number, issue.branch, worktree, base, issue.attempts, run_id
        )

    def finalize(self, number: int, run_id: str) -> None:
        path = self._issue_path(number)
        issue = load_issue(path)
        if issue.status is not IssueStatus.READY:
            raise WorkflowError(f"issue {number} is not ready")
        if not self._identity_valid(issue, number):
            raise WorkflowError(
                f"issue {number} preserved state is ambiguous; refusing to finalize"
            )
        assert issue.branch is not None
        branch = issue.branch
        worktree = self._worktree_path(number)
        self._synchronize_target(run_id)

        worktree_repository = GitRepository(worktree)
        base = self.repository.merge_base(self.settings.target_branch, branch)
        changes = worktree_repository.staged_changes(base)
        violations = self._guard(changes)
        verification = self._run_verification(worktree, run_id, number)
        if violations or not verification.passed:
            self._commit_status(
                path,
                IssueStatus.BLOCKED,
                branch=branch,
                attempts=issue.attempts,
                message=f"ralf: block issue {number}",
            )
            raise BlockedError(f"issue {number} no longer passes the gate")

        try:
            merge = self.repository.merge_no_ff(branch, f"ralf: merge issue {number}")
        except GitError as error:
            self.repository.abort_merge()
            self._commit_status(
                path,
                IssueStatus.BLOCKED,
                branch=branch,
                attempts=issue.attempts,
                message=f"ralf: block issue {number}",
            )
            raise BlockedError(f"issue {number} could not be merged: {error}") from error
        self.telemetry.record("merge", run=run_id, issue=number, commit=merge[:12])
        self._commit_status(
            path,
            IssueStatus.DONE,
            branch=None,
            attempts=issue.attempts,
            message=f"ralf: done issue {number}",
        )
        with contextlib.suppress(GitError):
            self.repository.worktree_remove(worktree)
        self.telemetry.record("issue_done", run=run_id, issue=number)
        self._publish(run_id)

    def _publish(self, run_id: str) -> None:
        if not self.push:
            return
        remote = self.remote or ("origin" if self.repository.has_remote("origin") else None)
        if remote is None:
            return
        try:
            self.repository.push(remote, self.settings.target_branch)
        except GitError as error:
            self.telemetry.record("push_failure", run=run_id, remote=remote)
            raise InfrastructureFailure(f"could not push to {remote}: {error}") from error
        self.telemetry.record("push", run=run_id, remote=remote)

    def _synchronize_target(self, run_id: str) -> None:
        remote = self.remote or ("origin" if self.repository.has_remote("origin") else None)
        if remote is None:
            return
        upstream = self.repository.upstream(remote)
        if not self.repository.has_upstream(remote):
            return
        target = self.settings.target_branch
        if self.repository.is_ancestor(target, upstream):
            self.repository.fast_forward(upstream)
            self.telemetry.record("synchronize", run=run_id, remote=remote)
        elif not self.repository.is_ancestor(upstream, target):
            raise InfrastructureFailure(f'target branch "{target}" has diverged from {remote}')

    # -- run --------------------------------------------------------------

    def plan(self, *, fetch: bool = False) -> RunPlan:
        return build_plan(
            self.settings,
            self.repository,
            no_sandbox=self.no_sandbox,
            remote=self.remote,
            fetch=fetch,
        )

    def run(self) -> int:
        self.telemetry.cleanup()
        run_id = new_run_id()
        with RepositoryLock(self.repository):
            plan = build_plan(
                self.settings,
                self.repository,
                no_sandbox=self.no_sandbox,
                remote=self.remote,
                fetch=True,
            )
            self.telemetry.record(
                "run_start",
                run=run_id,
                target=plan.target_branch,
                harness=plan.harness_profile,
                sandbox=plan.sandbox,
            )
            self._synchronize_target(run_id)

            processed = 0
            resumed = self._recover_in_progress(run_id)
            if resumed is not None:
                self._complete_issue(resumed, run_id)
                processed += 1

            while processed < self.max_issues:
                number = self._next_pending()
                if number is None:
                    break
                self._take(number, run_id)
                processed += 1

            self.telemetry.record("run_end", run=run_id, processed=processed)
        return 0

    def _take(self, number: int, run_id: str) -> None:
        status = self.take_to_ready(number, run_id)
        if status is IssueStatus.READY and self.auto_merge:
            self.finalize(number, run_id)

    def _complete_issue(self, number: int, run_id: str) -> None:
        try:
            status = self.resume(number, run_id)
        except BlockedError:
            return
        if status is IssueStatus.READY and self.auto_merge:
            try:
                self.finalize(number, run_id)
            except BlockedError:
                return

    def retry_issue(self, number: int) -> int:
        run_id = new_run_id()
        with RepositoryLock(self.repository):
            status = self.resume(number, run_id)
            if status is IssueStatus.READY and self.auto_merge:
                self.finalize(number, run_id)
        return 0

    def finalize_issue(self, number: int) -> int:
        run_id = new_run_id()
        with RepositoryLock(self.repository):
            self.finalize(number, run_id)
        return 0

    def _next_pending(self) -> int | None:
        for path in issue_files(self.issue_directory):
            if load_issue(path).status is IssueStatus.PENDING:
                return issue_number(path)
        return None

    def _recover_in_progress(self, run_id: str) -> int | None:
        for path in issue_files(self.issue_directory):
            issue = load_issue(path)
            if issue.status is not IssueStatus.IN_PROGRESS:
                continue
            number = issue_number(path)
            if self._identity_valid(issue, number):
                self.telemetry.record("resume", run=run_id, issue=number)
                return number
            self._commit_status(
                path,
                IssueStatus.BLOCKED,
                branch=issue.branch,
                attempts=issue.attempts,
                message=f"ralf: block issue {number}",
            )
            self.telemetry.record("resume_rejected", run=run_id, issue=number)
        return None

    # -- status -----------------------------------------------------------

    def status(self) -> dict[str, object]:
        issues: list[dict[str, object]] = []
        for path in issue_files(self.issue_directory):
            issue = load_issue(path)
            issues.append(
                {
                    "number": issue_number(path),
                    "status": issue.status.value,
                    "branch": issue.branch,
                    "attempts": issue.attempts,
                    "worktree_preserved": self._worktree_path(issue_number(path)).is_dir(),
                }
            )
        return {
            "target_branch": self.settings.target_branch,
            "issues": issues,
            "worktrees": [
                {"issue": issue.number, "path": self._worktree_path(issue.number).as_posix()}
                for issue in (load_issue(path) for path in issue_files(self.issue_directory))
                if self._worktree_path(issue.number).is_dir()
            ],
        }


def find_issue_number(directory: Path, number: int) -> Issue | None:
    return find_issue(directory, number)


def _violation_diagnostics(violations: list[Violation]) -> str:
    return "\n".join(f"- {violation.code}: {violation.path}" for violation in violations)


def _tail(text: str, limit: int = MAX_DIAGNOSTIC_BYTES) -> str:
    return text[-limit:]
