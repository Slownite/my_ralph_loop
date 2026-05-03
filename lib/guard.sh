#!/usr/bin/env bash
# Checks that no test files were net-deleted in a worktree.
# Usage: guard_test_deletion <worktree_path> <base_branch>
# Exits 1 if test files were removed.

guard_test_deletion() {
  local worktree="$1"
  local base="${2:-main}"
  local target="${3:-HEAD}"

  local deleted
  deleted=$(git -C "$worktree" diff "$base"..."$target" --name-only --diff-filter=D \
    | grep -E '(test_[^/]+\.(py|sh)$|[^/]+\.(test|spec)\.(ts|tsx|js|jsx)$|_test\.(go|rs)$)' \
    || true)

  if [[ -n "$deleted" ]]; then
    echo "guard: test files deleted:" >&2
    echo "$deleted" >&2
    return 1
  fi
}
