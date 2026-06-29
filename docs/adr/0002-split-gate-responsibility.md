# Split gate responsibility: ralf owns the pre-merge gate, opencode only implements

Instead of delegating the full "implement, test, lint, merge" workflow to opencode in a single prompt, ralf's xonsh code owns the command-detection table (mapping project files to test/typecheck/lint commands), runs the pre-merge gate itself, and retries opencode when the gate fails.

This prevents opencode from being the sole arbiter of "is this code ready?" — if opencode skips tests, hallucinates passing output, or deletes test files, the gate catches it independently. The trade-off is duplication: the command table must exist in both xonsh code (for the gate) and in the injected prompt snippet (so opencode knows what to run during RED/GREEN). Mitigated by injecting the command table as a prompt-snippet generated from the same xonsh source, so there's a single source of truth with two consumers.

A future reader might wonder "why doesn't opencode just run tests and merge itself?" — because the gate is the independent safety net. Giving the agent final say over whether its own code is ready defeats the purpose of verification.

## Considered Options

- **Full delegation (opencode does everything)** — Simpler xonsh code, but opencode controls the gate. If opencode decides to skip tests or misreports output, the loop trusts it. Harder to audit.
- **Full separation (ralf does everything, opencode only generates code)** — Ralf auto-detects commands, passes them to opencode as hints, then independently runs the gate. Gives ralf final control. Chosen for this reason.
