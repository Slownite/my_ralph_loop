"""ralf.toml read/write/generate"""

import pathlib
try:
    import tomllib
except ImportError:
    import tomli as tomllib

_DEFAULTS = {
    'model': {'default': 'claude-sonnet-4'},
    'loop': {'max_iterations': 10, 'retry_backoff_max': 8},
    'commands': {},
    'merge': {'auto': True},
}

def read_config(path='ralf.toml'):
    p = pathlib.Path(path)
    if not p.exists():
        return dict(_DEFAULTS)
    with open(p, 'rb') as f:
        config = tomllib.load(f)
    for section, values in _DEFAULTS.items():
        if section not in config:
            config[section] = dict(values)
        else:
            for k, v in values.items():
                config[section].setdefault(k, v)
    return config

def write_config(config, path='ralf.toml'):
    lines = []
    for section, values in config.items():
        if not values:
            continue
        lines.append(f'[{section}]')
        for k, v in values.items():
            if isinstance(v, str):
                lines.append(f'{k} = "{v}"')
            elif isinstance(v, bool):
                lines.append(f'{k} = {"true" if v else "false"}')
            else:
                lines.append(f'{k} = {v}')
        lines.append('')
    pathlib.Path(path).write_text('\n'.join(lines) + '\n')

def generate_default(model=''):
    return {
        'model': {'default': model or 'claude-sonnet-4'},
        'loop': {'max_iterations': 10},
        'commands': {},
        'merge': {'auto': True},
    }
