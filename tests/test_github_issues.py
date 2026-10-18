from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from ralf.github_issues import GitHubIssueQueue, TriageLabels, load_triage_labels
from ralf.issues import IssueStatus, load_issue, write_issue_status

from .support import create_project, write_executable


class FakeGitHub:
    def __init__(self, issues: list[dict[str, object]]) -> None:
        self.issues = issues
        self.transitions: list[tuple[int, IssueStatus, IssueStatus]] = []

    def available_labels(self) -> set[str]:
        return {
            "ready-for-agent",
            "ready-for-human",
            "agent-ready",
            "human-needed",
            "bug",
            "enhancement",
        }

    def ready_issues(self, label: str) -> list[dict[str, object]]:
        assert label in {"ready-for-agent", "agent-ready"}
        return self.issues

    def transition(
        self,
        number: int,
        previous: IssueStatus,
        status: IssueStatus,
        labels: TriageLabels,
    ) -> None:
        self.transitions.append((number, previous, status))


def test_triage_label_mapping_uses_tracker_names(tmp_path: Path) -> None:
    path = tmp_path / "docs" / "agents" / "triage-labels.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        """\
| Label in mattpocock/skills | Label in our tracker | Meaning |
| --- | --- | --- |
| `ready-for-agent` | `agent-ready` | Ready |
| `ready-for-human` | `human-needed` | Human |
"""
    )

    labels = load_triage_labels(tmp_path)

    assert labels.ready_for_agent == "agent-ready"
    assert labels.ready_for_human == "human-needed"


def test_triage_label_mapping_defaults_to_canonical_roles(tmp_path: Path) -> None:
    assert load_triage_labels(tmp_path) == TriageLabels(
        needs_triage="needs-triage",
        needs_info="needs-info",
        ready_for_agent="ready-for-agent",
        ready_for_human="ready-for-human",
        wontfix="wontfix",
    )


def test_github_queue_imports_only_unassigned_ready_issues(tmp_path: Path) -> None:
    client = FakeGitHub(
        [
            {
                "number": 7,
                "title": "Handle café receipts",
                "body": "## Acceptance criteria\n\n- [ ] Receipt is stored",
                "assignees": [],
                "labels": [{"name": "ready-for-agent"}, {"name": "enhancement"}],
            },
            {
                "number": 8,
                "title": "Already claimed",
                "body": "Do not take this",
                "assignees": [{"login": "sam"}],
                "labels": [{"name": "ready-for-agent"}, {"name": "bug"}],
            },
        ]
    )
    queue = GitHubIssueQueue(tmp_path, tmp_path / "state", client=client)

    queue.sync()

    issues = list((tmp_path / "state").glob("*.md"))
    assert [path.name for path in issues] == ["007-handle-cafe-receipts.md"]
    issue = load_issue(issues[0])
    assert issue.status is IssueStatus.PENDING
    assert "# Handle café receipts" in issue.body


def test_github_queue_preserves_active_state_and_updates_remote_role(tmp_path: Path) -> None:
    client = FakeGitHub([])
    queue = GitHubIssueQueue(tmp_path, tmp_path / "state", client=client)
    queue.directory.mkdir(parents=True)
    issue_path = queue.directory / "007-example.md"
    issue_path.write_text("---\nstatus: pending\n---\n\n# Example\n")
    write_issue_status(
        issue_path,
        status=IssueStatus.IN_PROGRESS,
        branch="ralf/issue-7-example",
        attempts=1,
    )

    queue.sync()
    queue.write_status(
        issue_path,
        status=IssueStatus.BLOCKED,
        branch="ralf/issue-7-example",
        attempts=2,
    )

    assert issue_path.exists()
    assert load_issue(issue_path).status is IssueStatus.BLOCKED
    assert client.transitions == [(7, IssueStatus.IN_PROGRESS, IssueStatus.BLOCKED)]


def test_github_queue_rejects_a_mapping_to_a_missing_label(tmp_path: Path) -> None:
    client = FakeGitHub([])
    client.available_labels = lambda: {"ready-for-agent"}  # type: ignore[method-assign]
    path = tmp_path / "docs" / "agents" / "triage-labels.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "| Label in mattpocock/skills | Label in our tracker |\n"
        "| --- | --- |\n"
        "| `ready-for-agent` | `missing-ready` |\n"
    )
    queue = GitHubIssueQueue(tmp_path, tmp_path / "state", client=client)

    try:
        queue.sync()
    except RuntimeError as error:
        assert json.loads(json.dumps(str(error))) == (
            'GitHub label "missing-ready" for ready-for-agent does not exist'
        )
    else:
        raise AssertionError("missing mapped label was accepted")


def test_github_queue_rejects_conflicting_state_roles(tmp_path: Path) -> None:
    client = FakeGitHub(
        [
            {
                "number": 9,
                "title": "Ambiguous state",
                "body": "",
                "assignees": [],
                "labels": [
                    {"name": "ready-for-agent"},
                    {"name": "needs-info"},
                    {"name": "bug"},
                ],
            }
        ]
    )

    try:
        GitHubIssueQueue(tmp_path, tmp_path / "state", client=client).sync()
    except RuntimeError as error:
        assert "conflicting triage state labels" in str(error)
    else:
        raise AssertionError("conflicting state labels were accepted")


def test_github_queue_requires_one_category_role(tmp_path: Path) -> None:
    client = FakeGitHub(
        [
            {
                "number": 10,
                "title": "Missing category",
                "body": "",
                "assignees": [],
                "labels": [{"name": "ready-for-agent"}],
            }
        ]
    )

    try:
        GitHubIssueQueue(tmp_path, tmp_path / "state", client=client).sync()
    except RuntimeError as error:
        assert "exactly one category label" in str(error)
    else:
        raise AssertionError("uncategorized issue was accepted")


def test_run_uses_github_by_default_and_leaves_local_queue_untouched(tmp_path: Path) -> None:
    project = create_project(
        tmp_path,
        harness_source=(
            "import sys\nfrom pathlib import Path\n"
            'sys.stdin.read()\nPath("feature.txt").write_text("done\\n")\n'
        ),
        auto=False,
    )
    calls = tmp_path / "gh-calls.jsonl"
    gh = write_executable(
        tmp_path / "bin" / "gh",
        f"""\
import json
import sys
from pathlib import Path

calls = Path({str(calls)!r})
with calls.open("a") as stream:
    stream.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:3] == ["label", "list"]:
    print(json.dumps([{{"name": "ready-for-agent"}}, {{"name": "ready-for-human"}}]))
elif sys.argv[1:3] == ["issue", "list"]:
    print(json.dumps([{{
        "number": 42,
        "title": "GitHub work",
        "body": "## Acceptance criteria\\n\\n- [ ] feature.txt exists",
        "assignees": [],
        "labels": [{{"name": "ready-for-agent"}}, {{"name": "enhancement"}}],
    }}]))
elif sys.argv[1:3] == ["issue", "edit"]:
    pass
else:
    raise SystemExit(2)
""",
    )
    environment = os.environ.copy()
    environment["XDG_STATE_HOME"] = str(project.state)
    environment["PATH"] = f"{gh.parent}{os.pathsep}{environment['PATH']}"

    result = subprocess.run(
        ["ralf-loop", "run", "--no-sandbox"],
        cwd=project.root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "status: pending" in project.issue_text(1)
    mirror = next((project.state / "ralf" / "repositories").rglob("042-github-work.md"))
    assert load_issue(mirror).status is IssueStatus.READY
    invocations = [json.loads(line) for line in calls.read_text().splitlines()]
    assert ["issue", "edit", "42", "--add-assignee", "@me"] in invocations
