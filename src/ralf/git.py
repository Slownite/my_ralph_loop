"""Public Git value validation."""

from __future__ import annotations

import subprocess


def is_valid_branch_name(branch: str) -> bool:
    """Return whether Git accepts a branch name without requiring a repository."""

    result = subprocess.run(
        ["git", "check-ref-format", "--branch", branch],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0
