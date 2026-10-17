"""Data-driven Harness profiles over the shared command process boundary.

Built-in profiles are data consumed by the common command Harness rather than
separate orchestration adapters. A custom argument-array profile remains the
escape hatch. T3 Code is excluded from v1 because it is an app-owned remote
orchestrator, not a sandboxable headless child CLI.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

BUILTIN_PROFILES = ("codex", "omp", "opencode")
CUSTOM_PROFILE = "custom"
KNOWN_PROFILES = (*BUILTIN_PROFILES, CUSTOM_PROFILE)


class HarnessConfigurationError(ValueError):
    """A Harness profile cannot be resolved from configuration."""


@dataclass(frozen=True, slots=True)
class BuiltinProfile:
    """The documented defaults and access one built-in Harness requires."""

    command: tuple[str, ...]
    model_style: str
    read_only_mounts: tuple[str, ...] = ()
    writable_state: tuple[str, ...] = ()
    environment: tuple[str, ...] = ()


BUILTINS: dict[str, BuiltinProfile] = {
    "codex": BuiltinProfile(
        command=(
            "codex",
            "exec",
            "--json",
            "--dangerously-bypass-approvals-and-sandbox",
            "-",
        ),
        model_style="codex",
        read_only_mounts=("~/.codex",),
        writable_state=("~/.codex/sessions",),
        environment=("HOME",),
    ),
    "omp": BuiltinProfile(
        command=("omp", "-p", "--mode=json", "--approval-mode=yolo", "--max-time=3600"),
        model_style="omp",
        read_only_mounts=("~/.config/omp", "~/.omp"),
        environment=("HOME",),
    ),
    "opencode": BuiltinProfile(
        command=("opencode", "run", "--standalone", "--format=json", "--auto"),
        model_style="opencode",
        read_only_mounts=("~/.config/opencode", "~/.local/share/opencode"),
        environment=("HOME",),
    ),
}


def apply_model(style: str, command: tuple[str, ...], model: str) -> tuple[str, ...]:
    """Translate an opaque model value only where the selected profile supports it."""

    if style == "codex":
        return (command[0], "--model", model, *command[1:])
    if style == "omp":
        return (*command, f"--model={model}")
    if style == "opencode":
        return (*command, "--model", model)
    return command


@dataclass(frozen=True, slots=True)
class HarnessSpec:
    """A resolved Harness ready to run through the command process boundary."""

    profile: str
    command: tuple[str, ...]
    environment_allowlist: tuple[str, ...]
    read_only_mounts: tuple[Path, ...]
    writable_state: tuple[Path, ...]
    model: str | None = None

    @property
    def executable(self) -> str:
        return self.command[0]


def _expand(paths: tuple[str, ...]) -> tuple[Path, ...]:
    return tuple(Path(path).expanduser() for path in paths)


def resolve_harness(harness: Mapping[str, object]) -> HarnessSpec:
    """Resolve version-agnostic Harness configuration into an executable spec."""

    profile = harness.get("profile")
    if not isinstance(profile, str) or profile not in KNOWN_PROFILES:
        raise HarnessConfigurationError(f'harness profile "{profile}" is not supported')

    configured_command = harness.get("command")
    model_value = harness.get("model")
    model = model_value if isinstance(model_value, str) else None
    command_parts: list[object] = (
        cast(list[object], configured_command) if isinstance(configured_command, list) else []
    )

    if profile == CUSTOM_PROFILE:
        if not command_parts:
            raise HarnessConfigurationError("custom Harness requires a non-empty command array")
        command = tuple(str(part) for part in command_parts)
        return HarnessSpec(
            profile=profile,
            command=command,
            environment_allowlist=("HOME",),
            read_only_mounts=(),
            writable_state=(),
            model=model,
        )

    builtin = BUILTINS[profile]
    base = tuple(str(part) for part in command_parts) if command_parts else builtin.command
    command = apply_model(builtin.model_style, base, model) if model is not None else base
    return HarnessSpec(
        profile=profile,
        command=command,
        environment_allowlist=builtin.environment,
        read_only_mounts=_expand(builtin.read_only_mounts),
        writable_state=_expand(builtin.writable_state),
        model=model,
    )


def probe_executable(spec: HarnessSpec) -> dict[str, str | None]:
    """Capture the executable name and reported version for diagnostics only."""

    resolved = shutil.which(spec.executable)
    version: str | None = None
    if resolved is not None:
        try:
            result = subprocess.run(
                [resolved, "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            version = None
        else:
            lines = (result.stdout or result.stderr).strip().splitlines()
            version = lines[0] if lines else None
    return {"executable": spec.executable, "version": version}
