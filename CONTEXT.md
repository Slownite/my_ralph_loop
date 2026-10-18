# Ralf context

Ralf is a Python 3.11+ Linux orchestrator that turns a project-owned Issue Queue into integrated work while keeping readiness and integration decisions outside the coding agent. GitHub is the default Issue Source; `--local` selects the file-backed queue. [GLOSSARY.md](GLOSSARY.md) holds the canonical language; this document describes how the final system fits together.

## Actors and ownership

- **Ralf** owns Issue state, staging, commits, worktrees, verification, merges, optional pushes, recovery, and audit records.
- A **Harness** is an external coding agent reached through one process boundary. It edits files and runs commands for feedback, and it can never declare its own work Ready or Done.
- The **Target** is the project branch into which completed work is integrated. It is whatever branch `ralf-loop init` observed, not an assumed `main`.

## Runtime flow

1. `init` writes a deterministic configuration: target branch, fixed argument arrays for verification, one Harness profile, one issue per run, three attempts per issue, local auto-merge on, remote push off.
2. `validate` checks configuration and the active Issue Source before any mutation. GitHub selects unassigned Issues carrying the mapped `ready-for-agent` role; `--local` validates the configured Markdown queue.
3. `run` takes a `flock` in the Git directory, fetches an optional remote and accepts only a fast-forward target, then preflights the clean target tree and branch references. `--dry-run` performs the same preflight and prints one exact plan without mutating anything.
4. For each Pending Issue, Ralf claims it on GitHub or commits its local `in_progress` transition, creates the feature branch and an XDG-state worktree, and runs the Harness as a fresh process with the prompt on standard input.
5. Ralf runs the Guard and the configured verification commands through the sandboxed process boundary, reruns the Guard afterwards, revalidates repository, branch, worktree, and the eligible diff, and commits exactly the validated tree.
6. The Issue becomes `ready`. With auto-merge, `finalize` synchronizes the Target, reruns the whole Gate against the merge candidate, merges `--no-ff`, commits `done` separately, removes the worktree, and optionally pushes.

## Failure semantics

- Spawn failure, nonzero Harness exit, timeout, or signal is an **infrastructure failure**: Ralf preserves edits, branch, and worktree, leaves the Issue `in_progress`, stops, and does not consume an Attempt.
- A successful Harness with no eligible diff, a guard violation, or a verification failure consumes one Attempt and starts a fresh process with the final 32 KiB of diagnostics.
- Exhausting `max_attempts_per_issue` marks the Issue `blocked` and preserves its evidence. `retry` resumes the preserved identity with a fresh per-run allowance.
- `SIGINT` and `SIGTERM` stop the active child, record the interruption, preserve state, and exit non-zero.
- A merge conflict marks the Issue `blocked` and never rebases automatically; a push failure is an infrastructure failure that preserves all local successful work.

## Evidence

Workflow transitions are authoritative in the active Issue Source and Git history. GitHub recovery state is mirrored under the XDG state directory; local Issue transitions are committed. Structured JSONL records add run, issue, attempt, Harness, verification, Git, and transition metadata without prompts, diffs, environment values, absolute paths, credentials, or raw argument arrays. Bounded local transcripts hold raw output with restricted permissions.
