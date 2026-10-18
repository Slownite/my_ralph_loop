# Use GitHub as the default Issue Source

Ralf selects unassigned GitHub Issues carrying Matt Pocock's `ready-for-agent` triage role by default, while `--local` retains the file-backed queue from ADR-0008. GitHub is the collaboration surface users already triage; a private XDG-state mirror lets the existing recovery and Gate workflow operate without committing tracker metadata into the Target. The label mapping in `docs/agents/triage-labels.md` is authoritative when present, so repositories may rename the canonical roles without configuring Ralf twice.
