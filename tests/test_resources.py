from ralf.resources import issue_prompt


def test_issue_prompt_is_available_as_a_package_resource() -> None:
    prompt = issue_prompt()

    assert prompt.startswith("# Ralf issue execution playbook\n")
    assert "Ralf owns Git operations" in prompt
