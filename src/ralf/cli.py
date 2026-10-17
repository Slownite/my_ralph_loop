"""Command-line interface for Ralf."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="preflight and print the exact execution plan without mutating anything",
    )
    parser.add_argument(
        "--no-sandbox",
        action="store_true",
        dest="no_sandbox",
        help="run the Harness and verification without Bubblewrap (reduces isolation)",
    )
    parser.add_argument(
        "--max-issues",
        type=int,
        dest="max_issues",
        metavar="N",
        help="stop after N issues in this run (default: run.max_issues from ralf.toml)",
    )
    parser.add_argument(
        "--no-auto-merge",
        action="store_true",
        dest="no_auto_merge",
        help="leave successful issues ready instead of merging them into the target",
    )
    parser.add_argument(
        "--push",
        action="store_true",
        dest="push",
        help="push the target branch after a successful merge",
    )
    parser.add_argument(
        "--remote",
        dest="remote",
        metavar="NAME",
        help="fetch NAME first and require a fast-forward target before running",
    )


def _version() -> str:
    try:
        return package_version("ralf-loop")
    except PackageNotFoundError:
        return "unknown"


_PARENT_DESCRIPTION = """\
Coordinate unattended implementation of a project-owned issue queue.

Ralf owns Issue state, Git mutations, sandboxing, verification, commits,
merges, recovery, and audit records. The coding Harness edits files but can
never declare its own work Ready or Done.
"""

_PARENT_EPILOG = """\
a bare `ralf-loop` is exactly `ralf-loop run`

examples:
  ralf-loop init --harness opencode   write ralf.toml for the opencode Harness
  ralf-loop validate                  check configuration and the issue queue
  ralf-loop run --dry-run             preflight and print the plan only
  ralf-loop status                    report issue states and preserved worktrees
  ralf-loop retry 7                   resume blocked issue 7 with a fresh allowance
  ralf-loop finalize 7                merge ready issue 7 into the target

exit codes:
  0    the requested operation completed
  1    a workflow error that is not otherwise classified
  2    configuration, issue-queue, or preflight validation failed
  3    work became blocked and needs a deliberate retry
  4    infrastructure failure; local work was preserved
  130  interrupted by SIGINT or SIGTERM; local work was preserved
"""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ralf-loop",
        description=_PARENT_DESCRIPTION,
        epilog=_PARENT_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_version()}",
        help="show the installed version and exit",
    )
    subparsers = parser.add_subparsers(dest="command", title="commands", metavar="<command>")

    initialize = subparsers.add_parser(
        "init",
        help="initialize deterministic project configuration",
        description=(
            "Write a complete, deterministic ralf.toml from the current branch, detected "
            "project commands, and one selected Harness profile."
        ),
        epilog=(
            "When ralf.toml already exists it is preserved and the new configuration is "
            "written to ralf.toml.proposed instead."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    initialize.add_argument(
        "--harness",
        choices=(*HARNESS_COMMANDS, "custom"),
        help="Harness profile to configure; prompted interactively when omitted on a TTY",
    )
    initialize.add_argument(
        "--harness-command",
        nargs=argparse.REMAINDER,
        metavar="ARG",
        help="command for --harness custom; every remaining argument is captured verbatim",
    )
    initialize.add_argument(
        "--model",
        metavar="MODEL",
        help="opaque provider/model string recorded for the Harness (no discovery or validation)",
    )

    validate = subparsers.add_parser(
        "validate",
        help="validate configuration and issues",
        description="Check configuration and the entire issue queue before any mutation.",
    )
    validate.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="print machine-readable results with stable code, message, and path fields",
    )

    run = subparsers.add_parser(
        "run",
        help="run the issue queue",
        description=(
            "Process pending issues in order, verifying and committing each one and "
            "optionally merging successful work into the target."
        ),
        epilog=(
            "Without --max-issues the run limit comes from run.max_issues in ralf.toml; "
            "with auto-merge enabled, run also finalizes each successful issue."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_run_options(run)

    status = subparsers.add_parser(
        "status",
        help="report issue workflow state",
        description="Report pending, in-progress, ready, blocked, and done issues.",
    )
    status.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="print the same state as JSON",
    )

    finalize = subparsers.add_parser(
        "finalize",
        help="merge one ready issue into the target",
        description="Recheck a ready issue against the target and merge it.",
    )
    finalize.add_argument("issue", type=int, metavar="ISSUE", help="numeric ID of the ready issue")
    finalize.add_argument(
        "--no-sandbox",
        action="store_true",
        dest="no_sandbox",
        help="rerun the Gate without Bubblewrap (reduces isolation)",
    )
    finalize.add_argument(
        "--push",
        action="store_true",
        dest="push",
        help="push the target branch after merging",
    )
    finalize.add_argument(
        "--remote",
        dest="remote",
        metavar="NAME",
        help="fetch NAME first and require a fast-forward target before merging",
    )

    retry = subparsers.add_parser(
        "retry",
        help="resume one blocked issue with a fresh allowance",
        description=(
            "Resume a blocked issue from its preserved edits with a fresh per-run allowance."
        ),
    )
    retry.add_argument("issue", type=int, metavar="ISSUE", help="numeric ID of the blocked issue")
    retry.add_argument(
        "--no-sandbox",
        action="store_true",
        dest="no_sandbox",
        help="run the Harness and verification without Bubblewrap (reduces isolation)",
    )
    retry.add_argument(
        "--push",
        action="store_true",
        dest="push",
        help="push the target branch after a successful merge",
    )
    retry.add_argument(
        "--remote",
        dest="remote",
        metavar="NAME",
        help="fetch NAME first and require a fast-forward target before running",
    )

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


def _warn_no_sandbox(args: argparse.Namespace) -> None:
    if getattr(args, "no_sandbox", False):
        print(
            "warning: --no-sandbox disables Bubblewrap; the Harness and verification "
            "commands run with full filesystem access",
            file=sys.stderr,
        )


def _run_run(args: argparse.Namespace) -> int:
    _warn_no_sandbox(args)
    if args.dry_run:

        def dry_run() -> int:
            workflow = _workflow(args)
            with RepositoryLock(workflow.repository):
                plan = workflow.plan(fetch=False)
            print(plan.describe())
            return EXIT_OK

        return _execute(dry_run)
    return _execute(lambda: _workflow(args).run())


def _run_status(args: argparse.Namespace) -> int:
    return _execute(lambda: _show_status(args))


def _show_status(args: argparse.Namespace) -> int:
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
    _warn_no_sandbox(args)
    return _execute(lambda: _workflow(args).finalize_issue(args.issue))


def _run_retry(args: argparse.Namespace) -> int:
    _warn_no_sandbox(args)
    return _execute(lambda: _workflow(args).retry_issue(args.issue))


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
    if not arguments or (
        arguments[0].startswith("-") and arguments[0] not in {"-h", "--help", "--version"}
    ):
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
