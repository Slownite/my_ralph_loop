"""Bubblewrap sandbox wrapper.

Mounts worktree read-write, opencode config read-only, allows network.
Degrades gracefully when bwrap is unavailable (macOS, CI, etc.)."""

import os as _os
import pathlib as _pathlib
import shutil as _shutil
import subprocess as _subprocess

_HAS_BWRAP = _shutil.which('bwrap') is not None and _os.uname().sysname == 'Linux'

def sandbox_available():
    return _HAS_BWRAP

def sandbox_run(worktree_path, command_list):
    """Run command_list inside sandbox. Returns (rc, stdout, stderr)."""
    if not _HAS_BWRAP:
        proc = _subprocess.run(command_list, capture_output=True, text=True,
                               cwd=worktree_path)
        return proc.returncode, proc.stdout, proc.stderr

    home = _pathlib.Path.home()
    opencode_config = home / '.config' / 'opencode'
    opencode_data = home / '.local' / 'share' / 'opencode'

    args = [
        'bwrap',
        '--unshare-all',
        '--share-net',
        '--new-session',
        '--die-with-parent',
        '--ro-bind', '/nix', '/nix',
        '--ro-bind', '/usr', '/usr',
        '--proc', '/proc',
        '--dev', '/dev',
        '--tmpfs', '/tmp',
        '--bind', str(worktree_path), '/workspace',
        '--ro-bind', str(opencode_config), str(opencode_config),
        '--ro-bind', str(opencode_data), str(opencode_data),
        '--chdir', '/workspace',
        '--set-env', 'HOME', str(home),
    ] + ['--'] + command_list

    proc = _subprocess.run(args, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr
