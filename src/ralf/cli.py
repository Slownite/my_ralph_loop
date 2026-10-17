"""Command-line interface for Ralf."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast

from ralf.config import HARNESS_COMMANDS, build_config, load_config, validate_config, write_config
from ralf.diagnostics import Diagnostic
from ralf.issues import validate_issues
from ralf.orchestrator import (
    BlockedError,
    InfrastructureFailure,
    Interrupted,
    Workflow,
    WorkflowError,
)
from ralf.plan import PreflightError, RepositoryLock

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_INVALID = 2
EXIT_BLOCKED = 3
EXIT_INFRASTRUCTURE = 4
EXIT_INTERRUPTED = 130

CONFIG_PATH = Path("ralf.toml")


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


def _add_run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dry-run", action="store_true", dest="dry_run")
    parser.add_argument("--no-sandbox", action="store_true", dest="no_sandbox")
    parser.add_argument("--max-issues", type=int, dest="max_issues")
    parser.add_argument("--no-auto-merge", action="store_true", dest="no_auto_merge")
    parser.add_argument("--push", action="store_true", dest="push")
    parser.add_argument("--remote", dest="remote")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ralf-loop")
    subparsers = parser.add_subparsers(dest="command")

    initialize = subparsers.add_parser(
        "init", help="initialize deterministic project configuration"
    )
    initialize.add_argument("--harness", choices=(*HARNESS_COMMANDS, "custom"))
    initialize.add_argument("--harness-command", nargs=argparse.REMAINDER, metavar="ARG")
    initialize.add_argument("--model")

    validate = subparsers.add_parser("validate", help="validate configuration and issues")
    validate.add_argument("--json", action="store_true", dest="as_json")

    run = subparsers.add_parser("run", help="run the issue queue")
    _add_run_options(run)

    status = subparsers.add_parser("status", help="report issue workflow state")
    status.add_argument("--json", action="store_true", dest="as_json")

    finalize = subparsers.add_parser("finalize", help="merge one ready issue into the target")
    finalize.add_argument("issue", type=int)
    finalize.add_argument("--no-sandbox", action="store_true", dest="no_sandbox")
    finalize.add_argument("--push", action="store_true", dest="push")
    finalize.add_argument("--remote", dest="remote")

    retry = subparsers.add_parser("retry", help="resume one blocked issue with a fresh allowance")
    retry.add_argument("issue", type=int)
    _add_run_options(retry)

    return parser


def _run_init(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
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
            Path.cwd(), harness_profile=profile, harness_command=command, model=args.model
        )
    except (subprocess.CalledProcessError, ValueError) as error:
        parser.error(str(error))
    if CONFIG_PATH.exists():
        write_config(config, Path("ralf.toml.proposed"))
        print("preserved: ralf.toml")
        print("proposed: ralf.toml.proposed")
        return EXIT_OK
    Path("docs/issues").mkdir(parents=True, exist_ok=True)
    write_config(config, CONFIG_PATH)
    print("initialized: ralf.toml")
    return EXIT_OK


def _run_validate(args: argparse.Namespace) -> int:
    if not CONFIG_PATH.is_file():
        errors = [
            Diagnostic(
                code="configuration_missing",
                message="ralf.toml does not exist",
                path="ralf.toml",
            )
        ]
    else:
        errors = validate_config(CONFIG_PATH)
        if not any(error.code == "configuration_invalid_toml" for error in errors):
            config = load_config(CONFIG_PATH)
            issue_directory = config.get("issue_directory")
            if isinstance(issue_directory, str) and issue_directory:
                errors.extend(validate_issues(Path(issue_directory), Path(issue_directory)))

    if errors:
        if args.as_json:
            print(json.dumps({"valid": False, "errors": [error.to_dict() for error in errors]}))
        else:
            for error in errors:
                print(f"invalid: {error.path}: {error.message}")
        return EXIT_INVALID

    if args.as_json:
        print(json.dumps({"valid": True, "errors": []}))
    else:
        print("valid: configuration and issue queue")
    return EXIT_OK


def _workflow(args: argparse.Namespace) -> Workflow:
    return Workflow(
        Path.cwd(),
        CONFIG_PATH,
        no_sandbox=getattr(args, "no_sandbox", False),
        remote=getattr(args, "remote", None),
        auto_merge=False if getattr(args, "no_auto_merge", False) else None,
        push=True if getattr(args, "push", False) else None,
        max_issues=getattr(args, "max_issues", None),
    )


def _run_run(args: argparse.Namespace) -> int:
    workflow = _workflow(args)
    if args.dry_run:

        def dry_run() -> int:
            with RepositoryLock(workflow.repository):
                plan = workflow.plan(fetch=False)
            print(plan.describe())
            return EXIT_OK

        return _execute(dry_run)
    return _execute(workflow.run)


def _run_status(args: argparse.Namespace) -> int:
    workflow = _workflow(args)
    state = workflow.status()
    if args.as_json:
        print(json.dumps(state, sort_keys=True))
        return EXIT_OK
    print(f"target branch: {state['target_branch']}")
    issues = state["issues"]
    assert isinstance(issues, list)
    typed_issues = cast("list[dict[str, object]]", issues)
    if not typed_issues:
        print("issues: none")
    for issue in typed_issues:
        marker = " (worktree preserved)" if issue["worktree_preserved"] else ""
        print(f"  {issue['number']!s:>4} {issue['status']}: {issue['branch'] or '-'}{marker}")
    return EXIT_OK


def _run_finalize(args: argparse.Namespace) -> int:
    workflow = _workflow(args)
    return _execute(lambda: workflow.finalize_issue(args.issue))


def _run_retry(args: argparse.Namespace) -> int:
    workflow = _workflow(args)
    return _execute(lambda: workflow.retry_issue(args.issue))


def _execute(action: Callable[[], int]) -> int:
    try:
        return action()
    except PreflightError as error:
        _report_preflight(error)
        return EXIT_INVALID
    except Interrupted as error:
        print(f"interrupted: {error}", file=sys.stderr)
        return EXIT_INTERRUPTED
    except BlockedError as error:
        print(f"blocked: {error}", file=sys.stderr)
        return EXIT_BLOCKED
    except InfrastructureFailure as error:
        print(f"infrastructure failure: {error}", file=sys.stderr)
        return EXIT_INFRASTRUCTURE
    except WorkflowError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR


def _report_preflight(error: PreflightError) -> None:
    for message in error.messages:
        print(f"invalid: {message}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0].startswith("-"):
        arguments = ["run", *arguments]
    parser = _parser()
    args = parser.parse_args(arguments)

    if args.command == "init":
        return _run_init(args, parser)
    if args.command == "validate":
        return _run_validate(args)
    if args.command == "status":
        return _run_status(args)
    if args.command == "finalize":
        return _run_finalize(args)
    if args.command == "retry":
        return _run_retry(args)
    return _run_run(args)
