# File-based issues over GitHub Issues

Issues live as local markdown files in `docs/issues/` with YAML frontmatter (`status: pending | in_progress | done | blocked`) instead of being managed through the GitHub Issues API via `gh`. The loop reads status from files and writes status back by editing frontmatter — no API calls, no labels, no CI triggers.

Being purely file-based means the loop works in any git repo without requiring GitHub authentication, network access, or webhook infrastructure. The trade-off is losing GitHub-specific features like label filtering, CI integration, and the PR review workflow. For a personal AFK tool, the simplicity gain outweighs those losses.

## Considered Options

- **GitHub Issues via `gh`** — Required `gh auth login`, network, and the GitHub API. CI and PR auto-merge relied on GitHub actions. Having the issue tracker on GitHub made sense when the output was PRs. But the loop no longer opens PRs (it merges locally), so GitHub issues became a network dependency with no upside.
- **File-based with directory staging** (`pending/`, `done/`, etc.) — Moving files between directories to change status. Creates messy git history (file renames) and requires more complex diffing to track status transitions. YAML frontmatter in a single file is cleaner and git-aware.
