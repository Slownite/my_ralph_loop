# ralf-once — Human-in-the-loop mode

## HITL checkpoints — you MUST pause and wait for approval before proceeding

**Checkpoint 1 — Plan**
Before writing any code or tests, present:
- Which acceptance criteria map to which test cases
- Which modules/files you will create or modify
- The branch name you will use (ralf/issue-N-<slug>)
Then output:
  [ralf-once] Checkpoint 1: Plan ready. Type 'approve' to continue or describe changes.
Wait for the user to type 'approve' before proceeding.

**Checkpoint 2 — RED**
After writing the failing tests (before any implementation), show:
- The test file(s) with all failing tests
- The test runner output confirming they fail
Then output:
  [ralf-once] Checkpoint 2: Tests written (RED). Type 'approve' to continue or describe changes.
Wait for the user to type 'approve' before proceeding.

**Checkpoint 3 — GREEN**
After implementation passes all tests, show:
- `git diff` of all changed files
- The test runner output confirming they pass
- The type checker output confirming it passes
- The linter output confirming it passes (if detected)
Then output:
  [ralf-once] Checkpoint 3: Implementation ready (GREEN). Type 'approve' to open PR.
Wait for the user to type 'approve' before opening a PR.

## Playbook

After all three checkpoints are approved, follow the ralf playbook below exactly.
Use branch naming: ralf/issue-N-<slugified-title>
Do NOT auto-merge — open the PR and stop. The human will merge.

---

# ralf — AFK issue execution playbook

Work on ONLY ONE issue per invocation. The issue number, title, and body are provided above this playbook.

> **BLOCKED protocol:** `gh issue edit N --add-label ralf-blocked --remove-label ralf` → go to **Step 8** (status: blocked), stop.

---

## Step 1 — Read prior context

Read `ralf-progress.txt` if it exists to understand what has already been done.

---

## Step 2 — Detect commands

Examine project files to determine commands. Skip lint silently if the linter or its runner is absent; note it in `ralf-progress.txt`. If no test runner is found, apply `ralf-blocked` and go to **Step 8**.

| File | Test | Type check | Lint |
|------|------|------------|------|
| `package.json` | `npm test` | `tsc --noEmit` | `npm run lint` (if script exists) |
| `pyproject.toml` / `setup.cfg` | `pytest` | `mypy .` / `pyright` | `ruff check .` |
| `Makefile` | `make test` | `make typecheck` (if target exists) | `make lint` (if target exists) |
| `Cargo.toml` | `cargo test` | `cargo check` | `cargo clippy` |
| `go.mod` | `go test ./...` | `go vet ./...` | `golangci-lint run` (if installed) |

---

## Step 3 — Create a worktree and branch

Create branch `ralf/issue-N-<slug>` (slug = title lowercased, non-alphanumeric → hyphens, max 50 chars). Add a git worktree at `/tmp/ralf-issue-N`. All work happens there — do not modify the main working tree.

---

## Step 4 — Implement via TDD

For each unchecked acceptance criterion: write a failing test (RED), confirm it fails, then write the minimum implementation to pass (GREEN). One criterion at a time. Tests must verify observable behavior, not implementation details.

---

## Step 5 — Verify all checks

After all criteria are implemented, run in order:
1. Full test suite
2. Type checker
3. Linter (if detected)

All must pass — → **BLOCKED** (do not open a PR) if any fails after 3 attempts.

Then check off each completed criterion in the issue body:
```bash
gh issue edit N --body "<updated body with checked criteria>"
```

---

## Step 6 — Commit and open PR

```bash
git add -A
git commit -m "<concise description>"
git push -u origin HEAD
gh pr create --title "<issue title>" --body "Closes #N" --base main --head "$BRANCH"
```

Output the PR URL and stop. Do not merge — the reviewer will merge.

---

## Step 7 — Label and clean up

```bash
gh issue edit N --add-label ralf-review --remove-label ralf
git worktree remove /tmp/ralf-issue-N
```

---

## Step 8 — Append to ralf-progress.txt (always runs)

Append to `ralf-progress.txt` in the main working tree:

```
---
issue: #N <title>
date: <ISO date>
status: done | blocked
summary: <one or two sentences>
---
```

Commit to main:
```bash
git add ralf-progress.txt
git commit -m "ralf: log progress for issue #N"
git push
```
