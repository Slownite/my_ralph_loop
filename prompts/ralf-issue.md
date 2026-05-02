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

## Step 6 — Commit, open PR, and merge

```bash
git add -A
git commit -m "<concise description>"
git push -u origin HEAD
gh pr create --title "<issue title>" --body "Closes #N" --base main --head "$BRANCH"
```

Wait for CI. If it passes: `gh pr merge --squash --auto`. → **BLOCKED** if CI fails after 3 attempts.

---

## Step 7 — Label and clean up

```bash
gh issue edit N --add-label ralf-done --remove-label ralf
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
