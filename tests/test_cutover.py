"""Cutover tests: the Python package is the only supported implementation."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]


def _tracked_python_files(pattern: str) -> list[Path]:
    return [
        path
        for path in ROOT.rglob(pattern)
        if ".venv" not in path.parts and ".git" not in path.parts
    ]


def test_legacy_implementation_is_removed() -> None:
    for legacy in ("bin", "ralf", "flake.nix", "flake.lock"):
        assert not (ROOT / legacy).exists(), f"{legacy} should be removed"

    assert not _tracked_python_files("*.xsh")
    assert not _tracked_python_files("*.xonsh")


def test_package_is_python_only() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text().lower()
    assert 'ralf-loop = "ralf.cli:main"' in pyproject
    assert "xonsh" not in pyproject
    assert "nix" not in pyproject
    assert "bwrap" not in pyproject  # Bubblewrap is a system prerequisite, not a dependency


def test_there_is_no_pypi_publication_configuration() -> None:
    for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
        assert "pypi" not in workflow.read_text().lower()
    assert "publish" not in (ROOT / "pyproject.toml").read_text().lower()


def test_architecture_decisions_cover_the_rewrite() -> None:
    decisions = sorted((ROOT / "docs" / "adr").glob("*.md"))
    assert len(decisions) >= 7
    text = "\n".join(decision.read_text() for decision in decisions).lower()
    for topic in ("harness", "bubblewrap", "telemetry", "file-backed", "gate", "workflow"):
        assert topic in text


def test_glossary_uses_the_canonical_language() -> None:
    glossary = (ROOT / "GLOSSARY.md").read_text()
    for term in ("Harness", "Attempt", "Target", "Ready", "Done", "Guard", "Gate", "Blocked"):
        assert term in glossary


def test_ci_exercises_the_full_gate() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    for step in ("ruff format", "ruff check", "pyright", "pytest", "uv build", "uvx"):
        assert step in workflow


def test_no_proprietary_harness_event_dependency() -> None:
    sources = "\n".join(path.read_text() for path in (ROOT / "src").rglob("*.py"))
    assert "session_id" not in sources
    assert "event_stream" not in sources
