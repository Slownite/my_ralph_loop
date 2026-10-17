"""Independent safety guards.

Guards reject ineligible changes regardless of verification results. They run
before a feature commit and again after verification, because verification
commands may themselves mutate the tree.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from ralf.git import Change

TEST_FILENAME = re.compile(r"^(test[_-].*|.*[_-]test|test.*)\.(py|xsh|sh|js|ts|tsx|rs|go|rb)$")
TEST_DIRECTORIES = {"tests", "test"}


@dataclass(frozen=True, slots=True)
class Violation:
    """A change that Ralf refuses to commit."""

    code: str
    message: str
    path: str


def is_test_path(path: str) -> bool:
    """Return whether a repository-relative path is an existing-style test file."""

    parts = path.split("/")
    if any(part in TEST_DIRECTORIES for part in parts[:-1]):
        return True
    return TEST_FILENAME.match(parts[-1]) is not None


def _is_protected(path: str, protected_roots: Iterable[str]) -> bool:
    return any(path == root or path.startswith(root.rstrip("/") + "/") for root in protected_roots)


def eligible_changes(changes: Iterable[Change], *, protected_roots: Iterable[str]) -> list[Change]:
    """Return the changes that may become part of the feature commit."""

    return [change for change in changes if not _is_protected(change.path, protected_roots)]


def protected_path_violations(
    changes: Iterable[Change], *, protected_roots: Iterable[str]
) -> list[Violation]:
    violations: list[Violation] = []
    for change in changes:
        if _is_protected(change.path, protected_roots):
            violations.append(
                Violation(
                    code="guard_protected_path",
                    message="changes to Ralf-owned paths are not allowed",
                    path=change.path,
                )
            )
    return violations


def test_deletion_violations(
    changes: Iterable[Change], *, allowed_deletions: Iterable[str]
) -> list[Violation]:
    allowed = set(allowed_deletions)
    violations: list[Violation] = []
    for change in changes:
        deleted = (change.status == "D" and is_test_path(change.path)) or (
            change.previous_path is not None
            and is_test_path(change.previous_path)
            and not is_test_path(change.path)
        )
        path = change.previous_path or change.path
        if deleted and path not in allowed:
            violations.append(
                Violation(
                    code="guard_test_deletion",
                    message="deletion of a pre-existing test file is not allowed",
                    path=path,
                )
            )
    return violations
