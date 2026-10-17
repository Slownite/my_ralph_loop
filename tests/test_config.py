from __future__ import annotations

from pathlib import Path

import pytest

from ralf.config import detect_project_commands, validate_config

from .test_validate_cli import VALID_CONFIG


@pytest.mark.parametrize(
    ("marker", "contents", "commands"),
    [
        (
            "package.json",
            '{"scripts":{"lint":"eslint ."}}',
            {
                "test": ["npm", "test"],
                "typecheck": ["tsc", "--noEmit"],
                "lint": ["npm", "run", "lint"],
            },
        ),
        (
            "Makefile",
            "test:\n\ttrue\n",
            {
                "test": ["make", "test"],
                "typecheck": ["make", "typecheck"],
                "lint": ["make", "lint"],
            },
        ),
        (
            "Cargo.toml",
            "[package]\nname = 'example'\n",
            {
                "test": ["cargo", "test"],
                "typecheck": ["cargo", "check"],
                "lint": ["cargo", "clippy"],
            },
        ),
        (
            "go.mod",
            "module example.test/project\n",
            {
                "test": ["go", "test", "./..."],
                "typecheck": ["go", "vet", "./..."],
                "lint": ["golangci-lint", "run"],
            },
        ),
    ],
)
def test_project_commands_are_detected_as_argument_arrays(
    tmp_path: Path, marker: str, contents: str, commands: dict[str, list[str]]
) -> None:
    (tmp_path / marker).write_text(contents)

    assert detect_project_commands(tmp_path) == commands


def test_configuration_requires_target_branch(tmp_path: Path) -> None:
    config_path = tmp_path / "ralf.toml"
    config_path.write_text(VALID_CONFIG.replace('target_branch = "main"\n', ""))

    diagnostics = validate_config(config_path)

    assert [diagnostic.to_dict() for diagnostic in diagnostics] == [
        {
            "code": "configuration_missing_key",
            "message": 'required configuration key "target_branch" is missing',
            "path": "ralf.toml:target_branch",
        }
    ]


def test_configuration_reports_invalid_values_across_sections(tmp_path: Path) -> None:
    invalid_config = VALID_CONFIG
    invalid_config = invalid_config.replace("config_version = 1", "config_version = 2")
    invalid_config = invalid_config.replace('target_branch = "main"', 'target_branch = "bad..name"')
    invalid_config = invalid_config.replace(
        'issue_directory = "docs/issues"', 'issue_directory = ""'
    )
    invalid_config = invalid_config.replace('profile = "custom"', "profile = 7")
    invalid_config = invalid_config.replace('command = ["fake-agent"]', "command = []")
    invalid_config = invalid_config.replace("max_issues = 1", "max_issues = 0")
    invalid_config = invalid_config.replace('lint = ["ruff", "check", "."]', 'lint = ["ruff", 7]')
    invalid_config = invalid_config.replace("auto = true", 'auto = "yes"')
    invalid_config = invalid_config.replace(
        "environment_allowlist = []", 'environment_allowlist = ["TOKEN", 7]'
    )
    invalid_config = invalid_config.replace("max_runs = 100", "max_runs = 0")
    config_path = tmp_path / "ralf.toml"
    config_path.write_text(invalid_config)

    diagnostics = validate_config(config_path)

    assert [diagnostic.to_dict() for diagnostic in diagnostics] == [
        {
            "code": "configuration_invalid_type",
            "message": 'command "commands.lint" must be an array of non-empty strings',
            "path": "ralf.toml:commands.lint",
        },
        {
            "code": "configuration_invalid_value",
            "message": 'configuration key "config_version" must equal 1',
            "path": "ralf.toml:config_version",
        },
        {
            "code": "configuration_empty_command",
            "message": 'command "harness.command" must not be empty',
            "path": "ralf.toml:harness.command",
        },
        {
            "code": "configuration_invalid_type",
            "message": 'configuration key "harness.profile" must be a string',
            "path": "ralf.toml:harness.profile",
        },
        {
            "code": "configuration_invalid_value",
            "message": 'configuration key "issue_directory" must not be empty',
            "path": "ralf.toml:issue_directory",
        },
        {
            "code": "configuration_invalid_type",
            "message": 'configuration key "merge.auto" must be a boolean',
            "path": "ralf.toml:merge.auto",
        },
        {
            "code": "configuration_invalid_value",
            "message": 'configuration key "run.max_issues" must be a positive integer',
            "path": "ralf.toml:run.max_issues",
        },
        {
            "code": "configuration_invalid_type",
            "message": 'configuration key "sandbox.environment_allowlist" must be an array '
            "of non-empty strings",
            "path": "ralf.toml:sandbox.environment_allowlist",
        },
        {
            "code": "configuration_invalid_branch",
            "message": 'branch "bad..name" is not a valid Git branch name',
            "path": "ralf.toml:target_branch",
        },
        {
            "code": "configuration_invalid_value",
            "message": 'configuration key "telemetry.max_runs" must be a positive integer',
            "path": "ralf.toml:telemetry.max_runs",
        },
    ]
