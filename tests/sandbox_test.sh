#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/sandbox.sh"

pass=0
fail=0

assert_exit() {
  local expected="$1"
  local description="$2"
  shift 2
  if "$@" 2>/dev/null; then
    actual=0
  else
    actual=$?
  fi
  if [[ "$actual" -eq "$expected" ]]; then
    echo "  PASS: $description"
    pass=$((pass + 1))
  else
    echo "  FAIL: $description (expected exit $expected, got $actual)"
    fail=$((fail + 1))
  fi
}

echo "sandbox_run integration tests"

if [[ "$(uname)" != "Linux" ]] || ! command -v bwrap &>/dev/null; then
  echo "  SKIP: bwrap not available (macOS or bwrap not installed) — degraded mode only"
  echo ""
  echo "Results: 0 passed, 0 failed (skipped)"
  exit 0
fi

worktree=$(mktemp -d)
escape_file="/tmp/ralf-sandbox-escape-$$"
rm -f "$escape_file"

# Case 1: write inside worktree succeeds
assert_exit 0 "write inside worktree succeeds" \
  sandbox_run "$worktree" bash -c "touch /workspace/inside.txt"

# Case 2: write outside worktree is blocked
sandbox_run "$worktree" bash -c "touch $escape_file" 2>/dev/null || true
if [[ ! -f "$escape_file" ]]; then
  echo "  PASS: write outside worktree is blocked by bwrap"
  pass=$((pass + 1))
else
  echo "  FAIL: write outside worktree was NOT blocked — escape file exists on host"
  fail=$((fail + 1))
  rm -f "$escape_file"
fi

# Case 3: file written inside worktree is visible on host (worktree is bind-mounted)
sandbox_run "$worktree" bash -c "echo hello > /workspace/visible.txt" 2>/dev/null || true
if [[ -f "$worktree/visible.txt" ]]; then
  echo "  PASS: file written inside sandbox is visible on host via worktree"
  pass=$((pass + 1))
else
  echo "  FAIL: file written inside sandbox not visible on host"
  fail=$((fail + 1))
fi

rm -rf "$worktree"

echo ""
echo "Results: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
