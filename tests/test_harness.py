"""Harness profile tests using fake executables named like each built-in."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ralf.harness import HarnessConfigurationError, HarnessSpec, resolve_harness
from ralf.process import CommandHarness, ProcessOutcome

from .support import write_executable

RECORDER = """\
import json
import os
import sys
from pathlib import Path

Path("invocation.json").write_text(
    json.dumps(
        {
            "argv": sys.argv[1:],
            "stdin": sys.stdin.read(),
            "cwd": Path.cwd().name,
            "sees_secret": "RALF_PROFILE_SECRET" in os.environ,
        }
    )
)
"""


def _resolve(profile: str, **overrides: object) -> HarnessSpec:
    harness: dict[str, object] = {"profile": profile}
    harness.update(overrides)
    return resolve_harness(harness)


def test_builtin_profiles_expand_to_documented_argument_shapes() -> None:
    assert _resolve("codex").command == (
        "codex",
        "exec",
        "--json",
        "--dangerously-bypass-approvals-and-sandbox",
        "-",
    )
    assert _resolve("omp").command == (
        "omp",
        "-p",
        "--mode=json",
        "--approval-mode=yolo",
        "--max-time=3600",
    )
    assert _resolve("opencode").command == (
        "opencode",
        "run",
        "--standalone",
        "--format=json",
        "--auto",
    )


def test_model_value_is_translated_per_profile() -> None:
    assert _resolve("codex", model="vendor/model").command[:3] == (
        "codex",
        "--model",
        "vendor/model",
    )
    assert _resolve("omp", model="opaque").command[-1] == "--model=opaque"
    assert _resolve("opencode", model="a/b").command[-2:] == ("--model", "a/b")


def test_custom_profile_keeps_the_argument_array_verbatim() -> None:
    spec = _resolve("custom", command=["agent", "--headless", "$(not-a-shell)"])
    assert spec.command == ("agent", "--headless", "$(not-a-shell)")


def test_unknown_profile_is_rejected() -> None:
    with pytest.raises(HarnessConfigurationError):
        _resolve("proprietary-event-stream")


@pytest.mark.parametrize("name", ["codex", "omp", "opencode"])
def test_fake_builtin_executables_receive_arguments_stdin_and_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    worktree = tmp_path / "assigned-worktree"
    worktree.mkdir()
    write_executable(tmp_path / "bin" / name, RECORDER)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("RALF_PROFILE_SECRET", "must-not-leak")

    spec = resolve_harness({"profile": name, "model": "opaque-model"})
    result = CommandHarness(
        spec.command,
        environment_allowlist=("PATH",),
        timeout_seconds=30,
    ).run("the prompt", worktree=worktree, no_sandbox=True)

    assert result.outcome is ProcessOutcome.SUCCESS
    invocation = json.loads((worktree / "invocation.json").read_text())
    assert invocation["stdin"] == "the prompt"
    assert invocation["cwd"] == "assigned-worktree"
    assert any("opaque-model" in argument for argument in invocation["argv"])
    assert invocation["sees_secret"] is False
