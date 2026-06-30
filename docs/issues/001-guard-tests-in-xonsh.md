---
status: done
---

# Issue 001 — Guard tests in xonsh

**Type:** AFK
**Blocked by:** None
**User stories covered:** N/A

## What to build

Port the test-deletion guard tests from the old bash suite (`tests/guard_test.sh`) to xonsh, testing `ralf/lib/guard.xsh`. The old tests verified that the guard correctly identifies test-file deletions on a feature branch relative to main. The xonsh port should test the same scenarios: no files deleted passes, test file deleted fails, non-test file deleted passes, test file added passes, multiple test files deleted fails.

This slice also establishes the xonsh test harness pattern (test runner, assertion helpers, temp git repo setup) that subsequent test issues will follow.

## Acceptance criteria

- [x] `ralf/tests/test_guard.xsh` exists with the same 5 test cases as the old `tests/guard_test.sh`
- [x] Each test creates a disposable git repo, makes a branch with a known diff, and asserts the guard's return value
- [x] `xonsh ralf/tests/test_guard.xsh` passes (exit 0)
- [ ] The test file is listed in the flake's devShell check or can be run by the user manually
- [x] Old `tests/guard_test.sh` is no longer needed (already removed from git)

## Blocked by

None - can start immediately
