"""Real Bubblewrap integration tests for the sandbox policy."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ralf.process import CommandHarness, ProcessOutcome
from ralf.sandbox import Mount, SandboxPolicy, bubblewrap_available

from .support import write_executable

pytestmark = pytest.mark.skipif(
    not bubblewrap_available(), reason="Bubblewrap is not available on this host"
)


def test_agent_policy_shares_network_but_verification_does_not() -> None:
    worktree = Path("/tmp")
    agent = SandboxPolicy(network=True).arguments(worktree)
    verification = SandboxPolicy(network=False).arguments(worktree)

    assert "--share-net" in agent
    assert "--share-net" not in verification
    assert "--unshare-all" in verification


def test_only_the_worktree_is_writable(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    outside = Path("/etc/ralf-sandbox-marker")
    executable = write_executable(
        worktree / "harness.py",
        f"""\
from pathlib import Path

Path("inside.txt").write_text("written")
try:
    Path({str(outside)!r}).write_text("escaped")
except OSError:
    print("outside read-only")
""",
    )

    result = CommandHarness((str(executable),)).run("prompt", worktree=worktree)

    assert result.outcome is ProcessOutcome.SUCCESS
    assert (worktree / "inside.txt").read_text() == "written"
    assert outside.exists() is False
    assert "outside read-only" in result.stdout


def test_read_only_mount_cannot_be_written(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    credentials = tmp_path / "credentials"
    credentials.mkdir()
    (credentials / "token").write_text("secret")
    executable = write_executable(
        worktree / "harness.py",
        f"""\
from pathlib import Path

target = Path({str(credentials / "token")!r})
print(target.read_text())
try:
    target.write_text("changed")
except OSError:
    print("mount read-only")
""",
    )
    policy = SandboxPolicy(mounts=(Mount(credentials),))

    result = CommandHarness((str(executable),), policy=policy).run("prompt", worktree=worktree)

    assert result.outcome is ProcessOutcome.SUCCESS
    assert "secret" in result.stdout
    assert "mount read-only" in result.stdout
    assert (credentials / "token").read_text() == "secret"


def test_verification_has_no_network(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    executable = write_executable(
        worktree / "harness.py",
        """\
import socket

try:
    socket.create_connection(("1.1.1.1", 53), timeout=2)
except OSError:
    print("no network")
else:
    print("network reachable")
""",
    )
    policy = SandboxPolicy(network=False)

    result = CommandHarness((str(executable),), policy=policy).run("prompt", worktree=worktree)

    assert result.outcome is ProcessOutcome.SUCCESS
    assert "no network" in result.stdout


def test_missing_bubblewrap_fails_closed(tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    executable = write_executable(
        tmp_path / "harness.py", f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
    )

    result = CommandHarness((str(executable),), bubblewrap_command="missing-bwrap").run(
        "prompt", worktree=tmp_path
    )

    assert result.outcome is ProcessOutcome.SPAWN_FAILURE
    assert result.sandboxed is True
    assert marker.exists() is False


def test_sandbox_documentation_states_the_threat_boundary() -> None:
    readme = Path(__file__).parents[1] / "README.md"
    text = readme.read_text().lower()
    assert "cannot prevent" in text or "threat" in text
    assert shutil.which("bwrap") is not None
