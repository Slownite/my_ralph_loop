"""A typed view over validated configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from ralf.sandbox import Mount


def _table(config: Mapping[str, object], key: str) -> dict[str, object]:
    value = config.get(key)
    if isinstance(value, dict):
        return cast(dict[str, object], value)
    return {}


def _string(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _integer(value: object, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _boolean(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _arguments(value: object) -> tuple[str, ...] | None:
    if isinstance(value, list):
        parts = cast(list[object], value)
        if parts and all(isinstance(part, str) for part in parts):
            return tuple(str(part) for part in parts)
    return None


def _strings(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(part) for part in cast(list[object], value) if isinstance(part, str))
    return ()


@dataclass(frozen=True, slots=True)
class Settings:
    """Configuration values the workflow may rely on without re-checking types."""

    target_branch: str
    issue_directory: str
    harness: Mapping[str, object]
    max_issues: int
    max_attempts_per_issue: int
    attempt_timeout_seconds: float
    verification_commands: tuple[tuple[str, tuple[str, ...]], ...]
    auto_merge: bool
    push: bool
    remote: str | None
    verification_network: bool
    environment_allowlist: tuple[str, ...]
    extra_mounts: tuple[Mount, ...]
    allowed_test_deletions: tuple[str, ...]
    max_runs: int
    max_age_days: int

    @classmethod
    def from_config(cls, config: Mapping[str, object]) -> Settings:
        harness = _table(config, "harness")
        run = _table(config, "run")
        commands = _table(config, "commands")
        merge = _table(config, "merge")
        sandbox = _table(config, "sandbox")
        telemetry = _table(config, "telemetry")
        guards = _table(config, "guards")

        verification: list[tuple[str, tuple[str, ...]]] = []
        for name in ("test", "typecheck", "lint"):
            arguments = _arguments(commands.get(name))
            if arguments is not None:
                verification.append((name, arguments))
        custom = _table(commands, "custom")
        for name in sorted(custom):
            arguments = _arguments(custom[name])
            if arguments is not None:
                verification.append((f"custom.{name}", arguments))

        mounts: list[Mount] = []
        raw_mounts = sandbox.get("mounts")
        if isinstance(raw_mounts, list):
            for raw in cast(list[object], raw_mounts):
                if not isinstance(raw, dict):
                    continue
                entry = cast(dict[str, object], raw)
                source = entry.get("source")
                if not isinstance(source, str) or not source:
                    continue
                target_value = entry.get("target")
                target = target_value if isinstance(target_value, str) and target_value else None
                mounts.append(
                    Mount(
                        source=Path(source).expanduser(),
                        target=Path(target).expanduser() if target else None,
                        writable=_boolean(entry.get("writable"), False),
                    )
                )

        return cls(
            target_branch=_string(config.get("target_branch")),
            issue_directory=_string(config.get("issue_directory"), "docs/issues"),
            harness=harness,
            max_issues=_integer(run.get("max_issues"), 1),
            max_attempts_per_issue=_integer(run.get("max_attempts_per_issue"), 3),
            attempt_timeout_seconds=float(_integer(run.get("attempt_timeout_seconds"), 3600)),
            verification_commands=tuple(verification),
            auto_merge=_boolean(merge.get("auto"), True),
            push=_boolean(merge.get("push"), False),
            remote=(_string(merge.get("remote")) or None),
            verification_network=_boolean(sandbox.get("verification_network"), False),
            environment_allowlist=_strings(sandbox.get("environment_allowlist")),
            extra_mounts=tuple(mounts),
            allowed_test_deletions=_strings(guards.get("allowed_test_deletions")),
            max_runs=_integer(telemetry.get("max_runs"), 100),
            max_age_days=_integer(telemetry.get("max_age_days"), 30),
        )
