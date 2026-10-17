from pathlib import Path

import pytest

from ralf.issues import IssueFormatError, IssueStatus, load_issue


def test_public_issue_loader_returns_a_domain_status(tmp_path: Path) -> None:
    issue_path = tmp_path / "001-example.md"
    issue_path.write_text("---\nstatus: pending\nattempts: 0\n---\n\n# Example\n")

    issue = load_issue(issue_path)

    assert issue.status is IssueStatus.PENDING


def test_public_issue_loader_rejects_an_invalid_status(tmp_path: Path) -> None:
    issue_path = tmp_path / "001-example.md"
    issue_path.write_text("---\nstatus: wandering\n---\n\n# Example\n")

    with pytest.raises(IssueFormatError, match='status "wandering" is not valid'):
        load_issue(issue_path)
