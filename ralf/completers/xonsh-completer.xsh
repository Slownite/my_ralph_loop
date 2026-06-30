"""ralf-loop model name completions for xonsh.

Source this file from your xonsh rc to get Tab completion
on `ralf-loop --model ` and `ralf-loop -m `:

    import os as _os
    if _os.environ.get('RALF_ROOT'):
        source _os.path.join(_os.environ['RALF_ROOT'], 'completers', 'xonsh-completer.xsh')
"""

import subprocess as _sp

from xonsh.completers import tools as _xct


@_xct.contextual_command_completer_for('ralf-loop')
def _ralf_model_completer(context):
    args = [a.value for a in context.args]
    arg_index = context.arg_index
    prefix = context.prefix

    if arg_index >= 1 and args[arg_index - 1] in ('--model', '-m'):
        result = _sp.run(['opencode', 'models'],
                         capture_output=True, text=True)
        models = [m for m in result.stdout.strip().split('\n')
                  if '/' in m]
        if prefix:
            return {m for m in models if m.startswith(prefix)}
        return set(models)

    if arg_index == 1:
        return {'--model': None, '-m': None,
                '--dry-run': None, '--list-models': None,
                '--init': None, '--help': None,
                '--no-auto-merge': None, '--yes': None}

    return None
