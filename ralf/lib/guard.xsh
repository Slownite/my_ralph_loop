"""Test-deletion guard.

Checks that the branch did not decrease the net test file count
relative to the base branch. Runs before the test suite."""

import pathlib as _pathlib

def _is_test_file(filepath):
    name = _pathlib.Path(filepath).name.lower()
    parts = _pathlib.Path(filepath).parts
    return ('test' in name or 'spec' in name or
            'tests' in parts or 'test' in parts or
            name.endswith('_test.go') or name.startswith('test_'))

def guard_test_deletion(worktree_path, base_branch='main'):
    added = 0
    deleted = 0

    output = $(git -C @(worktree_path) diff @(base_branch)...HEAD --name-status --diff-filter=ADR)

    for line in output.strip().split('\n'):
        if not line.strip():
            continue
        parts = line.split('\t')
        if len(parts) < 2:
            continue
        status, filepath = parts[0], parts[1]
        if not _is_test_file(filepath):
            continue
        if status == 'A':
            added += 1
        elif status == 'D':
            deleted += 1

    net = added - deleted
    if net < 0:
        return False, f'Test file count decreased by {-net} (+{added}/-{deleted})'
    return True, f'Guard passed (+{added}/-{deleted} net:{net})'
