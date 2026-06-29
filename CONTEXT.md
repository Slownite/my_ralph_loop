# ralf — AFK issue automation loop

An autonomous loop that picks file-based issues from `docs/issues/`, dispatches them to opencode for TDD implementation, runs a local pre-merge gate (test + typecheck + lint), and auto-merges to main when all checks pass.

## Language

**Issue**:
A markdown file in `docs/issues/` with YAML frontmatter containing a `status` field. Acceptance criteria are checkbox items in the body. Formerly a GitHub issue.
_Status values_: `pending`, `in_progress`, `done`, `blocked`

**Loop**:
The outer xonsh orchestrator (`ralf-loop`) that scans pending issues, dispatches each to opencode, gates the result, and merges or retries.

**Iteration**:
One invocation of `opencode run`. Counts toward `max_iterations`. Includes both initial implementation and subsequent retry attempts on the same issue.

**Gate**:
The local verification suite (test runner + type checker + linter) executed by ralf on the feature branch before merge. All must pass for merge to proceed.

**Playbook**:
The prompt template (`ralf/prompts/ralf-issue.md`) injected with the issue body and detected command table, then sent to opencode. Ends at "code committed to branch" — the gate is ralf's responsibility.

**Branch**:
A git branch `ralf/issue-N-slug` created from main in a disposable worktree. Implemented during retries on the same issue.

**Worktree**:
A disposable git worktree at `/tmp/ralf-issue-N` where all implementation and the gate run.

**ralf.toml**:
Per-project configuration file (auto-generated, user-editable) defining the default model, max iterations, command overrides, and merge behavior.

**Init**:
A mode (`ralf-loop --init`) that scans `docs/issues/*.md` for markdown issue files and prepends YAML frontmatter (`status: pending`) to any file missing it.

**Guard**:
A pre-gate check that verifies the branch has not decreased the net test file count relative to `main` (catches opencode deleting tests).

## Relationships

- A **Playbook** is assembled from the **Issue** body + the **Prompt** template + the detected **Command table**
- A **Branch** is isolated in a **Worktree**; ralf runs **Gate** and **Guard** inside the worktree
- The **Loop** consumes **Iteration** budget until all **Issues** are `done` or budget exhausted
- **ralf.toml** supplies the default **model** and **Iteration** budget

## Example dialogue

> **Dev:** "What happens if the Gate fails on the initial implementation?"
> **Domain expert:** "Ralf feeds the failure output back to opencode as a new iteration. It keeps retrying until the Gate passes or the iteration budget runs out — then the issue is blocked."
>
> **Dev:** "And if opencode crashes mid-implementation?"
> **Domain expert:** "That's an infrastructure failure, not an implementation failure — ralf retries with backoff using a separate counter, not the iteration budget."
