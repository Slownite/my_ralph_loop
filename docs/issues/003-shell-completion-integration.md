---
status: pending
---

# Issue 003 — Shell completion integration

**Type:** HITL
**Blocked by:** None
**User stories covered:** N/A

## What to build

Wire up shell tab-completion for the `ralf-loop --model` flag so the user can press Tab and see available models from `opencode models`. This involves creating a xonsh completer that plugs into the user's shell configuration.

The `bin/ralf-complete.xonsh` already exists as a backend that lists model IDs. This slice hooks that backend into the shell's completion mechanism. The exact integration depends on whether the user runs ralf-loop inside xonsh (where xonsh's `completer` API applies) or from their login shell (bash/zsh/fish, which each have their own completion system).

## Acceptance criteria

- [ ] Pressing Tab after `ralf-loop --model ` in the shell shows a list of model IDs from `opencode models`
- [ ] The user's shell config (.bashrc, .zshrc, xonshrc, or equivalent) is updated to load the completer
- [ ] `opencode models` is called once per completion request (no cached stale list)
- [ ] Shell reload or new terminal session activates the completion without manual steps

## Blocked by

None - can start immediately
