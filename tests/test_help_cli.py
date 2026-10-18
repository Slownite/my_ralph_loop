from __future__ import annotations

import pytest
from pytest import CaptureFixture

from ralf.cli import main


def capture_help(capsys: CaptureFixture[str], *args: str) -> str:
    """Run the CLI in-process, expect argparse to exit, and return standard output."""
    with pytest.raises(SystemExit) as exit_info:
        main(list(args))
    assert exit_info.value.code in (0, None)
    return capsys.readouterr().out


def test_global_help_describes_the_program_and_lists_every_command(
    capsys: CaptureFixture[str],
) -> None:
    output = capture_help(capsys, "--help")

    assert "Coordinate unattended implementation" in output
    for command in ("init", "validate", "run", "status", "finalize", "retry"):
        assert f"    {command} " in output
    assert "exit codes:" in output
    assert "130" in output


def test_help_flag_shows_global_help_rather_than_run_options(
    capsys: CaptureFixture[str],
) -> None:
    output = capture_help(capsys, "--help")

    assert "commands:" in output
    assert "usage: ralf-loop [-h]" in output
    assert "usage: ralf-loop run" not in output


def test_run_help_documents_every_run_option(capsys: CaptureFixture[str]) -> None:
    output = capture_help(capsys, "run", "--help")

    for option in (
        "--dry-run",
        "--no-sandbox",
        "--max-issues",
        "--no-auto-merge",
        "--push",
        "--remote",
        "--local",
    ):
        assert option in output
    assert "run.max_issues" in output


def test_subcommand_help_explains_positional_and_json_flag(
    capsys: CaptureFixture[str],
) -> None:
    finalize = capture_help(capsys, "finalize", "--help")
    validate = capture_help(capsys, "validate", "--help")

    assert "ISSUE" in finalize
    assert "numeric ID of the ready issue" in finalize
    assert "code, message, and" in validate
    assert "path fields" in validate


def test_version_flag_reports_the_installed_version(capsys: CaptureFixture[str]) -> None:
    output = capture_help(capsys, "--version")

    assert output.startswith("ralf-loop ")
