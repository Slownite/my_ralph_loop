# ralf — AFK issue execution playbook

Work on ONLY ONE issue per invocation. The issue number, title, and body are provided above this playbook.

> **BLOCKED protocol:** Signal failure and stop. ralf will retry.

---

## Step 1 — Read prior context

Read `ralf-progress.txt` if it exists to understand what has already been done.

---

## Step 2 — Create a worktree and branch

Create branch `ralf/issue-N-<slug>` (slug = title lowercased, non-alphanumeric → hyphens, max 50 chars). Add a git worktree at `/tmp/ralf-issue-N`. All work happens there — do not modify the main working tree.

---

## Step 3 — Implement via TDD

For each unchecked acceptance criterion: write a failing test (RED), confirm it fails, then write the minimum implementation to pass (GREEN). One criterion at a time. Tests must verify observable behavior, not implementation details.

---

## Step 4 — Commit to branch

After all criteria are implemented, check off each completed criterion in the issue body by editing the issue file. Then commit all changes to the branch:

```bash
git add -A
git commit -m "<concise description of what was implemented>"
git push -u origin HEAD
```

Signal done — ralf will run the verification gate and merge.
