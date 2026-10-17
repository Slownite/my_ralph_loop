"""Build Bubblewrap sandbox launch arguments.

Ralf runs agent and verification processes inside Bubblewrap with the least
privilege each operation requires and fails closed when isolation cannot start.
Isolation cannot prevent a networked Harness from transmitting source that the
Harness is able to read.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BUBBLEWRAP = "bwrap"


class SandboxUnavailable(RuntimeError):
    """The requested isolation cannot be established."""


@dataclass(frozen=True, slots=True)
class Mount:
    """One explicitly configured bind mount into the sandbox."""

    source: Path
    target: Path | None = None
    writable: bool = False

    @property
    def destination(self) -> Path:
        return self.target if self.target is not None else self.source


@dataclass(frozen=True, slots=True)
class SandboxPolicy:
    """The filesystem and network access one operation receives."""

    network: bool = True
    mounts: tuple[Mount, ...] = ()

    def arguments(self, worktree: Path, *, bubblewrap: str = DEFAULT_BUBBLEWRAP) -> list[str]:
        """Return a complete ``bwrap`` argument vector for one worktree."""

        worktree = worktree.resolve()
        arguments = [
            bubblewrap,
            "--die-with-parent",
            "--new-session",
            "--unshare-all",
        ]
        if self.network:
            arguments.append("--share-net")
        arguments += [
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
        ]
        # The worktree Git link stays read-only even though the worktree is writable.
        git_link = worktree / ".git"
        if git_link.exists() or git_link.is_symlink():
            arguments += ["--ro-bind", str(git_link), str(git_link)]
        for mount in self.mounts:
            if not mount.source.exists():
                continue
            flag = "--bind" if mount.writable else "--ro-bind"
            arguments += [flag, str(mount.source.resolve()), str(mount.destination)]
        arguments += ["--chdir", str(worktree), "--"]
        return arguments


AGENT_POLICY = SandboxPolicy(network=True)


def bubblewrap_available(bubblewrap: str = DEFAULT_BUBBLEWRAP) -> bool:
    return shutil.which(bubblewrap) is not None


def require_bubblewrap(bubblewrap: str = DEFAULT_BUBBLEWRAP) -> None:
    if not bubblewrap_available(bubblewrap):
        raise SandboxUnavailable(
            f'isolation executable "{bubblewrap}" was not found; install Bubblewrap '
            "or pass --no-sandbox explicitly"
        )
