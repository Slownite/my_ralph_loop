"""Crash-safe, content-free local telemetry.

Structured records are append-only JSONL under an ignored XDG state directory.
They never contain prompts, diffs, environment values, absolute paths, credential
values, or raw argument arrays. Raw transcripts are stored separately with
restricted permissions and explicit bounds. The event sink stays backend-neutral.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

SENSITIVE_FIELDS = frozenset(
    {
        "prompt",
        "prompts",
        "diff",
        "diffs",
        "environment",
        "env",
        "arguments",
        "argv",
        "args",
        "command",
        "absolute_path",
        "path",
        "token",
        "secret",
        "credential",
        "password",
    }
)
_SCALAR = (str, int, bool, float)
_ABSOLUTE_PATH = re.compile(r"^(/|[A-Za-z]:[\\/])")


class TelemetryError(ValueError):
    """A structured record would violate the telemetry content contract."""


def _unsafe_reason(key: str, value: object) -> str | None:
    if key in SENSITIVE_FIELDS:
        return f'field "{key}" may not be recorded in structured telemetry'
    if isinstance(value, (list, tuple, dict, set, bytes)):
        return f'field "{key}" must be a scalar; raw argument arrays are excluded'
    if value is not None and not isinstance(value, _SCALAR):
        return f'field "{key}" must be a scalar'
    if isinstance(value, str) and _ABSOLUTE_PATH.match(value):
        return f'field "{key}" must not contain an absolute path'
    return None


def new_run_id() -> str:
    return uuid.uuid4().hex


def state_home() -> Path:
    configured = os.environ.get("XDG_STATE_HOME")
    base = Path(configured) if configured else Path.home() / ".local" / "state"
    return base / "ralf"


def repository_state_directory(repository_root: Path) -> Path:
    """Return the XDG state directory keyed by repository identity."""

    identity = uuid.uuid5(uuid.NAMESPACE_URL, str(repository_root.resolve())).hex[:12]
    return state_home() / "repositories" / identity


@dataclass(slots=True)
class Telemetry:
    """Append-only operational records and bounded local transcripts."""

    directory: Path
    max_runs: int = 100
    max_age_days: int = 30
    max_transcript_bytes: int = 1_048_576
    _path: Path = field(init=False)

    def __post_init__(self) -> None:
        self._path = self.directory / "runs.jsonl"

    @property
    def records_path(self) -> Path:
        return self._path

    def _append(self, payload: dict[str, object]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, sort_keys=True) + "\n"
        descriptor = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(descriptor, line.encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def record(self, event: str, **fields: object) -> dict[str, object]:
        """Append one safe structured record and return it."""

        if not event:
            raise TelemetryError("an event name is required")
        for key, value in fields.items():
            reason = _unsafe_reason(key, value)
            if reason is not None:
                raise TelemetryError(reason)
        payload: dict[str, object] = {
            "event": event,
            "time": time.time(),
            **fields,
        }
        self._append(payload)
        return payload

    def read_records(self) -> Iterator[dict[str, object]]:
        """Yield complete records, ignoring an interrupted trailing record."""

        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped or not line.endswith("\n"):
                    continue
                try:
                    value = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    yield value

    def incomplete_tail(self) -> bool:
        """Return whether the file ends with an interrupted, partial record."""

        if not self._path.exists():
            return False
        content = self._path.read_text(encoding="utf-8")
        if not content:
            return False
        return not content.endswith("\n")

    def transcript_path(self, run_id: str, attempt: int, stream: str) -> Path:
        return self.directory / "transcripts" / run_id / f"attempt-{attempt}-{stream}.txt"

    def write_transcript(self, run_id: str, attempt: int, stream: str, content: str) -> Path:
        """Store bounded raw output with restricted permissions, outside records."""

        path = self.transcript_path(run_id, attempt, stream)
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = content.encode("utf-8")[-self.max_transcript_bytes :]
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(descriptor, encoded)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return path

    def transcript_directory(self, run_id: str) -> Path:
        return self.directory / "transcripts" / run_id

    def cleanup(self, *, now: float | None = None) -> dict[str, int]:
        """Retain at most ``max_runs`` or ``max_age_days`` and record cleanup."""

        moment = time.time() if now is None else now
        transcripts = self.directory / "transcripts"
        removed_runs = 0
        removed_age = 0
        if transcripts.is_dir():
            entries = sorted(
                (entry for entry in transcripts.iterdir() if entry.is_dir()),
                key=lambda entry: entry.stat().st_mtime,
                reverse=True,
            )
            cutoff = moment - self.max_age_days * 24 * 60 * 60
            for index, entry in enumerate(entries):
                too_many = index >= self.max_runs
                too_old = entry.stat().st_mtime < cutoff
                if not (too_many or too_old):
                    continue
                _remove_tree(entry)
                if too_old:
                    removed_age += 1
                else:
                    removed_runs += 1
        summary = {"removed_runs": removed_runs, "removed_runs_age": removed_age}
        if removed_runs or removed_age:
            self.record(
                "telemetry_cleanup",
                removed_runs=removed_runs,
                removed_runs_age=removed_age,
            )
        return summary


def _remove_tree(path: Path) -> None:
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_file() or child.is_symlink():
            child.unlink(missing_ok=True)
        elif child.is_dir():
            child.rmdir()
    path.rmdir()
