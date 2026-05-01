# ralf

AFK issue automation for Claude Code. Give it a backlog of GitHub issues, go make coffee, come back to merged PRs.

## What it does

`ralf-loop` picks GitHub issues labelled `ralf`, implements each one via TDD using `claude -p`, opens a PR, and auto-merges when tests and type checks pass. It loops up to N times, stopping early when the queue is empty.

`ralf-once` does the same thing interactively — it pauses at three checkpoints (plan, RED, GREEN) so you can review before anything is committed.

Both tools are project-agnostic: they sniff the test runner and type checker from your project files (`package.json`, `pyproject.toml`, `Makefile`, etc.) and work in any repo.

## Prerequisites

- [Nix](https://nixos.org/download) with flakes enabled
- [Claude Code](https://claude.ai/code) installed and authenticated
- [gh CLI](https://cli.github.com) authenticated (`gh auth login`)

## Installation

```bash
nix profile install github:Slownite/my_ralph_loop
```

This puts `ralf-loop` and `ralf-once` on your PATH with all dependencies pinned (gh, claude, git, bubblewrap).

To update:

```bash
nix profile upgrade my_ralph_loop
```

## Typical workflow

### 1. Write a PRD

In your project, use the `/to-prd` Claude Code skill to turn a conversation into a structured PRD issue on GitHub.

### 2. Break it into issues

Use `/to-issues` to slice the PRD into independently-implementable sub-issues. Each issue gets:
- A **What to build** section
- **Acceptance criteria** checkboxes — these become the TDD targets

### 3. Triage and label

Review the issues. For each one you want ralf to handle autonomously, apply the `ralf` label:

```bash
gh issue edit 42 --add-label ralf
```

> Only label issues with clear acceptance criteria. Vague issues will stall.

### 4a. Run unattended (AFK)

From your project directory:

```bash
ralf-loop 10
```

Processes up to 10 `ralf`-labelled issues sequentially. Each iteration:
1. Picks the lowest-numbered open `ralf` issue
2. Runs `claude -p` inside a sandboxed worktree
3. Implements via TDD (RED → GREEN per acceptance criterion)
4. Opens a PR and auto-merges if tests + type checks pass
5. Labels the issue `ralf-done` and logs to `ralf-progress.txt`
6. Outputs `<promise>COMPLETE</promise>` when the queue is empty

If anything goes wrong (tests won't pass, type errors, stuck), the issue is labelled `ralf-blocked` and the loop stops.

### 4b. Run interactively (HITL)

```bash
ralf-once 42
```

Opens an interactive Claude Code session for issue #42. Claude pauses at three checkpoints:

| Checkpoint | What you see | What to type |
|------------|-------------|--------------|
| **Plan** | Which tests will be written, which files touched, branch name | `approve` |
| **RED** | Failing test files + test runner output | `approve` |
| **GREEN** | Full diff + passing tests + type check output | `approve` |

After the third approval, Claude opens a PR. It does **not** auto-merge — you merge manually.

Without an argument, `ralf-once` lists open `ralf` issues for you to pick from:

```bash
ralf-once
# Open ralf issues:
#   #42  add user authentication
#   #43  implement rate limiting
# Issue number to work:
```

## Labels

| Label | Meaning |
|-------|---------|
| `ralf` | Ready for automation — apply this to queue an issue |
| `ralf-done` | Completed and merged by ralf |
| `ralf-blocked` | ralf got stuck — needs human review |

## Sandboxing

On Linux, `ralf-loop` runs `claude` inside a [bubblewrap](https://github.com/containers/bubblewrap) sandbox:
- The project worktree is mounted read-write at `/workspace`
- `~/.claude` (skills, settings) is mounted read-only
- Everything else is either read-only or unavailable

On macOS, the sandbox is skipped (bubblewrap is Linux-only). The test-deletion guard still runs from outside the sandbox as a safety net.

The test-deletion guard runs after every iteration. If Claude deleted test files net-negative on the feature branch, the loop stops and labels the issue `ralf-blocked`.

### Claude Code permissions

The repo ships `.claude/settings.json` with pre-authorized permission rules so the ralf agent never hits an interactive prompt for the commands it needs:

| Rule | Covers |
|------|--------|
| `Bash(git worktree *)` | Worktree creation |
| `Bash(git checkout *)` | Branch creation and switching |
| `Bash(git push*)` | Pushing branches |
| `Bash(git commit *)` | Committing changes |
| `Bash(gh pr *)` | Opening and merging PRs |
| `Bash(gh issue *)` | Editing issue labels |
| `Bash(mypy *)` | Type checking |

If you add a new tool or command to the TDD playbook that requires a permission, add a matching rule to `.claude/settings.json`.

## `ralf-progress.txt`

After each issue, ralf appends a summary entry to `ralf-progress.txt` in your project root:

```
---
issue: #42 add user authentication
date: 2026-05-01
status: done
summary: Implemented JWT auth with refresh tokens. Added 12 tests covering happy path and expiry edge cases.
---
```

This file is committed to your repo and read by the next iteration so Claude has context on what was already done.

## Repository layout

```
bin/
  ralf-loop          # AFK loop script
  ralf-once          # HITL interactive script
lib/
  sandbox.sh         # bwrap wrapper (Linux) / degraded no-op (macOS)
  guard.sh           # test-deletion guard
prompts/
  ralf-issue.md      # TDD playbook injected into every claude -p call
tests/
  guard_test.sh      # unit tests for lib/guard.sh
  sandbox_test.sh    # integration tests for lib/sandbox.sh (NixOS only)
flake.nix            # Nix package definitions
```

## Running the tests

```bash
nix develop
bash tests/guard_test.sh
bash tests/sandbox_test.sh   # NixOS only, skipped on macOS
```

## Contributing

1. Fork and clone the repo
2. Enter the dev shell: `nix develop`
3. Make your changes
4. Run the tests: `bash tests/guard_test.sh`
5. Open a PR

### Adding support for a new test runner

Edit `prompts/ralf-issue.md` — the sniffing table in Step 3 maps project files to test and type check commands. Add a row for the new runner.

### macOS sandbox parity

The macOS sandbox (`sandbox-exec`) is tracked as future work. If you want to implement it, `lib/sandbox.sh` is where the platform branch lives. The Linux bwrap path is the reference implementation.

### Editing the TDD playbook

`prompts/ralf-issue.md` is the instruction set Claude follows for every issue. Changes here affect all future `ralf-loop` and `ralf-once` runs. Test any changes against a real issue before merging.

## Roadmap

- [ ] macOS sandbox parity via `sandbox-exec`
- [ ] Parallel issue processing (`ralf-parallel`)
- [ ] Notification on completion (Slack, ntfy)
- [ ] Support for issue trackers beyond GitHub
