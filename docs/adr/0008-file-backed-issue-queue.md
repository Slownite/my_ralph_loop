---
status: superseded by ADR-0010
---

# Keep the file-backed issue queue

Ralf's project work queue stays local, Git-aware, and file-backed after the Python rewrite. Issues remain Markdown files in the configured issue directory whose numeric filename prefix is both identity and processing order, and whose narrow `key: scalar` frontmatter carries only workflow status, branch, and cumulative attempts.

This supersedes the earlier Xonsh-era file-based-issues decision and keeps Ralf independent of any external tracker at runtime. GitHub tracks this rewrite specification only; it is not Ralf's runtime issue store. The deliberate refusal to add a general YAML parser is retained: portability and a predictable parser are worth more than richer frontmatter.
