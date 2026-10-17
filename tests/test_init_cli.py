from __future__ import annotations

import os
import stat
import subprocess
import sys
from io import StringIO
from pathlib import Path

from pytest import MonkeyPatch

from ralf.cli import main
from ralf.config import load_config


def _git(project: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=project, check=True, capture_output=True, text=True)


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    _git(project, "init", "-b", "release/next")
    return project


def _install_fake(bin_dir: Path, name: str) -> None:
    bin_dir.mkdir(exist_ok=True)
    executable = bin_dir / name
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)


def _run(project: Path, *args: str, path: Path | None = None) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    if path is not None:
        environment["PATH"] = f"{path}{os.pathsep}{environment['PATH']}"
    return subprocess.run(
        ["ralf-loop", *args],
        cwd=project,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


class _InteractiveInput(StringIO):
    def isatty(self) -> bool:
        return True


def test_init_writes_complete_deterministic_configuration(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / "pyproject.toml").write_text("[project]\nname = 'example'\n")
    bin_dir = tmp_path / "bin"
    _install_fake(bin_dir, "codex")

    result = _run(
        project, "init", "--harness", "codex", "--model", "vendor/model:latest", path=bin_dir
    )

    assert result.returncode == 0
    assert result.stdout == "initialized: ralf.toml\n"
    assert result.stderr == ""
    assert load_config(project / "ralf.toml") == {
        "config_version": 1,
        "target_branch": "release/next",
        "issue_directory": "docs/issues",
        "harness": {
            "profile": "codex",
            "command": [
                "codex",
                "exec",
                "--json",
                "--dangerously-bypass-approvals-and-sandbox",
                "-",
            ],
            "model": "vendor/model:latest",
        },
        "run": {
            "max_issues": 1,
            "max_attempts_per_issue": 3,
            "attempt_timeout_seconds": 3600,
        },
        "commands": {
            "test": ["pytest"],
            "typecheck": ["pyright"],
            "lint": ["ruff", "check", "."],
        },
        "merge": {"auto": True, "push": False},
        "sandbox": {"verification_network": False, "environment_allowlist": []},
        "telemetry": {"max_runs": 100, "max_age_days": 30},
    }

    validation = _run(project, "validate", "--json", path=bin_dir)

    assert validation.returncode == 0


def test_init_preserves_existing_configuration_and_writes_proposal(tmp_path: Path) -> None:
    project = _project(tmp_path)
    existing = "# hand-edited configuration\nconfig_version = 99\n"
    (project / "ralf.toml").write_text(existing)

    result = _run(project, "init", "--harness", "custom", "--harness-command", "agent")

    assert result.returncode == 0
    assert result.stdout == "preserved: ralf.toml\nproposed: ralf.toml.proposed\n"
    assert result.stderr == ""
    assert (project / "ralf.toml").read_text() == existing
    proposal = load_config(project / "ralf.toml.proposed")
    assert proposal["target_branch"] == "release/next"
    assert proposal["harness"] == {"profile": "custom", "command": ["agent"]}


def test_init_interactively_selects_from_installed_harnesses(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    project = _project(tmp_path)
    bin_dir = tmp_path / "bin"
    _install_fake(bin_dir, "codex")
    _install_fake(bin_dir, "opencode")
    monkeypatch.chdir(project)
    monkeypatch.setattr(
        "ralf.cli.shutil.which",
        lambda name: str(bin_dir / name) if name in {"codex", "opencode"} else None,
    )
    monkeypatch.setattr(sys, "stdin", _InteractiveInput("2\n"))

    result = main(["init"])

    assert result == 0
    assert load_config(project / "ralf.toml")["harness"] == {
        "profile": "opencode",
        "command": ["opencode", "run", "--standalone", "--format=json", "--auto"],
    }


def test_init_requires_harness_flag_when_input_is_redirected(tmp_path: Path) -> None:
    project = _project(tmp_path)

    result = _run(project, "init")

    assert result.returncode == 2
    assert result.stdout == ""
    assert "--harness is required when standard input is not a TTY" in result.stderr
    assert not (project / "ralf.toml").exists()


def test_init_preserves_custom_harness_argument_array(tmp_path: Path) -> None:
    project = _project(tmp_path)

    result = _run(
        project,
        "init",
        "--harness",
        "custom",
        "--model",
        "opaque",
        "--harness-command",
        "agent",
        "--headless",
        "value",
    )

    assert result.returncode == 0
    assert load_config(project / "ralf.toml")["harness"] == {
        "profile": "custom",
        "command": ["agent", "--headless", "value"],
        "model": "opaque",
    }
