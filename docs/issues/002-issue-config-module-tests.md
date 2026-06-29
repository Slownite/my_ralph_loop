---
status: pending
---

# Issue 002 — Issue + config module tests

**Type:** AFK
**Blocked by:** 001
**User stories covered:** N/A

## What to build

Write xonsh tests for `ralf/lib/issues.xsh` (frontmatter reading, writing, init, number extraction, slugify) and `ralf/lib/config.xsh` (ralf.toml read/write, generate, defaults, missing file handling). Each module's tests follow the test harness pattern established in issue 001: create temp files, call the module functions, assert the result.

## Acceptance criteria

- [ ] `ralf/tests/test_issues.xsh` tests `issues.read_issue`, `write_issue`, `add_frontmatter_if_missing`, `set_status`, `extract_number`, `extract_title`, `slugify`
- [ ] `ralf/tests/test_config.xsh` tests `config.read_config` (with existing file, missing file, partial file), `write_config`, `generate_default`
- [ ] All tests pass (exit 0) when run with `xonsh ralf/tests/*.xsh`
- [ ] Tests cover edge cases: empty files, already-frontmattered files, files with only frontmatter, ralf.toml with override commands section

## Blocked by

- Issue 001 — Guard tests in xonsh (depends on test harness pattern)
