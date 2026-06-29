"""Prompt assembly for opencode."""

import pathlib as _pathlib
import issues as _issues

def assemble_prompt(issue_path, commands, ralf_root):
    """Build the full prompt string for opencode run."""
    filename = _pathlib.Path(issue_path).name
    fm, body = _issues.read_issue(issue_path)
    issue_num = _issues.extract_number(filename)
    issue_title = _issues.extract_title(body)

    template_path = _pathlib.Path(ralf_root) / 'prompts' / 'ralf-issue.md'
    template = template_path.read_text()

    cmd_lines = ['## Project commands\n']
    labels = {'test': 'Test', 'typecheck': 'Type check', 'lint': 'Lint'}
    for key, label in labels.items():
        cmd = commands.get(key)
        if cmd:
            cmd_lines.append(f'- **{label}:** `{cmd}`')

    cmd_block = '\n'.join(cmd_lines) + '\n\n---\n'

    progress_path = _pathlib.Path.cwd() / 'ralf-progress.txt'
    context = ''
    if progress_path.exists():
        context = (f'## Prior context\n\n```\n{progress_path.read_text()}\n```\n'
                   '\n---\n')

    return (f'# Issue #{issue_num}: {issue_title}\n\n{body}\n\n---\n\n'
            f'{context}{cmd_block}{template}')
