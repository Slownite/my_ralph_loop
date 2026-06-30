#!/usr/bin/env xonsh
"""Tests for ralf/lib/config.xsh — ralf.toml read/write/generate."""

import os as _os
import pathlib as _pathlib
import shutil as _shutil
import tempfile as _tempfile

def _load_mod():
    ralf_env = _os.environ.get('RALF_ROOT', '')
    if ralf_env and _pathlib.Path(ralf_env).is_dir():
        ralf = _pathlib.Path(ralf_env)
    else:
        ralf = _pathlib.Path(__file__).resolve().parent.parent
    source @(str(ralf.joinpath('lib', 'config.xsh')))

_load_mod()

_tc = 0
_tf = 0

def _assert_eq(a, b, desc):
    global _tc, _tf
    if a == b:
        _tc += 1
        print(f'  PASS: {desc}')
    else:
        _tf += 1
        print(f'  FAIL: {desc} (expected {b!r}, got {a!r})')

def _assert_true(v, desc):
    global _tc, _tf
    if v:
        _tc += 1
        print(f'  PASS: {desc}')
    else:
        _tf += 1
        print(f'  FAIL: {desc} (expected True)')

print('config module tests')

# ---- generate_default ----
cfg = generate_default()
_assert_eq(cfg['model']['default'], 'claude-sonnet-4', 'generate_default: default model')
_assert_eq(cfg['loop']['max_iterations'], 10, 'generate_default: max_iterations')
_assert_eq(cfg['merge']['auto'], True, 'generate_default: auto-merge')
_assert_eq(cfg['commands'], {}, 'generate_default: empty commands')

cfg2 = generate_default('gpt-4o')
_assert_eq(cfg2['model']['default'], 'gpt-4o', 'generate_default: custom model')

# ---- read_config with missing file ----
cfg3 = read_config('/nonexistent/ralf.toml')
_assert_eq(cfg3['model']['default'], 'claude-sonnet-4', 'read_config: missing file defaults')

# ---- read_config with existing file ----
td = _tempfile.mkdtemp()
try:
    toml_path = str(_pathlib.Path(td).joinpath('ralf.toml'))
    _pathlib.Path(toml_path).write_text('[model]\ndefault = "gpt-4o"\n')
    cfg4 = read_config(toml_path)
    _assert_eq(cfg4['model']['default'], 'gpt-4o', 'read_config: overrides model')
    _assert_eq(cfg4['loop']['max_iterations'], 10, 'read_config: missing loop gets default')
    _assert_eq(cfg4['merge']['auto'], True, 'read_config: missing merge gets default')
finally:
    _shutil.rmtree(td)

# ---- read_config with partial file (commands override) ----
td = _tempfile.mkdtemp()
try:
    toml_path = str(_pathlib.Path(td).joinpath('ralf.toml'))
    _pathlib.Path(toml_path).write_text('[commands]\ntest = "pytest --cov"\n')
    cfg5 = read_config(toml_path)
    _assert_eq(cfg5['commands']['test'], 'pytest --cov', 'read_config: commands override')
    _assert_eq(cfg5['model']['default'], 'claude-sonnet-4', 'read_config: model still default')
finally:
    _shutil.rmtree(td)

# ---- read_config with all sections ----
td = _tempfile.mkdtemp()
try:
    toml_path = str(_pathlib.Path(td).joinpath('ralf.toml'))
    _pathlib.Path(toml_path).write_text(
        '[model]\n'
        'default = "claude-sonnet-4"\n'
        '\n'
        '[loop]\n'
        'max_iterations = 5\n'
        '\n'
        '[commands]\n'
        'typecheck = "pyright"\n'
        '\n'
        '[merge]\n'
        'auto = false\n')
    cfg6 = read_config(toml_path)
    _assert_eq(cfg6['model']['default'], 'claude-sonnet-4', 'read_config: full model')
    _assert_eq(cfg6['loop']['max_iterations'], 5, 'read_config: full max_iterations')
    _assert_eq(cfg6['commands']['typecheck'], 'pyright', 'read_config: full commands')
    _assert_eq(cfg6['merge']['auto'], False, 'read_config: full auto=false')
finally:
    _shutil.rmtree(td)

# ---- write_config then read back ----
td = _tempfile.mkdtemp()
try:
    toml_path = str(_pathlib.Path(td).joinpath('ralf.toml'))
    _ = write_config({
        'model': {'default': 'gemini-2.5-pro'},
        'loop': {'max_iterations': 3},
        'commands': {'lint': 'ruff check'},
        'merge': {'auto': False},
    }, toml_path)
    cfg7 = read_config(toml_path)
    _assert_eq(cfg7['model']['default'], 'gemini-2.5-pro', 'write+read: model')
    _assert_eq(cfg7['loop']['max_iterations'], 3, 'write+read: max_iterations')
    _assert_eq(cfg7['commands']['lint'], 'ruff check', 'write+read: lint')
    _assert_eq(cfg7['merge']['auto'], False, 'write+read: auto=false')
finally:
    _shutil.rmtree(td)

print(f'\nResults: {_tc} passed, {_tf} failed')
if _tf > 0:
    exit(1)
