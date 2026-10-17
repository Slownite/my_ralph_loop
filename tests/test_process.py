from __future__ import annotations

import json
import signal
from pathlib import Path

import pytest

from ralf.process import CommandHarness, ProcessOutcome


def write_executable(path: Path, source: str) -> Path:
    path.write_text("#!/usr/bin/env python3\n" + source)
    path.chmod(0o755)
    return path


def test_harness_receives_prompt_worktree_and_allowed_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worktree = tmp_path / "assigned-worktree"
    worktree.mkdir()
    executable = write_executable(
        tmp_path / "inspect-harness",
        """\
import os
from pathlib import Path
import sys

print(Path.cwd().name)
print(sys.stdin.read())
print(os.environ["RALF_ALLOWED_TEST_VALUE"])
print("present" if "RALF_UNRELATED_SECRET" in os.environ else "absent")
print("child error", file=sys.stderr)
""",
    )
    monkeypatch.setenv("RALF_ALLOWED_TEST_VALUE", "allowed")
    monkeypatch.setenv("RALF_UNRELATED_SECRET", "must-not-leak")

    result = CommandHarness(
        (str(executable),), environment_allowlist=("RALF_ALLOWED_TEST_VALUE",)
    ).run("implement issue 12", worktree=worktree, no_sandbox=True)

    assert result.outcome is ProcessOutcome.SUCCESS
    assert result.stdout == "assigned-worktree\nimplement issue 12\nallowed\nabsent\n"
    assert result.stderr == "child error\n"
    assert result.sandboxed is False
    assert result.notice == "sandbox disabled by explicit --no-sandbox override"


def test_harness_classifies_nonzero_exit_and_keeps_streams_separate(tmp_path: Path) -> None:
    executable = write_executable(
        tmp_path / "failing-harness",
        """\
import sys

print("partial output")
print("failure detail", file=sys.stderr)
raise SystemExit(23)
""",
    )

    result = CommandHarness((str(executable),)).run("prompt", worktree=tmp_path, no_sandbox=True)

    assert result.outcome is ProcessOutcome.NONZERO_EXIT
    assert result.returncode == 23
    assert result.stdout == "partial output\n"
    assert result.stderr == "failure detail\n"


def test_harness_classifies_spawn_failure(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"

    result = CommandHarness((str(missing),)).run("prompt", worktree=tmp_path, no_sandbox=True)

    assert result.outcome is ProcessOutcome.SPAWN_FAILURE
    assert result.returncode is None
    assert result.stdout == ""
    assert result.stderr == ""
    assert result.error == f"executable not found: {missing}"


def test_harness_classifies_other_operating_system_spawn_failures(tmp_path: Path) -> None:
    not_executable = tmp_path / "not-executable"
    not_executable.write_text("content")

    result = CommandHarness((str(not_executable),)).run(
        "prompt", worktree=tmp_path, no_sandbox=True
    )

    assert result.outcome is ProcessOutcome.SPAWN_FAILURE
    assert result.returncode is None
    assert result.error == f"could not start executable {not_executable}: Permission denied"


def test_timeout_requests_graceful_termination_and_retains_output(tmp_path: Path) -> None:
    executable = write_executable(
        tmp_path / "slow-harness",
        """\
import signal
import sys
import time

def stop(_signal, _frame):
    print("graceful stop", file=sys.stderr, flush=True)
    raise SystemExit(0)

signal.signal(signal.SIGTERM, stop)
print("started", flush=True)
time.sleep(30)
""",
    )

    result = CommandHarness(
        (str(executable),), timeout_seconds=0.1, termination_grace_seconds=0.5
    ).run("prompt", worktree=tmp_path, no_sandbox=True)

    assert result.outcome is ProcessOutcome.TIMEOUT
    assert result.stdout == "started\n"
    assert result.stderr == "graceful stop\n"
    assert result.force_killed is False


def test_timeout_force_kills_after_grace_period(tmp_path: Path) -> None:
    executable = write_executable(
        tmp_path / "stuck-harness",
        """\
import signal
import time

signal.signal(signal.SIGTERM, signal.SIG_IGN)
print("ignoring termination", flush=True)
time.sleep(30)
""",
    )

    result = CommandHarness(
        (str(executable),), timeout_seconds=0.1, termination_grace_seconds=0.1
    ).run("prompt", worktree=tmp_path, no_sandbox=True)

    assert result.outcome is ProcessOutcome.TIMEOUT
    assert result.stdout == "ignoring termination\n"
    assert result.force_killed is True
    assert result.signal == signal.SIGKILL


def test_harness_classifies_signal_termination(tmp_path: Path) -> None:
    executable = write_executable(
        tmp_path / "signalled-harness",
        """\
import os
import signal

os.kill(os.getpid(), signal.SIGTERM)
""",
    )

    result = CommandHarness((str(executable),)).run("prompt", worktree=tmp_path, no_sandbox=True)

    assert result.outcome is ProcessOutcome.SIGNAL_TERMINATION
    assert result.returncode == -signal.SIGTERM
    assert result.signal == signal.SIGTERM


def test_harness_fails_closed_when_sandbox_cannot_start(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-run"
    executable = write_executable(
        tmp_path / "harness",
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n",
    )
    missing_bwrap = tmp_path / "missing-bwrap"

    result = CommandHarness((str(executable),), bubblewrap_command=str(missing_bwrap)).run(
        "prompt", worktree=tmp_path
    )

    assert result.outcome is ProcessOutcome.SPAWN_FAILURE
    assert result.sandboxed is True
    assert result.notice is None
    assert result.error == f"executable not found: {missing_bwrap}"
    assert marker.exists() is False


def test_harness_runs_in_sandbox_without_persisting_writes_outside_worktree(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "assigned-worktree"
    worktree.mkdir()
    outside = tmp_path / "outside"
    executable = write_executable(
        worktree / "sandbox-harness",
        f"""\
from pathlib import Path
import sys

Path("inside").write_text(sys.stdin.read())
try:
    Path({str(outside)!r}).write_text("escaped")
except OSError:
    pass
print("sandbox complete")
""",
    )

    result = CommandHarness((str(executable),)).run("sandbox prompt", worktree=worktree)

    assert result.outcome is ProcessOutcome.SUCCESS
    assert result.stdout == "sandbox complete\n"
    assert result.sandboxed is True
    assert result.notice is None
    assert (worktree / "inside").read_text() == "sandbox prompt"
    assert outside.exists() is False


def test_operational_record_marks_override_without_process_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = write_executable(
        tmp_path / "quiet-harness",
        "import os\nprint(os.environ['RALF_RECORD_SECRET'])\n",
    )
    monkeypatch.setenv("RALF_RECORD_SECRET", "sensitive-value")

    result = CommandHarness(
        (str(executable), "sensitive-argument"),
        environment_allowlist=("RALF_RECORD_SECRET",),
    ).run("sensitive prompt", worktree=tmp_path, no_sandbox=True)

    assert result.to_record() == {
        "outcome": "success",
        "sandbox": "disabled_by_override",
        "returncode": 0,
        "signal": None,
        "force_killed": False,
    }


def test_argument_array_has_no_shell_parsing_and_default_timeout_is_one_hour(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "shell-was-used"
    executable = write_executable(
        tmp_path / "argument-harness",
        "import json, sys\nprint(json.dumps(sys.argv[1:]))\n",
    )
    literal_argument = f"$(touch {marker})"
    harness = CommandHarness((str(executable), literal_argument))

    result = harness.run("prompt", worktree=tmp_path, no_sandbox=True)

    assert harness.timeout_seconds == 60 * 60
    assert json.loads(result.stdout) == [literal_argument]
    assert marker.exists() is False


def test_every_harness_attempt_starts_a_fresh_process(tmp_path: Path) -> None:
    executable = write_executable(
        tmp_path / "pid-harness",
        "import os\nprint(os.getpid())\n",
    )
    harness = CommandHarness((str(executable),))

    first = harness.run("first", worktree=tmp_path, no_sandbox=True)
    second = harness.run("second", worktree=tmp_path, no_sandbox=True)

    assert first.outcome is ProcessOutcome.SUCCESS
    assert second.outcome is ProcessOutcome.SUCCESS
    assert first.stdout != second.stdout
