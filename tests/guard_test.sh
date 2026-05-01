#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/guard.sh"

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

# Creates a git repo with a base commit, then a second commit applying a diff.
# Usage: make_repo <dir> [file_to_add] [file_to_delete]
make_repo() {
  local dir="$1"
  local add_file="${2:-}"
  local del_file="${3:-}"

  git init -q "$dir"
  git -C "$dir" config user.email "test@test.com"
  git -C "$dir" config user.name "Test"

  # Base commit with some files
  mkdir -p "$dir/src" "$dir/tests"
  echo "x" > "$dir/src/app.py"
  echo "x" > "$dir/tests/test_app.py"
  echo "x" > "$dir/tests/test_util.py"
  git -C "$dir" add .
  git -C "$dir" commit -q -m "base"

  # Branch with changes
  git -C "$dir" checkout -q -b feature

  if [[ -n "$del_file" ]]; then
    git -C "$dir" rm -q "$del_file"
  fi
  if [[ -n "$add_file" ]]; then
    echo "x" > "$dir/$add_file"
    git -C "$dir" add "$dir/$add_file"
  fi

  if git -C "$dir" diff --cached --quiet && git -C "$dir" diff --quiet; then
    # nothing staged — make a no-op commit
    echo "noop" > "$dir/src/noop"
    git -C "$dir" add .
  fi

  git -C "$dir" commit -q -m "feature"
}

echo "guard_test_deletion tests"

# Case 1: no files deleted → pass
dir=$(mktemp -d)
make_repo "$dir"
assert_exit 0 "no files deleted → pass" guard_test_deletion "$dir" main
rm -rf "$dir"

# Case 2: test file deleted → fail
dir=$(mktemp -d)
make_repo "$dir" "" "tests/test_app.py"
assert_exit 1 "test file deleted (test_app.py) → fail" guard_test_deletion "$dir" main
rm -rf "$dir"

# Case 3: non-test file deleted → pass
dir=$(mktemp -d)
make_repo "$dir" "" "src/app.py"
assert_exit 0 "non-test file deleted (src/app.py) → pass" guard_test_deletion "$dir" main
rm -rf "$dir"

# Case 4: test file added (not deleted) → pass
dir=$(mktemp -d)
make_repo "$dir" "tests/test_new.py"
assert_exit 0 "test file added → pass" guard_test_deletion "$dir" main
rm -rf "$dir"

# Case 5: multiple test files deleted → fail
dir=$(mktemp -d)
make_repo "$dir" "" "tests/test_app.py"
# delete second test file in same branch
git -C "$dir" rm -q "tests/test_util.py"
git -C "$dir" commit -q -m "delete more tests"
assert_exit 1 "multiple test files deleted → fail" guard_test_deletion "$dir" main
rm -rf "$dir"

echo ""
echo "Results: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
