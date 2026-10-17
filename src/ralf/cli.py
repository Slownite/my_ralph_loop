"""Command-line interface for Ralf."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from ralf.config import HARNESS_COMMANDS, build_config, load_config, validate_config, write_config
from ralf.diagnostics import Diagnostic
from ralf.issues import validate_issues


def _select_interactive_harness(parser: argparse.ArgumentParser) -> str:
    available = [
        profile
        for profile, command in HARNESS_COMMANDS.items()
        if shutil.which(command[0]) is not None
    ]
    if not available:
        parser.error("no supported harness executable was found on PATH; use --harness custom")
    print("Installed harnesses:")
    for number, profile in enumerate(available, start=1):
        print(f"  {number}. {profile}")
    response = input("Select harness [1]: ").strip()
    try:
        selection = 1 if not response else int(response)
        if selection < 1:
            raise IndexError
        return available[selection - 1]
    except (ValueError, IndexError):
        parser.error("harness selection must be one of the displayed numbers")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ralf-loop")
    subparsers = parser.add_subparsers(dest="command", required=True)
    initialize = subparsers.add_parser(
        "init", help="initialize deterministic project configuration"
    )
    initialize.add_argument("--harness", choices=(*HARNESS_COMMANDS, "custom"))
    initialize.add_argument("--harness-command", nargs=argparse.REMAINDER, metavar="ARG")
    initialize.add_argument("--model")
    validate = subparsers.add_parser("validate", help="validate configuration and issues")
    validate.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "init":
        profile = args.harness
        if profile is None:
            if not sys.stdin.isatty():
                parser.error("--harness is required when standard input is not a TTY")
            profile = _select_interactive_harness(parser)
        if profile == "custom":
            if not args.harness_command:
                parser.error("--harness-command is required for the custom harness")
            command = args.harness_command
        else:
            if args.harness_command:
                parser.error("--harness-command can only be used with --harness custom")
            command = HARNESS_COMMANDS[profile]
            if shutil.which(command[0]) is None:
                parser.error(f'harness executable "{command[0]}" was not found on PATH')
        try:
            config = build_config(
                Path.cwd(),
                harness_profile=profile,
                harness_command=command,
                model=args.model,
            )
        except (subprocess.CalledProcessError, ValueError) as error:
            parser.error(str(error))
        config_path = Path("ralf.toml")
        if config_path.exists():
            write_config(config, Path("ralf.toml.proposed"))
            print("preserved: ralf.toml")
            print("proposed: ralf.toml.proposed")
            return 0
        Path("docs/issues").mkdir(parents=True, exist_ok=True)
        write_config(config, config_path)
        print("initialized: ralf.toml")
        return 0

    config_path = Path("ralf.toml")
    if not config_path.is_file():
        errors = [
            Diagnostic(
                code="configuration_missing",
                message="ralf.toml does not exist",
                path="ralf.toml",
            )
        ]
    else:
        errors = validate_config(config_path)
        if not any(error.code == "configuration_invalid_toml" for error in errors):
            config = load_config(config_path)
            issue_directory = config.get("issue_directory")
            if isinstance(issue_directory, str) and issue_directory:
                errors.extend(validate_issues(Path(issue_directory), Path(issue_directory)))

    if errors:
        if args.as_json:
            print(json.dumps({"valid": False, "errors": [error.to_dict() for error in errors]}))
        else:
            for error in errors:
                print(f"invalid: {error.path}: {error.message}")
        return 2

    if args.as_json:
        print(json.dumps({"valid": True, "errors": []}))
    else:
        print("valid: configuration and issue queue")
    return 0
