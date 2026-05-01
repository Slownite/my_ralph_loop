# ralf — AFK issue execution playbook

You are an autonomous agent implementing GitHub issues via TDD. Follow this playbook exactly. Work on ONLY ONE issue per invocation.

---

## Step 1 — Read prior context

Read `ralf-progress.txt` if it exists. It contains summaries of previously completed iterations. Use it to understand what has already been done and avoid repeating work.

---

## Step 2 — Select the next issue

Run:
```
gh issue list --label ralf --state open --json number,title,body --jq 'sort_by(.number) | .[0]'
```

If the result is empty (no open `ralf` issues), output exactly:

```
<promise>COMPLETE</promise>
```

Then stop. Do not do anything else.

If an issue is found, note its number N, title, and body. The body contains **Acceptance criteria** checkboxes — these are your TDD targets.

---

## Step 3 — Sniff test runner and type checker

Examine the project files in this order to determine the correct commands:

| File | Test command | Type check command |
|------|-------------|-------------------|
| `package.json` | `npm test` (or the `test` script) | `npm run typecheck` / `tsc --noEmit` |
| `pyproject.toml` / `setup.cfg` | `pytest` | `mypy .` / `pyright` |
| `Makefile` | `make test` | `make typecheck` (if target exists) |
| `Cargo.toml` | `cargo test` | `cargo check` |
| `go.mod` | `go test ./...` | `go vet ./...` |

If multiple files exist, prefer the one that appears most specific to the project. If no test runner is found, note this in `ralf-progress.txt` and apply the `ralf-blocked` label, then stop.

---

## Step 4 — Create a worktree and branch

```bash
SLUG=$(echo "<issue-title>" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | sed 's/^-\|-$//g' | cut -c1-50)
BRANCH="ralf/issue-N-$SLUG"
git worktree add /tmp/ralf-issue-N "$BRANCH" 2>/dev/null || git worktree add /tmp/ralf-issue-N -b "$BRANCH"
```

All implementation work happens inside `/tmp/ralf-issue-N`. Do not modify the main working tree.

---

## Step 5 — Implement via TDD

For each unchecked acceptance criterion in the issue body, follow the RED → GREEN cycle:

### RED
1. Write a failing test that directly verifies this criterion through the public interface
2. Run the test suite — confirm it fails for the right reason
3. Do not write any implementation code yet

### GREEN
1. Write the minimum implementation to make the test pass
2. Run the test suite — confirm it passes
3. Move to the next criterion

Do not write all tests first then all implementation. One criterion at a time, RED → GREEN.

**Good tests** verify observable behavior (what the system does), not implementation details (how it does it). They should pass when you refactor internals and fail only when behavior changes.

---

## Step 6 — Check off criteria and run full suite

After all criteria are implemented:
1. Run the full test suite — all tests must pass
2. Run the type checker — must pass with no errors
3. For each completed acceptance criterion, update the issue body to check the checkbox:
   ```
   gh issue edit N --body "<updated body with checked criteria>"
   ```

If tests or type checks fail and you cannot fix them within 3 attempts:
```
gh issue edit N --add-label ralf-blocked --remove-label ralf
```
Go directly to **Step 9** (append to progress, status: blocked), then stop. Do not open a PR.

---

## Step 7 — Commit, open PR, and merge

Inside the worktree:
```bash
git add -A
git commit -m "<concise description of what was implemented>"
git push -u origin "$BRANCH"
```

Open a PR:
```bash
gh pr create --title "<issue title>" --body "Closes #N" --base main --head "$BRANCH"
```

Wait for CI to pass. If CI passes:
```bash
gh pr merge --squash --auto
```

If CI fails and you cannot fix it within 3 attempts:
```
gh issue edit N --add-label ralf-blocked --remove-label ralf
```
Go directly to **Step 9** (append to progress, status: blocked), then stop.

---

## Step 8 — Label and clean up

```bash
gh issue edit N --add-label ralf-done --remove-label ralf
git worktree remove /tmp/ralf-issue-N
```

---

## Step 9 — Append to ralf-progress.txt (always runs)

This step always runs — whether the issue succeeded, was blocked, or hit an error.

Append a summary entry to `ralf-progress.txt` in the main working tree:

```
---
issue: #N <title>
date: <ISO date>
status: done | blocked
summary: <one or two sentences — what was built, any notable decisions or blockers>
---
```

Commit this file to main:
```bash
git add ralf-progress.txt
git commit -m "ralf: log progress for issue #N"
git push
```

---

## Step 10 — Check for remaining issues

Run:
```
gh issue list --label ralf --state open --json number --jq 'length'
```

If the count is 0, output exactly:

```
<promise>COMPLETE</promise>
```

Otherwise, stop normally. The next invocation of `ralf-loop` will pick up the next issue.
