"""Access resources shipped in the Ralf package."""

from importlib.resources import files


def issue_prompt() -> str:
    """Return the harness-neutral issue execution playbook."""

    return files("ralf.prompts").joinpath("ralf-issue.md").read_text(encoding="utf-8")
