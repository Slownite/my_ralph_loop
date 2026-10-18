"""GitHub-backed Issue intake using Matt Pocock's triage-role vocabulary."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from ralf.issues import (
    IssueStatus,
    issue_files,
    issue_number,
    load_issue,
    write_issue_status,
)

CANONICAL_READY_FOR_AGENT = "ready-for-agent"
CANONICAL_READY_FOR_HUMAN = "ready-for-human"
CANONICAL_STATE_ROLES = (
    "needs-triage",
    "needs-info",
    CANONICAL_READY_FOR_AGENT,
    CANONICAL_READY_FOR_HUMAN,
    "wontfix",
)
CATEGORY_ROLES = frozenset({"bug", "enhancement"})


class GitHubIssueError(RuntimeError):
    """GitHub Issue discovery or a state transition failed."""


@dataclass(frozen=True, slots=True)
class TriageLabels:
    """Tracker labels corresponding to the Matt Pocock triage roles Ralf uses."""

    needs_triage: str = "needs-triage"
    needs_info: str = "needs-info"
    ready_for_agent: str = "ready-for-agent"
    ready_for_human: str = "ready-for-human"
    wontfix: str = "wontfix"

    @property
    def state_roles(self) -> frozenset[str]:
        return frozenset(
            {
                self.needs_triage,
                self.needs_info,
                self.ready_for_agent,
                self.ready_for_human,
                self.wontfix,
            }
        )


class GitHubIssueClient(Protocol):
    def available_labels(self) -> set[str]: ...

    def ready_issues(self, label: str) -> list[dict[str, object]]: ...

    def transition(
        self,
        number: int,
        previous: IssueStatus,
        status: IssueStatus,
        labels: TriageLabels,
    ) -> None: ...


class GhClient:
    """Narrow ``gh`` process boundary used by the GitHub Issue queue."""

    def __init__(self, repository_root: Path) -> None:
        self.root = repository_root

    def _run(self, *arguments: str) -> str:
        try:
            result = subprocess.run(
                ["gh", *arguments],
                cwd=self.root,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise GitHubIssueError(f"could not run gh: {error}") from error
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "no output"
            raise GitHubIssueError(f"gh {' '.join(arguments)} failed: {detail}")
        return result.stdout

    def available_labels(self) -> set[str]:
        values = json.loads(self._run("label", "list", "--limit", "1000", "--json", "name"))
        return {
            str(entry["name"])
            for entry in cast(list[dict[str, object]], values)
            if isinstance(entry.get("name"), str)
        }

    def ready_issues(self, label: str) -> list[dict[str, object]]:
        values = json.loads(
            self._run(
                "issue",
                "list",
                "--state",
                "open",
                "--label",
                label,
                "--limit",
                "1000",
                "--json",
                "number,title,body,assignees,labels",
            )
        )
        return cast(list[dict[str, object]], values)

    def transition(
        self,
        number: int,
        previous: IssueStatus,
        status: IssueStatus,
        labels: TriageLabels,
    ) -> None:
        reference = str(number)
        if status is IssueStatus.IN_PROGRESS:
            arguments = ["issue", "edit", reference, "--add-assignee", "@me"]
            if previous is IssueStatus.BLOCKED:
                arguments += [
                    "--remove-label",
                    labels.ready_for_human,
                    "--add-label",
                    labels.ready_for_agent,
                ]
            self._run(*arguments)
        elif status is IssueStatus.BLOCKED:
            self._run(
                "issue",
                "edit",
                reference,
                "--remove-label",
                labels.ready_for_agent,
                "--add-label",
                labels.ready_for_human,
            )
        elif status is IssueStatus.DONE:
            self._run("issue", "edit", reference, "--remove-label", labels.ready_for_agent)
            self._run("issue", "close", reference, "--reason", "completed")


def _table_cell(value: str) -> str:
    return value.strip().strip("`").strip()


def load_triage_labels(repository_root: Path) -> TriageLabels:
    """Load tracker-specific label names, falling back to the canonical roles."""

    mapping = {role: role for role in CANONICAL_STATE_ROLES}
    path = repository_root / "docs" / "agents" / "triage-labels.md"
    if path.is_file():
        for line in path.read_text().splitlines():
            if not line.lstrip().startswith("|"):
                continue
            cells = [_table_cell(cell) for cell in line.strip().strip("|").split("|")]
            if len(cells) < 2:
                continue
            canonical, tracker = cells[:2]
            if canonical in mapping and tracker and set(tracker) != {"-"}:
                mapping[canonical] = tracker
    return TriageLabels(
        needs_triage=mapping["needs-triage"],
        needs_info=mapping["needs-info"],
        ready_for_agent=mapping[CANONICAL_READY_FOR_AGENT],
        ready_for_human=mapping[CANONICAL_READY_FOR_HUMAN],
        wontfix=mapping["wontfix"],
    )


def _slug(title: str) -> str:
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")
    return value or "issue"


def _assignees(issue: dict[str, object]) -> list[object]:
    value = issue.get("assignees")
    return cast(list[object], value) if isinstance(value, list) else []


def _labels(issue: dict[str, object]) -> set[str]:
    value = issue.get("labels")
    if not isinstance(value, list):
        return set()
    return {
        str(label["name"])
        for raw in cast(list[object], value)
        if isinstance(raw, dict)
        for label in [cast(dict[str, object], raw)]
        if isinstance(label.get("name"), str)
    }


class GitHubIssueQueue:
    """Mirror actionable GitHub Issues into private local workflow state."""

    def __init__(
        self,
        repository_root: Path,
        directory: Path,
        *,
        client: GitHubIssueClient | None = None,
    ) -> None:
        self.root = repository_root.resolve()
        self.directory = directory
        self.client = client or GhClient(self.root)
        self.labels = load_triage_labels(self.root)

    def _path(self, number: int) -> Path | None:
        return next(
            (path for path in issue_files(self.directory) if issue_number(path) == number),
            None,
        )

    def sync(self) -> None:
        """Refresh pending mirrors while preserving active workflow state."""

        available = self.client.available_labels()
        required = (
            (CANONICAL_READY_FOR_AGENT, self.labels.ready_for_agent),
            (CANONICAL_READY_FOR_HUMAN, self.labels.ready_for_human),
        )
        for role, label in required:
            if label not in available:
                raise GitHubIssueError(f'GitHub label "{label}" for {role} does not exist')

        self.directory.mkdir(parents=True, exist_ok=True)
        remote: list[dict[str, object]] = []
        for issue in self.client.ready_issues(self.labels.ready_for_agent):
            if _assignees(issue):
                continue
            number = issue.get("number")
            names = _labels(issue)
            states = names & self.labels.state_roles
            categories = names & CATEGORY_ROLES
            if states != {self.labels.ready_for_agent}:
                raise GitHubIssueError(
                    f"GitHub issue #{number} has conflicting triage state labels: "
                    f"{', '.join(sorted(states)) or 'none'}"
                )
            if len(categories) != 1:
                raise GitHubIssueError(
                    f"GitHub issue #{number} must have exactly one category label "
                    f"(bug or enhancement)"
                )
            remote.append(issue)
        eligible_numbers: set[int] = set()
        for remote_issue in remote:
            remote_number = remote_issue.get("number")
            if isinstance(remote_number, int) and not isinstance(remote_number, bool):
                eligible_numbers.add(remote_number)

        for path in issue_files(self.directory):
            issue = load_issue(path)
            if issue.status is IssueStatus.PENDING and issue.number not in eligible_numbers:
                path.unlink()

        for raw in remote:
            number = raw.get("number")
            title = raw.get("title")
            body = raw.get("body")
            if type(number) is not int or not isinstance(title, str) or not isinstance(body, str):
                continue
            existing = self._path(number)
            if existing is not None and load_issue(existing).status is not IssueStatus.PENDING:
                continue
            path = existing or self.directory / f"{number:03d}-{_slug(title)}.md"
            path.write_text(
                f"---\nstatus: pending\nattempts: 0\n---\n\n# {title}\n\n{body.strip()}\n"
            )

    def snapshot(self, directory: Path) -> None:
        """Build a disposable current view without mutating persistent state."""

        directory.mkdir(parents=True, exist_ok=True)
        if self.directory.is_dir():
            for path in issue_files(self.directory):
                shutil.copy2(path, directory / path.name)
        GitHubIssueQueue(self.root, directory, client=self.client).sync()

    def write_status(
        self,
        path: Path,
        *,
        status: IssueStatus,
        branch: str | None,
        attempts: int,
    ) -> None:
        """Persist local recovery state and reflect meaningful roles on GitHub."""

        previous = load_issue(path).status
        write_issue_status(path, status=status, branch=branch, attempts=attempts)
        self.client.transition(issue_number(path), previous, status, self.labels)
