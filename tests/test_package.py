from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .test_validate_cli import VALID_CONFIG


def test_built_wheel_runs_and_loads_resources_outside_checkout(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    assert uv is not None
    repository = Path(__file__).parents[1]
    distribution_directory = tmp_path / "distribution"
    subprocess.run(
        [uv, "build", "--wheel", "--out-dir", str(distribution_directory)],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = list(distribution_directory.glob("*.whl"))
    assert len(wheels) == 1

    environment = tmp_path / "environment"
    subprocess.run(
        [uv, "venv", str(environment)],
        check=True,
        capture_output=True,
        text=True,
    )
    python = environment / "bin" / "python"
    subprocess.run(
        [uv, "pip", "install", "--python", str(python), str(wheels[0])],
        check=True,
        capture_output=True,
        text=True,
    )

    project = tmp_path / "project"
    (project / "docs" / "issues").mkdir(parents=True)
    (project / "ralf.toml").write_text(VALID_CONFIG)
    result = subprocess.run(
        [environment / "bin" / "ralf-loop", "validate", "--json"],
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
    )
    resource = subprocess.run(
        [
            python,
            "-c",
            "from ralf.resources import issue_prompt; print(issue_prompt(), end='')",
        ],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout) == {"valid": True, "errors": []}
    assert resource.stdout.startswith("# Ralf issue execution playbook\n")
    assert "Ralf owns Git operations" in resource.stdout
