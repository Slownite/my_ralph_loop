from __future__ import annotations

import json
import subprocess
from pathlib import Path

VALID_CONFIG = """\
config_version = 1
target_branch = "main"
issue_directory = "docs/issues"

[harness]
profile = "custom"
command = ["fake-agent"]

[run]
max_issues = 1
max_attempts_per_issue = 3
attempt_timeout_seconds = 3600

[commands]
test = ["pytest"]
typecheck = ["pyright"]
lint = ["ruff", "check", "."]

[merge]
auto = true
push = false

[sandbox]
verification_network = false
environment_allowlist = []

[telemetry]
max_runs = 100
max_age_days = 30
"""


def run_validate(project: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ralf-loop", "validate", "--json"],
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
    )


def run_validate_human(project: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ralf-loop", "validate"],
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
    )


def test_validate_json_reports_missing_configuration(tmp_path: Path) -> None:
    result = run_validate(tmp_path)

    assert result.returncode == 2
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "valid": False,
        "errors": [
            {
                "code": "configuration_missing",
                "message": "ralf.toml does not exist",
                "path": "ralf.toml",
            }
        ],
    }


def test_validate_json_rejects_unknown_configuration_section(tmp_path: Path) -> None:
    (tmp_path / "docs" / "issues").mkdir(parents=True)
    (tmp_path / "ralf.toml").write_text(VALID_CONFIG + "\n[unexpected]\nenabled = true\n")

    result = run_validate(tmp_path)

    assert result.returncode == 2
    assert json.loads(result.stdout) == {
        "valid": False,
        "errors": [
            {
                "code": "configuration_unknown_key",
                "message": 'unknown configuration key "unexpected"',
                "path": "ralf.toml:unexpected",
            }
        ],
    }


def test_validate_json_reports_all_configuration_shape_errors(tmp_path: Path) -> None:
    (tmp_path / "docs" / "issues").mkdir(parents=True)
    invalid_config = VALID_CONFIG.replace("config_version = 1", 'config_version = "one"')
    invalid_config = invalid_config.replace("max_issues = 1", "max_issues = 1\nunexpected = 9")
    invalid_config = invalid_config.replace('test = ["pytest"]', "test = []")
    (tmp_path / "ralf.toml").write_text(invalid_config)

    result = run_validate(tmp_path)

    assert result.returncode == 2
    assert json.loads(result.stdout) == {
        "valid": False,
        "errors": [
            {
                "code": "configuration_empty_command",
                "message": 'command "commands.test" must not be empty',
                "path": "ralf.toml:commands.test",
            },
            {
                "code": "configuration_invalid_type",
                "message": 'configuration key "config_version" must be an integer',
                "path": "ralf.toml:config_version",
            },
            {
                "code": "configuration_unknown_key",
                "message": 'unknown configuration key "run.unexpected"',
                "path": "ralf.toml:run.unexpected",
            },
        ],
    }


def test_validate_json_reports_every_issue_queue_error_before_work(tmp_path: Path) -> None:
    issues = tmp_path / "docs" / "issues"
    issues.mkdir(parents=True)
    (tmp_path / "ralf.toml").write_text(VALID_CONFIG)
    (issues / "bad.md").write_text("---\nstatus: pending\n---\n\n# Bad name\n")
    (issues / "001-first.md").write_text("---\nstatus: pending\n# Missing delimiter\n")
    (issues / "01-duplicate.md").write_text(
        "---\nstatus: wandering\nbranch: bad..branch\nattempts: 0\n---\n\n# Duplicate\n"
    )

    result = run_validate(tmp_path)

    assert result.returncode == 2
    assert json.loads(result.stdout) == {
        "valid": False,
        "errors": [
            {
                "code": "issue_duplicate_id",
                "message": "issue ID 1 is also used by 01-duplicate.md",
                "path": "docs/issues/001-first.md",
            },
            {
                "code": "issue_invalid_frontmatter",
                "message": "frontmatter must end with a --- delimiter",
                "path": "docs/issues/001-first.md",
            },
            {
                "code": "issue_invalid_branch",
                "message": 'branch "bad..branch" is not a valid Git branch name',
                "path": "docs/issues/01-duplicate.md:branch",
            },
            {
                "code": "issue_invalid_status",
                "message": 'status "wandering" is not valid',
                "path": "docs/issues/01-duplicate.md:status",
            },
            {
                "code": "issue_invalid_filename",
                "message": "filename must be <numeric-id>-<slug>.md",
                "path": "docs/issues/bad.md",
            },
        ],
    }


def test_run_maps_configuration_preflight_to_exit_two(tmp_path: Path) -> None:
    (tmp_path / "docs" / "issues").mkdir(parents=True)
    (tmp_path / "ralf.toml").write_text(
        VALID_CONFIG.replace("[telemetry]\nmax_runs = 100\nmax_age_days = 30\n", "")
    )

    result = subprocess.run(
        ["ralf-loop", "run", "--dry-run"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert "invalid:" in result.stderr


def test_validate_human_confirms_configuration_and_queue(tmp_path: Path) -> None:
    (tmp_path / "docs" / "issues").mkdir(parents=True)
    (tmp_path / "ralf.toml").write_text(VALID_CONFIG)

    result = run_validate_human(tmp_path)

    assert result.returncode == 0
    assert result.stdout == "valid: configuration and issue queue\n"
    assert result.stderr == ""


def test_validate_reports_configuration_and_issue_errors_together(tmp_path: Path) -> None:
    issues = tmp_path / "docs" / "issues"
    issues.mkdir(parents=True)
    (issues / "bad.md").write_text("---\nstatus: pending\n---\n")
    (tmp_path / "ralf.toml").write_text("unknown = true\n" + VALID_CONFIG)

    result = run_validate(tmp_path)

    assert result.returncode == 2
    assert json.loads(result.stdout) == {
        "valid": False,
        "errors": [
            {
                "code": "configuration_unknown_key",
                "message": 'unknown configuration key "unknown"',
                "path": "ralf.toml:unknown",
            },
            {
                "code": "issue_invalid_filename",
                "message": "filename must be <numeric-id>-<slug>.md",
                "path": "docs/issues/bad.md",
            },
        ],
    }
