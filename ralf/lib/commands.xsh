"""Project command detection table.

Maps project files to test, typecheck, and lint commands.
ralf.toml [commands] section overrides auto-detected entries."""

import json as _json
import pathlib as _pathlib

_DEFAULT_TABLE = {
    'package.json': {
        'match': lambda root: root.joinpath('package.json').exists(),
        'test': 'npm test',
        'typecheck': 'tsc --noEmit',
        'lint_check': lambda root: _has_npm_script(root, 'lint'),
        'lint': 'npm run lint',
    },
    'pyproject.toml|setup.cfg': {
        'match': lambda root: (root.joinpath('pyproject.toml').exists()
                               or root.joinpath('setup.cfg').exists()),
        'test': 'pytest',
        'typecheck': 'mypy .',
        'lint': 'ruff check .',
    },
    'Makefile': {
        'match': lambda root: root.joinpath('Makefile').exists(),
        'test': 'make test',
        'typecheck': 'make typecheck',
        'lint': 'make lint',
    },
    'Cargo.toml': {
        'match': lambda root: root.joinpath('Cargo.toml').exists(),
        'test': 'cargo test',
        'typecheck': 'cargo check',
        'lint': 'cargo clippy',
    },
    'go.mod': {
        'match': lambda root: root.joinpath('go.mod').exists(),
        'test': 'go test ./...',
        'typecheck': 'go vet ./...',
        'lint': 'golangci-lint run',
    },
}

def _has_npm_script(root, name):
    pkg = root.joinpath('package.json')
    if not pkg.exists():
        return False
    with open(pkg) as f:
        data = _json.load(f)
    return name in data.get('scripts', {})

def detect_commands(project_root, overrides=None):
    """Return {test, typecheck, lint} dict for the project.

    overrides — optional dict from ralf.toml [commands] section.
    Entries in overrides win unconditionally.
    """
    root = _pathlib.Path(project_root)
    cmds = {'test': None, 'typecheck': None, 'lint': None}

    for entry in _DEFAULT_TABLE.values():
        if entry['match'](root):
            cmds['test'] = entry['test']
            cmds['typecheck'] = entry['typecheck']
            if 'lint_check' in entry and entry['lint_check'](root):
                cmds['lint'] = entry['lint']
            elif 'lint' in entry:
                cmds['lint'] = entry['lint']
            break

    if overrides:
        for k in ('test', 'typecheck', 'lint'):
            if overrides.get(k):
                cmds[k] = overrides[k]

    return cmds
