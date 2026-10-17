"""Load and validate Ralf configuration."""

from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path
from typing import cast

from ralf.diagnostics import Diagnostic
from ralf.git import is_valid_branch_name

ROOT_KEYS = {
    "config_version",
    "target_branch",
    "issue_directory",
    "harness",
    "run",
    "commands",
    "merge",
    "sandbox",
    "telemetry",
}
SECTION_KEYS = {
    "harness": {"profile", "command", "model"},
    "run": {"max_issues", "max_attempts_per_issue", "attempt_timeout_seconds"},
    "commands": {"test", "typecheck", "lint", "custom"},
    "merge": {"auto", "push", "remote"},
    "sandbox": {"verification_network", "environment_allowlist"},
    "telemetry": {"max_runs", "max_age_days"},
}

HARNESS_COMMANDS: dict[str, list[str]] = {
    "codex": [
        "codex",
        "exec",
        "--json",
        "--dangerously-bypass-approvals-and-sandbox",
        "-",
    ],
    "omp": ["omp", "-p", "--mode=json", "--approval-mode=yolo", "--max-time=3600"],
    "opencode": ["opencode", "run", "--standalone", "--format=json", "--auto"],
}


def current_branch(project_root: Path) -> str:
    """Return the project's checked-out branch."""

    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )
    branch = result.stdout.strip()
    if not branch:
        raise ValueError("cannot initialize configuration from a detached HEAD")
    return branch


def detect_project_commands(project_root: Path) -> dict[str, list[str]]:
    """Detect fixed verification argument arrays from project files."""

    if (project_root / "package.json").is_file():
        commands = {
            "test": ["npm", "test"],
            "typecheck": ["tsc", "--noEmit"],
        }
        try:
            package: object = json.loads((project_root / "package.json").read_text())
        except (OSError, json.JSONDecodeError):
            package = {}
        if isinstance(package, dict):
            scripts = cast(dict[object, object], package).get("scripts")
            if isinstance(scripts, dict) and "lint" in scripts:
                commands["lint"] = ["npm", "run", "lint"]
        return commands
    if (project_root / "pyproject.toml").is_file() or (project_root / "setup.cfg").is_file():
        return {
            "test": ["pytest"],
            "typecheck": ["pyright"],
            "lint": ["ruff", "check", "."],
        }
    if (project_root / "Makefile").is_file():
        return {
            "test": ["make", "test"],
            "typecheck": ["make", "typecheck"],
            "lint": ["make", "lint"],
        }
    if (project_root / "Cargo.toml").is_file():
        return {
            "test": ["cargo", "test"],
            "typecheck": ["cargo", "check"],
            "lint": ["cargo", "clippy"],
        }
    if (project_root / "go.mod").is_file():
        return {
            "test": ["go", "test", "./..."],
            "typecheck": ["go", "vet", "./..."],
            "lint": ["golangci-lint", "run"],
        }
    return {}


def build_config(
    project_root: Path,
    *,
    harness_profile: str,
    harness_command: list[str],
    model: str | None = None,
) -> dict[str, object]:
    """Build a complete version 1 configuration from init-time observations."""

    harness: dict[str, object] = {
        "profile": harness_profile,
        "command": harness_command,
    }
    if model is not None:
        harness["model"] = model
    return {
        "config_version": 1,
        "target_branch": current_branch(project_root),
        "issue_directory": "docs/issues",
        "harness": harness,
        "run": {
            "max_issues": 1,
            "max_attempts_per_issue": 3,
            "attempt_timeout_seconds": 3600,
        },
        "commands": detect_project_commands(project_root),
        "merge": {"auto": True, "push": False},
        "sandbox": {"verification_network": False, "environment_allowlist": []},
        "telemetry": {"max_runs": 100, "max_age_days": 30},
    }


def _toml_value(value: object) -> str:
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    if type(value) is str:
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in cast(list[object], value)) + "]"
    raise TypeError(f"unsupported TOML value: {type(value).__name__}")


def write_config(config: dict[str, object], path: Path) -> None:
    """Write configuration deterministically as TOML."""

    lines: list[str] = []
    for key, value in config.items():
        if isinstance(value, dict):
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(f"[{key}]")
            for child_key, child_value in cast(dict[str, object], value).items():
                lines.append(f"{child_key} = {_toml_value(child_value)}")
        else:
            lines.append(f"{key} = {_toml_value(value)}")
    path.write_text("\n".join(lines) + "\n")


def load_config(path: Path) -> dict[str, object]:
    """Load a TOML configuration from disk."""

    with path.open("rb") as config_file:
        return cast(dict[str, object], tomllib.load(config_file))


def _diagnostic(code: str, message: str, path: Path, key: str) -> Diagnostic:
    return Diagnostic(code=code, message=message, path=f"{path.name}:{key}")


def _string_list(value: object, *, allow_empty: bool) -> bool:
    if not isinstance(value, list):
        return False
    items = cast(list[object], value)
    return (allow_empty or bool(items)) and all(type(item) is str and bool(item) for item in items)


def _required_table(
    config: dict[str, object], section: str, path: Path, diagnostics: list[Diagnostic]
) -> dict[str, object] | None:
    value = config.get(section)
    if value is None:
        diagnostics.append(
            _diagnostic(
                "configuration_missing_key",
                f'required configuration key "{section}" is missing',
                path,
                section,
            )
        )
        return None
    if not isinstance(value, dict):
        diagnostics.append(
            _diagnostic(
                "configuration_invalid_type",
                f'configuration key "{section}" must be a table',
                path,
                section,
            )
        )
        return None
    return cast(dict[str, object], value)


def _require_key(
    table: dict[str, object], section: str, key: str, path: Path, diagnostics: list[Diagnostic]
) -> object | None:
    if key not in table:
        dotted = f"{section}.{key}"
        diagnostics.append(
            _diagnostic(
                "configuration_missing_key",
                f'required configuration key "{dotted}" is missing',
                path,
                dotted,
            )
        )
        return None
    return table[key]


def _validate_command(
    value: object, dotted: str, path: Path, diagnostics: list[Diagnostic]
) -> None:
    if value == []:
        diagnostics.append(
            _diagnostic(
                "configuration_empty_command",
                f'command "{dotted}" must not be empty',
                path,
                dotted,
            )
        )
    elif not _string_list(value, allow_empty=False):
        diagnostics.append(
            _diagnostic(
                "configuration_invalid_type",
                f'command "{dotted}" must be an array of non-empty strings',
                path,
                dotted,
            )
        )


def _validate_positive_integer(
    value: object, dotted: str, path: Path, diagnostics: list[Diagnostic]
) -> None:
    if type(value) is not int:
        diagnostics.append(
            _diagnostic(
                "configuration_invalid_type",
                f'configuration key "{dotted}" must be an integer',
                path,
                dotted,
            )
        )
    elif value <= 0:
        diagnostics.append(
            _diagnostic(
                "configuration_invalid_value",
                f'configuration key "{dotted}" must be a positive integer',
                path,
                dotted,
            )
        )


def _validate_boolean(
    value: object, dotted: str, path: Path, diagnostics: list[Diagnostic]
) -> None:
    if type(value) is not bool:
        diagnostics.append(
            _diagnostic(
                "configuration_invalid_type",
                f'configuration key "{dotted}" must be a boolean',
                path,
                dotted,
            )
        )


def validate_config(path: Path) -> list[Diagnostic]:
    """Return every configuration diagnostic that can be found safely."""

    try:
        config = load_config(path)
    except tomllib.TOMLDecodeError as error:
        return [
            Diagnostic(
                code="configuration_invalid_toml",
                message=str(error),
                path=path.name,
            )
        ]

    diagnostics = [
        _diagnostic(
            "configuration_unknown_key",
            f'unknown configuration key "{key}"',
            path,
            key,
        )
        for key in sorted(config.keys() - ROOT_KEYS)
    ]

    version = config.get("config_version")
    if version is None:
        diagnostics.append(
            _diagnostic(
                "configuration_missing_key",
                'required configuration key "config_version" is missing',
                path,
                "config_version",
            )
        )
    elif type(version) is not int:
        diagnostics.append(
            _diagnostic(
                "configuration_invalid_type",
                'configuration key "config_version" must be an integer',
                path,
                "config_version",
            )
        )
    elif version != 1:
        diagnostics.append(
            _diagnostic(
                "configuration_invalid_value",
                'configuration key "config_version" must equal 1',
                path,
                "config_version",
            )
        )

    target_branch = config.get("target_branch")
    if target_branch is None:
        diagnostics.append(
            _diagnostic(
                "configuration_missing_key",
                'required configuration key "target_branch" is missing',
                path,
                "target_branch",
            )
        )
    elif type(target_branch) is not str:
        diagnostics.append(
            _diagnostic(
                "configuration_invalid_type",
                'configuration key "target_branch" must be a string',
                path,
                "target_branch",
            )
        )
    elif not is_valid_branch_name(target_branch):
        diagnostics.append(
            _diagnostic(
                "configuration_invalid_branch",
                f'branch "{target_branch}" is not a valid Git branch name',
                path,
                "target_branch",
            )
        )

    issue_directory = config.get("issue_directory")
    if issue_directory is None:
        diagnostics.append(
            _diagnostic(
                "configuration_missing_key",
                'required configuration key "issue_directory" is missing',
                path,
                "issue_directory",
            )
        )
    elif type(issue_directory) is not str:
        diagnostics.append(
            _diagnostic(
                "configuration_invalid_type",
                'configuration key "issue_directory" must be a string',
                path,
                "issue_directory",
            )
        )
    elif not issue_directory:
        diagnostics.append(
            _diagnostic(
                "configuration_invalid_value",
                'configuration key "issue_directory" must not be empty',
                path,
                "issue_directory",
            )
        )

    tables: dict[str, dict[str, object]] = {}
    for section, known_keys in SECTION_KEYS.items():
        table = _required_table(config, section, path, diagnostics)
        if table is None:
            continue
        tables[section] = table
        diagnostics.extend(
            _diagnostic(
                "configuration_unknown_key",
                f'unknown configuration key "{section}.{key}"',
                path,
                f"{section}.{key}",
            )
            for key in sorted(table.keys() - known_keys)
        )

    harness = tables.get("harness")
    if harness is not None:
        profile = _require_key(harness, "harness", "profile", path, diagnostics)
        if profile is not None and type(profile) is not str:
            diagnostics.append(
                _diagnostic(
                    "configuration_invalid_type",
                    'configuration key "harness.profile" must be a string',
                    path,
                    "harness.profile",
                )
            )
        command = harness.get("command")
        if command is not None:
            _validate_command(command, "harness.command", path, diagnostics)
        elif profile == "custom":
            _require_key(harness, "harness", "command", path, diagnostics)
        model = harness.get("model")
        if model is not None and type(model) is not str:
            diagnostics.append(
                _diagnostic(
                    "configuration_invalid_type",
                    'configuration key "harness.model" must be a string',
                    path,
                    "harness.model",
                )
            )

    run = tables.get("run")
    if run is not None:
        for key in ("max_issues", "max_attempts_per_issue", "attempt_timeout_seconds"):
            value = _require_key(run, "run", key, path, diagnostics)
            if value is not None:
                _validate_positive_integer(value, f"run.{key}", path, diagnostics)

    commands = tables.get("commands")
    if commands is not None:
        for key in ("test", "typecheck", "lint"):
            value = commands.get(key)
            if value is not None:
                _validate_command(value, f"commands.{key}", path, diagnostics)
        custom = commands.get("custom")
        if custom is not None:
            if not isinstance(custom, dict):
                diagnostics.append(
                    _diagnostic(
                        "configuration_invalid_type",
                        'configuration key "commands.custom" must be a table',
                        path,
                        "commands.custom",
                    )
                )
            else:
                for name, value in cast(dict[str, object], custom).items():
                    _validate_command(value, f"commands.custom.{name}", path, diagnostics)

    merge = tables.get("merge")
    if merge is not None:
        for key in ("auto", "push"):
            value = _require_key(merge, "merge", key, path, diagnostics)
            if value is not None:
                _validate_boolean(value, f"merge.{key}", path, diagnostics)
        remote = merge.get("remote")
        if remote is not None and (type(remote) is not str or not remote):
            diagnostics.append(
                _diagnostic(
                    "configuration_invalid_type",
                    'configuration key "merge.remote" must be a non-empty string',
                    path,
                    "merge.remote",
                )
            )

    sandbox = tables.get("sandbox")
    if sandbox is not None:
        network = _require_key(sandbox, "sandbox", "verification_network", path, diagnostics)
        if network is not None:
            _validate_boolean(network, "sandbox.verification_network", path, diagnostics)
        environment = _require_key(sandbox, "sandbox", "environment_allowlist", path, diagnostics)
        if environment is not None and not _string_list(environment, allow_empty=True):
            diagnostics.append(
                _diagnostic(
                    "configuration_invalid_type",
                    'configuration key "sandbox.environment_allowlist" must be an array '
                    "of non-empty strings",
                    path,
                    "sandbox.environment_allowlist",
                )
            )

    telemetry = tables.get("telemetry")
    if telemetry is not None:
        for key in ("max_runs", "max_age_days"):
            value = _require_key(telemetry, "telemetry", key, path, diagnostics)
            if value is not None:
                _validate_positive_integer(value, f"telemetry.{key}", path, diagnostics)

    return sorted(diagnostics, key=lambda diagnostic: (diagnostic.path, diagnostic.code))
