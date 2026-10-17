# ralf

AFK issue automation loop. Picks file-based issues from `docs/issues/`, dispatches each to opencode for TDD implementation, runs a local pre-merge gate (test + typecheck + lint), and auto-merges to main when all checks pass.

## Python validation preview

The Python rewrite is being built alongside the current Xonsh loop. Its first tracer bullet provides strict, read-only validation through an installed `ralf-loop` command; the Xonsh implementation remains the active automation loop until parity and cutover.

Python 3.11 or newer and [uv](https://docs.astral.sh/uv/) are required for this preview. Install from a checkout or Git URL rather than PyPI:

```bash
uv tool install .
uv tool install git+https://github.com/Slownite/my_ralph_loop.git
```

For development:

```bash
uv sync
uv run ralf-loop validate
uv run ralf-loop validate --json
uv run pytest
uv run pyright
uv run ruff check src tests
```

The version 1 configuration validated by this slice has this shape:

```toml
config_version = 1
target_branch = "main"
issue_directory = "docs/issues"

[harness]
profile = "custom"
command = ["fake-agent"]
# model = "opaque-provider-model-name"

[run]
max_issues = 1
max_attempts_per_issue = 3
attempt_timeout_seconds = 3600

[commands]
test = ["pytest"]
typecheck = ["pyright"]
lint = ["ruff", "check", "."]

# Optional named commands are also argument arrays.
[commands.custom]
# docs = ["mkdocs", "build", "--strict"]

[merge]
auto = true
push = false
# remote = "origin"

[sandbox]
verification_network = false
environment_allowlist = []

[telemetry]
max_runs = 100
max_age_days = 30
```

Configuration rejects unknown keys, wrong types, unsupported versions, invalid Git branch names, non-positive limits, and empty or malformed command arrays. Issues retain the narrow `key: scalar` frontmatter format with only `status`, `branch`, and `attempts`; valid statuses are `pending`, `in_progress`, `ready`, `done`, and `blocked`.

`validate` checks the complete issue queue before any later workflow may mutate the project. Its stable exit codes are:

| Code | Meaning |
|------|---------|
| `0` | Configuration and every issue are valid |
| `2` | Validation failed; human output or JSON diagnostics explain every safely discoverable problem |

With `--json`, output always contains a boolean `valid` field and an `errors` array. Each error has stable `code`, `message`, and `path` fields.

## Prerequisites

- [Nix](https://nixos.org/download) with flakes enabled
- [opencode](https://opencode.ai) installed and configured with at least one provider
- API credentials for your chosen model (`opencode providers list` to check)

## Installation

```bash
nix profile install github:Slownite/my_ralph_loop
```

Puts `ralf-loop` on PATH with all dependencies pinned (opencode, git, bubblewrap).

To update:

```bash
nix profile upgrade my_ralph_loop
```

## Usage

### 1. Write issues

Create markdown files in `docs/issues/` with acceptance criteria as checkboxes:

```markdown
---
status: pending
---

# Issue 001 — Add user authentication

## What to build

Implement JWT-based auth with refresh tokens.

## Acceptance criteria

- [ ] POST /auth/login returns a JWT pair
- [ ] Expired access tokens are rejected with 401
- [ ] Refresh token endpoint returns a new access token
```

### 2. Initialize

Prepends YAML frontmatter to any issue file that lacks it:

```bash
ralf-loop --init
```

### 3. Run unattended

From your project directory:

```bash
ralf-loop                       # uses defaults from ralf.toml
ralf-loop 20                    # override max iterations
ralf-loop --model gpt-4o        # override model for this run
ralf-loop --no-auto-merge        # keep branch, don't merge
ralf-loop --dry-run              # show what would happen
```

Each iteration:
1. Picks the lowest-numbered `status: pending` issue
2. Sets it `in_progress`
3. Creates a branch + worktree from main
4. Injects the issue + command table into the playbook prompt
5. Runs `opencode run` inside a bubblewrap sandbox
6. Runs the pre-merge gate (guard → test → typecheck → lint)
7. If gate passes: merges to main, marks `done`, logs to `ralf-progress.txt`
8. If gate fails: feeds output back to opencode and retries (counts as one iteration)
9. If iterations exhausted: marks `blocked`

Outputs `<promise>COMPLETE</promise>` when the queue is empty.

## Configuration

`ralf.toml` is auto-generated on first run (interactive model picker). Edit it to change defaults:

```toml
[model]
default = "claude-sonnet-4"

[loop]
max_iterations = 10

[commands]
# overrides for auto-detected commands
# test = "pytest --cov"
# typecheck = "pyright"

[merge]
auto = true
```

## Labels

Issue status is tracked in the YAML frontmatter:

| Status | Meaning |
|--------|---------|
| `pending` | Ready for automation |
| `in_progress` | Currently being worked on |
| `done` | Completed and merged |
| `blocked` | ralf ran out of iterations — needs human review |

## Sandboxing

On Linux, `opencode` runs inside a [bubblewrap](https://github.com/containers/bubblewrap) sandbox:
- The project worktree is mounted read-write at `/workspace`
- `~/.config/opencode` and `~/.local/share/opencode` are mounted read-only
- Network is available (API calls to LLM providers)
- Everything else is isolated

On macOS, the sandbox is skipped (bubblewrap is Linux-only). The test-deletion guard still runs from outside the sandbox as a safety net.

## Repository layout

```
bin/
  ralf-loop.xonsh          # main AFK loop
  ralf-complete.xonsh      # model listing helper
ralf/
  lib/
    config.xsh             # ralf.toml read/write
    commands.xsh           # test/typecheck/lint detection
    issues.xsh             # issue file frontmatter manipulation
    guard.xsh              # test-deletion guard
    sandbox.xsh            # bubblewrap wrapper
    prompts.xsh            # prompt assembly
  prompts/
    ralf-issue.md          # TDD playbook
  tests/                   # xonsh test suite
flake.nix                  # Nix package definitions
CONTEXT.md                 # domain language glossary
docs/adr/                  # architecture decision records
```
