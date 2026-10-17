"""Public Harness process boundary."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class ProcessOutcome(StrEnum):
    """Classification of a Harness process result."""

    SUCCESS = "success"
    NONZERO_EXIT = "nonzero_exit"
    SPAWN_FAILURE = "spawn_failure"
    TIMEOUT = "timeout"
    SIGNAL_TERMINATION = "signal_termination"


@dataclass(frozen=True, slots=True)
class ProcessResult:
    """Observable result of one fresh Harness process."""

    outcome: ProcessOutcome
    stdout: str
    stderr: str
    returncode: int | None
    sandboxed: bool
    notice: str | None = None
    error: str | None = None
    signal: int | None = None
    force_killed: bool = False

    def to_record(self) -> dict[str, str | int | bool | None]:
        """Return content-free metadata suitable for an operational record."""

        return {
            "outcome": self.outcome.value,
            "sandbox": "enabled" if self.sandboxed else "disabled_by_override",
            "returncode": self.returncode,
            "signal": self.signal,
            "force_killed": self.force_killed,
        }


@dataclass(frozen=True, slots=True)
class CommandHarness:
    """Run a generic argument-array Harness through one process contract."""

    command: tuple[str, ...]
    environment_allowlist: tuple[str, ...] = ()
    timeout_seconds: float = 60 * 60
    termination_grace_seconds: float = 5.0
    bubblewrap_command: str = "bwrap"

    @staticmethod
    def _signal_process_group(process: subprocess.Popen[str], signal_number: int) -> None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal_number)

    def run(self, prompt: str, *, worktree: Path, no_sandbox: bool = False) -> ProcessResult:
        """Run one fresh Harness process in its assigned worktree."""

        environment = {
            name: os.environ[name] for name in self.environment_allowlist if name in os.environ
        }
        sandboxed = not no_sandbox
        notice = None if sandboxed else "sandbox disabled by explicit --no-sandbox override"
        worktree = worktree.resolve()
        launch_command = self.command
        if sandboxed:
            launch_command = (
                self.bubblewrap_command,
                "--die-with-parent",
                "--new-session",
                "--unshare-all",
                "--share-net",
                "--ro-bind",
                "/",
                "/",
                "--dev",
                "/dev",
                "--proc",
                "/proc",
                "--tmpfs",
                "/tmp",
                "--bind",
                str(worktree),
                str(worktree),
                "--chdir",
                str(worktree),
                "--",
                *self.command,
            )
        try:
            process = subprocess.Popen(
                launch_command,
                cwd=worktree,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
        except FileNotFoundError:
            return ProcessResult(
                outcome=ProcessOutcome.SPAWN_FAILURE,
                stdout="",
                stderr="",
                returncode=None,
                sandboxed=sandboxed,
                notice=notice,
                error=f"executable not found: {launch_command[0]}",
            )
        except OSError as error:
            detail = error.strerror or type(error).__name__
            return ProcessResult(
                outcome=ProcessOutcome.SPAWN_FAILURE,
                stdout="",
                stderr="",
                returncode=None,
                sandboxed=sandboxed,
                notice=notice,
                error=f"could not start executable {launch_command[0]}: {detail}",
            )
        try:
            stdout, stderr = process.communicate(prompt, timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired:
            self._signal_process_group(process, signal.SIGTERM)
            force_killed = False
            try:
                stdout, stderr = process.communicate(timeout=self.termination_grace_seconds)
            except subprocess.TimeoutExpired:
                self._signal_process_group(process, signal.SIGKILL)
                force_killed = True
                stdout, stderr = process.communicate()
            return ProcessResult(
                outcome=ProcessOutcome.TIMEOUT,
                stdout=stdout,
                stderr=stderr,
                returncode=process.returncode,
                sandboxed=sandboxed,
                notice=notice,
                signal=-process.returncode if process.returncode < 0 else None,
                force_killed=force_killed,
            )
        returncode = process.returncode
        return ProcessResult(
            outcome=(
                ProcessOutcome.SUCCESS
                if returncode == 0
                else (
                    ProcessOutcome.SIGNAL_TERMINATION
                    if returncode < 0
                    else ProcessOutcome.NONZERO_EXIT
                )
            ),
            stdout=stdout,
            stderr=stderr,
            returncode=returncode,
            sandboxed=sandboxed,
            notice=notice,
            signal=-returncode if returncode < 0 else None,
        )
