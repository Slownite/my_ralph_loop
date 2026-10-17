"""Load and validate Ralf's file-backed issue queue."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ralf.diagnostics import Diagnostic
from ralf.git import is_valid_branch_name

ISSUE_FILENAME = re.compile(r"^(?P<id>[0-9]+)-(?P<slug>[a-z0-9]+(?:-[a-z0-9]+)*)\.md$")
FRONTMATTER_LINE = re.compile(r"^(?P<key>[a-z][a-z0-9_]*): (?P<value>[^\n]+)$")
ISSUE_KEYS = {"status", "branch", "attempts"}


class IssueStatus(StrEnum):
    """The closed workflow states an Issue may occupy."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    READY = "ready"
    DONE = "done"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class Issue:
    """A validated file-backed issue."""

    number: int
    status: IssueStatus
    branch: str | None
    attempts: int
    body: str


@dataclass(frozen=True, slots=True)
class _IssueDocument:
    number: int
    status: str
    branch: str | None
    attempts: int
    body: str


class IssueFormatError(ValueError):
    """An issue cannot be represented by the narrow frontmatter format."""


def _load_issue_document(path: Path) -> _IssueDocument:

    filename = ISSUE_FILENAME.fullmatch(path.name)
    if filename is None:
        raise IssueFormatError("filename must be <numeric-id>-<slug>.md")

    content = path.read_text()
    lines = content.splitlines()
    if not lines or lines[0] != "---":
        raise IssueFormatError("frontmatter must begin with a --- delimiter")
    try:
        closing_index = lines.index("---", 1)
    except ValueError as error:
        raise IssueFormatError("frontmatter must end with a --- delimiter") from error

    frontmatter: dict[str, str] = {}
    for line in lines[1:closing_index]:
        match = FRONTMATTER_LINE.fullmatch(line)
        if match is None:
            raise IssueFormatError("frontmatter entries must use key: scalar")
        key = match.group("key")
        if key in frontmatter:
            raise IssueFormatError(f'duplicate frontmatter key "{key}"')
        frontmatter[key] = match.group("value")

    unknown_keys = sorted(frontmatter.keys() - ISSUE_KEYS)
    if unknown_keys:
        raise IssueFormatError(f'unknown frontmatter key "{unknown_keys[0]}"')
    if "status" not in frontmatter:
        raise IssueFormatError('required frontmatter key "status" is missing')

    attempts_text = frontmatter.get("attempts", "0")
    try:
        attempts = int(attempts_text)
    except ValueError as error:
        raise IssueFormatError("attempts must be a non-negative integer") from error
    if attempts < 0:
        raise IssueFormatError("attempts must be a non-negative integer")

    body = "\n".join(lines[closing_index + 1 :]).strip()
    return _IssueDocument(
        number=int(filename.group("id")),
        status=frontmatter["status"],
        branch=frontmatter.get("branch"),
        attempts=attempts,
        body=body,
    )


def load_issue(path: Path) -> Issue:
    """Load one fully validated issue."""

    document = _load_issue_document(path)
    try:
        status = IssueStatus(document.status)
    except ValueError as error:
        raise IssueFormatError(f'status "{document.status}" is not valid') from error
    if document.branch is not None and not is_valid_branch_name(document.branch):
        raise IssueFormatError(f'branch "{document.branch}" is not a valid Git branch name')
    return Issue(
        number=document.number,
        status=status,
        branch=document.branch,
        attempts=document.attempts,
        body=document.body,
    )


def issue_files(directory: Path) -> list[Path]:
    """Return issue files ordered by their numeric identity."""

    numbered: list[tuple[int, Path]] = []
    for path in directory.glob("*.md"):
        filename = ISSUE_FILENAME.fullmatch(path.name)
        if filename is not None:
            numbered.append((int(filename.group("id")), path))
    return [path for _, path in sorted(numbered)]


def issue_number(path: Path) -> int:
    filename = ISSUE_FILENAME.fullmatch(path.name)
    if filename is None:
        raise IssueFormatError("filename must be <numeric-id>-<slug>.md")
    return int(filename.group("id"))


def issue_slug(path: Path) -> str:
    filename = ISSUE_FILENAME.fullmatch(path.name)
    if filename is None:
        raise IssueFormatError("filename must be <numeric-id>-<slug>.md")
    return filename.group("slug")


def pending_issues(directory: Path) -> list[Issue]:
    """Return pending issues in numeric order for deterministic processing."""

    pending: list[Issue] = []
    for path in issue_files(directory):
        issue = load_issue(path)
        if issue.status == IssueStatus.PENDING:
            pending.append(issue)
    return pending


def find_issue(directory: Path, number: int) -> Issue | None:
    for path in issue_files(directory):
        if issue_number(path) == number:
            return load_issue(path)
    return None


def write_issue_status(
    path: Path,
    *,
    status: IssueStatus,
    branch: str | None,
    attempts: int,
) -> None:
    """Rewrite only the portable workflow metadata, preserving the issue body."""

    issue = load_issue(path)
    lines = ["---", f"status: {status.value}"]
    if branch is not None:
        lines.append(f"branch: {branch}")
    lines.append(f"attempts: {attempts}")
    lines.append("---")
    lines.append("")
    path.write_text("\n".join([*lines, issue.body, ""]))


def validate_issues(directory: Path, display_directory: Path) -> list[Diagnostic]:
    """Validate every Markdown issue in a directory before work begins."""

    if not directory.is_dir():
        return [
            Diagnostic(
                code="issue_directory_missing",
                message="configured issue directory does not exist",
                path=display_directory.as_posix(),
            )
        ]

    diagnostics: list[Diagnostic] = []
    seen_numbers: dict[int, Path] = {}
    for path in sorted(directory.glob("*.md")):
        display_path = display_directory / path.name
        filename = ISSUE_FILENAME.fullmatch(path.name)
        if filename is None:
            diagnostics.append(
                Diagnostic(
                    code="issue_invalid_filename",
                    message="filename must be <numeric-id>-<slug>.md",
                    path=display_path.as_posix(),
                )
            )
        else:
            number = int(filename.group("id"))
            previous = seen_numbers.get(number)
            if previous is None:
                seen_numbers[number] = display_path
            else:
                diagnostics.append(
                    Diagnostic(
                        code="issue_duplicate_id",
                        message=f"issue ID {number} is also used by {path.name}",
                        path=previous.as_posix(),
                    )
                )

        try:
            issue = _load_issue_document(path)
        except IssueFormatError as error:
            if filename is not None:
                diagnostics.append(
                    Diagnostic(
                        code="issue_invalid_frontmatter",
                        message=str(error),
                        path=display_path.as_posix(),
                    )
                )
            continue

        try:
            IssueStatus(issue.status)
        except ValueError:
            diagnostics.append(
                Diagnostic(
                    code="issue_invalid_status",
                    message=f'status "{issue.status}" is not valid',
                    path=f"{display_path.as_posix()}:status",
                )
            )
        if issue.branch is not None and not is_valid_branch_name(issue.branch):
            diagnostics.append(
                Diagnostic(
                    code="issue_invalid_branch",
                    message=f'branch "{issue.branch}" is not a valid Git branch name',
                    path=f"{display_path.as_posix()}:branch",
                )
            )

    return sorted(diagnostics, key=lambda diagnostic: (diagnostic.path, diagnostic.code))
