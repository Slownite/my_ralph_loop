"""Public Harness process boundary.

Every Harness attempt is a fresh process. The prompt arrives on standard input
and the process works in the assigned worktree. Standard output and error are
captured separately and the result classifies success, nonzero exit, spawn
failure, timeout, and signal termination.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import FrameType
from typing import Any

from ralf.sandbox import AGENT_POLICY, SandboxPolicy

INTERRUPTION_SIGNALS = (signal.SIGINT, signal.SIGTERM)


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
    interrupted: bool = False

    def to_record(self) -> dict[str, str | int | bool | None]:
        """Return content-free metadata suitable for an operational record."""

        return {
            "outcome": self.outcome.value,
            "sandbox": "enabled" if self.sandboxed else "disabled_by_override",
            "returncode": self.returncode,
            "signal": self.signal,
            "force_killed": self.force_killed,
        }

    @property
    def ok(self) -> bool:
        return self.outcome is ProcessOutcome.SUCCESS


@dataclass(frozen=True, slots=True)
class CommandHarness:
    """Run a generic argument-array command through one process contract."""

    command: tuple[str, ...]
    environment_allowlist: tuple[str, ...] = ()
    timeout_seconds: float = 60 * 60
    termination_grace_seconds: float = 5.0
    bubblewrap_command: str = "bwrap"
    policy: SandboxPolicy = field(default=AGENT_POLICY)

    def _environment(self) -> dict[str, str]:
        names = {"PATH", *self.environment_allowlist}
        return {name: os.environ[name] for name in names if name in os.environ}

    @staticmethod
    def _signal_process_group(process: subprocess.Popen[str], signal_number: int) -> None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal_number)

    def _launch(
        self, worktree: Path, *, no_sandbox: bool
    ) -> tuple[tuple[str, ...], bool, str | None]:
        sandboxed = not no_sandbox
        if not sandboxed:
            return self.command, False, "sandbox disabled by explicit --no-sandbox override"
        arguments = self.policy.arguments(worktree, bubblewrap=self.bubblewrap_command)
        return (*arguments, *self.command), True, None

    def _collect(
        self, process: subprocess.Popen[str], stdin_data: str | None
    ) -> tuple[str, str, ProcessOutcome | None, bool, bool]:
        """Communicate with a started process, applying the timeout policy."""

        interrupted = [False]

        def handle(signal_number: int, _frame: FrameType | None) -> None:
            interrupted[0] = True
            self._signal_process_group(process, signal.SIGTERM)

        previous: dict[int, Any] = {}
        for signal_number in INTERRUPTION_SIGNALS:
            with contextlib.suppress(ValueError):
                previous[signal_number] = signal.signal(signal_number, handle)
        try:
            try:
                stdout, stderr = process.communicate(stdin_data, timeout=self.timeout_seconds)
            except subprocess.TimeoutExpired:
                self._signal_process_group(process, signal.SIGTERM)
                force_killed = False
                try:
                    stdout, stderr = process.communicate(timeout=self.termination_grace_seconds)
                except subprocess.TimeoutExpired:
                    self._signal_process_group(process, signal.SIGKILL)
                    force_killed = True
                    stdout, stderr = process.communicate()
                return stdout, stderr, ProcessOutcome.TIMEOUT, force_killed, interrupted[0]
        finally:
            for signal_number, handler in previous.items():
                signal.signal(signal_number, handler)
        return stdout, stderr, None, False, interrupted[0]

    def _run(self, stdin_data: str | None, *, worktree: Path, no_sandbox: bool) -> ProcessResult:
        worktree = worktree.resolve()
        launch_command, sandboxed, notice = self._launch(worktree, no_sandbox=no_sandbox)
        try:
            process = subprocess.Popen(
                launch_command,
                cwd=worktree,
                env=self._environment(),
                stdin=subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL,
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
        stdout, stderr, forced_outcome, force_killed, interrupted = self._collect(
            process, stdin_data
        )
        returncode = process.returncode
        if forced_outcome is not None:
            outcome = forced_outcome
        elif interrupted and returncode is not None and returncode < 0:
            outcome = ProcessOutcome.SIGNAL_TERMINATION
        elif returncode == 0:
            outcome = ProcessOutcome.SUCCESS
        elif returncode is not None and returncode < 0:
            outcome = ProcessOutcome.SIGNAL_TERMINATION
        else:
            outcome = ProcessOutcome.NONZERO_EXIT
        return ProcessResult(
            outcome=outcome,
            stdout=stdout,
            stderr=stderr,
            returncode=returncode,
            sandboxed=sandboxed,
            notice=notice,
            signal=-returncode if returncode is not None and returncode < 0 else None,
            force_killed=force_killed,
            interrupted=interrupted,
        )

    def run(self, prompt: str, *, worktree: Path, no_sandbox: bool = False) -> ProcessResult:
        """Run one fresh Harness process in its assigned worktree."""

        return self._run(prompt, worktree=worktree, no_sandbox=no_sandbox)

    def run_arguments(
        self,
        arguments: tuple[str, ...],
        *,
        worktree: Path,
        no_sandbox: bool = False,
    ) -> ProcessResult:
        """Run a verification command array without standard input."""

        verification = CommandHarness(
            command=arguments,
            environment_allowlist=self.environment_allowlist,
            timeout_seconds=self.timeout_seconds,
            termination_grace_seconds=self.termination_grace_seconds,
            bubblewrap_command=self.bubblewrap_command,
            policy=self.policy,
        )
        return verification._run(None, worktree=worktree, no_sandbox=no_sandbox)
