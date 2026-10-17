# Ralf

Ralf is a Python 3.11+ Linux application that coordinates unattended implementation of a project-owned issue queue. It owns workflow state, Git mutations, sandboxing, verification, commits, merges, recovery, and audit records so the coding Harness cannot declare its own work Ready or Done.

Canonical domain language lives in [GLOSSARY.md](GLOSSARY.md). Hard-to-reverse decisions live in [docs/adr/](docs/adr/). The former Xonsh implementation and its `CONTEXT.md` vocabulary are gone; the Python package is the only supported implementation.

## Prerequisites

- Linux
- Python 3.11 or newer
- Git
- [Bubblewrap](https://github.com/containers/bubblewrap) (`bwrap`) for isolation, unless a run explicitly passes `--no-sandbox`

## Install

Install from a checkout or a Git URL. Ralf is not published to PyPI.

```bash
uv tool install .
uv tool install git+https://github.com/Slownite/my_ralph_loop.git
```

For development:

```bash
uv sync
uv run ralf-loop validate
uv run pytest
uv run pyright
uv run ruff check src tests
```

## Commands

A bare `ralf-loop` is exactly `ralf-loop run`.

| Command | Purpose |
|---------|---------|
| `ralf-loop init` | Write a complete, deterministic `ralf.toml` from the current branch, detected project commands, and one selected Harness profile |
| `ralf-loop validate [--json]` | Validate configuration and the whole issue queue before any mutation |
| `ralf-loop run [--dry-run]` | Process pending issues in order, optionally merging successful work |
| `ralf-loop status [--json]` | Report pending, in-progress, ready, blocked, and done issues plus preserved worktrees |
| `ralf-loop finalize <issue>` | Recheck a ready issue against the target and merge it |
| `ralf-loop retry <issue>` | Resume a blocked issue from its preserved edits with a fresh per-run allowance |

Run options: `--no-sandbox`, `--max-issues N`, `--no-auto-merge`, `--push`, `--remote NAME`.

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | The requested operation completed |
| `1` | A workflow error that is not otherwise classified |
| `2` | Configuration, issue-queue, or preflight validation failed |
| `3` | Work became `blocked` and needs a deliberate retry |
| `4` | Infrastructure failure; local work was preserved |
| `130` | Interrupted by `SIGINT` or `SIGTERM`; local work was preserved |

`validate --json` always prints a boolean `valid` field and an `errors` array whose entries have stable `code`, `message`, and `path` fields. `status --json` prints the same state the human output shows.

## Configuration

`ralf-loop init` records the currently checked-out branch as `target_branch`, detects project verification commands, and selects one Harness. Every required choice has a noninteractive flag; interactive prompts appear only on a TTY. When `ralf.toml` already exists, `init` preserves it and writes `ralf.toml.proposed`.

```toml
config_version = 1
target_branch = "main"
issue_directory = "docs/issues"

[harness]
profile = "codex"          # codex, omp, opencode, or custom
# command = ["agent", "--flag"]   # required for the custom profile
# model = "opaque-provider-model"

[run]
max_issues = 1
max_attempts_per_issue = 3
attempt_timeout_seconds = 3600

[commands]
test = ["pytest"]
typecheck = ["pyright"]
lint = ["ruff", "check", "."]

[merge]
auto = true
push = false
# remote = "origin"

[sandbox]
verification_network = false
environment_allowlist = []

[[sandbox.mounts]]        # optional extra mounts, explicit and validated
# source = "/path/on/host"
# target = "/path/in/sandbox"
# writable = false

[telemetry]
max_runs = 100
max_age_days = 30

[guards]
allowed_test_deletions = []
```

Configuration is versioned and rejects unknown sections or keys, invalid types, empty command arrays, unknown harness profiles, invalid branch references, and non-positive limits. All executable commands are argument arrays; shell syntax requires an explicit shell invocation. The optional model value is stored as an opaque string with no dynamic discovery or validation.

## Issues

Issues are Markdown files named `<numeric-id>-<slug>.md` in the configured issue directory. The numeric prefix is identity and processing order. Frontmatter is deliberately narrow: `status`, `branch`, and `attempts`.

```markdown
---
status: pending
---

# Issue 001 — Add user authentication

## Acceptance criteria

- [ ] POST /auth/login returns a JWT pair
```

Status progresses `pending -> in_progress -> ready -> done`, with `blocked` as a failure outcome. `ready` means the Gate passed but the work is unmerged; `done` means it was merged into the Target.

## How a run works

1. Preflight validates configuration, the whole issue queue, the clean target tree, the target branch, branch references, and optional remote state, under a per-repository `flock`.
2. Ralf commits the `in_progress` transition on the target, then creates the feature branch and an XDG-state worktree from that commit.
3. The Harness runs as a fresh process with the prompt on standard input and the worktree as its working directory. It edits files but cannot own issue state, staging, commits, worktrees, verification, merges, or pushes.
4. Ralf runs the guards and verification commands in Bubblewrap, then reruns the guards to catch formatter or check mutations.
5. Ralf revalidates repository, branch, worktree, and the eligible diff, then commits exactly the validated tree and marks the issue `ready`.
6. With auto-merge, Ralf synchronizes the target by fast-forward only, reruns the whole gate against the merge candidate, merges with `--no-ff`, commits `done` separately, and removes the worktree.

Spawn failure, nonzero Harness exit, timeout, or signal is an infrastructure failure: Ralf preserves edits, branch, and worktree, leaves the issue `in_progress`, and does not consume an attempt. Verification failure consumes an attempt and starts a fresh Harness process with the final 32 KiB of prior diagnostics; the full transcript stays local.

## Sandboxing

On Linux, Harness and verification processes run inside a [bubblewrap](https://github.com/containers/bubblewrap) sandbox:

- The assigned worktree is the only writable repository location; the worktree Git link and Harness credential mounts are read-only
- Harness runs keep network access for provider calls; verification has no network unless `sandbox.verification_network` enables it
- Ralf fails closed when Bubblewrap is missing or cannot start, unless the run explicitly passed `--no-sandbox`

Isolation reduces filesystem and process exposure but cannot prevent a networked Harness from transmitting source it is able to read. Treat the sandbox as a blast-radius limit, not a data-loss-prevention boundary.

## Telemetry

Ralf writes append-only JSONL records under `$XDG_STATE_HOME/ralf/repositories/<identity>` (`~/.local/state` by default). Structured records cover runs, issues, attempts, Harness and verification operations, Git operations, and workflow transitions with IDs, times, outcomes, and durations. They never contain prompts, diffs, environment values, absolute paths, credential values, or raw argument arrays.

Raw stdout and stderr are stored separately with `0600` permissions and explicit size bounds. Records are retained for at most 100 runs or 30 days, whichever limit is reached first, and cleanup is recorded. The event sink stays backend-neutral; no dashboard or OpenTelemetry dependency is introduced, and any future remote export is metadata-only by default.

## Repository layout

```
src/ralf/           # installed Python package
  cli.py            # init, validate, run, status, finalize, retry
  config.py         # versioned configuration and init
  issues.py         # file-backed issue queue and transitions
  guards.py         # protected-path and test-deletion guards
  git.py            # Ralf-owned Git operations
  harness.py        # data-driven Harness profiles
  orchestrator.py   # the workflow engine
  plan.py           # preflight, execution plan, repository lock
  process.py        # the command process boundary
  sandbox.py        # Bubblewrap policy
  settings.py       # typed configuration view
  telemetry.py      # local-first records, transcripts, retention
  diagnostics.py    # machine-readable validation problems
  resources.py      # packaged prompt resources
docs/adr/           # architecture decision records
docs/issues/        # the project issue queue
tests/              # pytest behavior and integration tests
```
