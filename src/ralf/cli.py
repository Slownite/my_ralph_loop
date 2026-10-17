"""Command-line interface for Ralf."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from ralf.config import load_config, validate_config
from ralf.diagnostics import Diagnostic
from ralf.issues import validate_issues


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ralf-loop")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validate configuration and issues")
    validate.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command != "validate":
        return 1

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
