# Keep telemetry local and content-free by default

Ralf records crash-safe structured operation metadata and bounded local transcripts without requiring a dashboard or remote service; structured records exclude prompts, diffs, environment values, absolute paths, and raw arguments. A backend-neutral event sink leaves room for later metadata-only OTLP export while avoiding vendor coupling and accidental sensitive-content export in the core workflow.
