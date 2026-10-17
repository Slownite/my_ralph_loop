# Package Ralf with Python and uv

Ralf will move from an Xonsh program distributed through Nix to a Python 3.11+ package locked and developed with uv, because an ordinary console package is easier to install from a checkout or Git URL and test independently of its source tree. The Python implementation will coexist with Xonsh until end-to-end parity is proven; after cutover, Git and Bubblewrap remain explicit Linux system prerequisites rather than bundled runtime dependencies.

## Considered Options

- **Keep Xonsh and Nix** — pins system tools conveniently, but couples installation and development to Nix and keeps the orchestration code in a niche runtime.
- **Publish a Python package to PyPI** — provides a public registry path, but adds a release channel that this personal, Git-installed tool does not need.
