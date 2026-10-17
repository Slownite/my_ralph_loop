# Ralf owns workflow and Git mutations

Ralf, rather than the coding Harness, owns Issue state, staging, commits, worktrees, verification, merges, and optional pushes so that the actor producing a change cannot declare its own work Ready or Done. This preserves the existing independent-gate intent while accepting additional orchestration complexity and keeping Harness capabilities limited to editing files and running commands.
