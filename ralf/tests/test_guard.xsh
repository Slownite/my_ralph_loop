#!/usr/bin/env xonsh
"""Tests for ralf/lib/guard.xsh — test-deletion guard."""

import os as _os
import pathlib as _pathlib
import shutil as _shutil
import subprocess as _subprocess
import tempfile as _tempfile

def _load_guard():
    ralf_env = _os.environ.get('RALF_ROOT', '')
    if ralf_env and _pathlib.Path(ralf_env).is_dir():
        ralf = _pathlib.Path(ralf_env)
    else:
        ralf = _pathlib.Path(__file__).resolve().parent.parent
    src = ralf.joinpath('lib', 'guard.xsh')
    source @(str(src))

_load_guard()

_pass = 0
_fail = 0

def _make_repo(tmpdir, add_file=None, del_file=None):
    repo = _pathlib.Path(tmpdir)

    _subprocess.run(['git', 'init', '-q', str(repo)], capture_output=True)
    _subprocess.run(['git', '-C', str(repo), 'config', 'user.email', 'test@test.com'],
                    capture_output=True)
    _subprocess.run(['git', '-C', str(repo), 'config', 'user.name', 'Test'],
                    capture_output=True)

    repo.joinpath('src').mkdir(parents=True, exist_ok=True)
    repo.joinpath('tests').mkdir(parents=True, exist_ok=True)
    repo.joinpath('src', 'app.py').write_text('x')
    repo.joinpath('tests', 'test_app.py').write_text('x')
    repo.joinpath('tests', 'test_util.py').write_text('x')
    _subprocess.run(['git', '-C', str(repo), 'add', '.'], capture_output=True)
    _subprocess.run(['git', '-C', str(repo), 'commit', '-q', '-m', 'base'],
                    capture_output=True)

    _subprocess.run(['git', '-C', str(repo), 'checkout', '-q', '-b', 'feature'],
                    capture_output=True)

    if del_file:
        _subprocess.run(['git', '-C', str(repo), 'rm', '-q', del_file],
                        capture_output=True)
    if add_file:
        p = repo.joinpath(add_file)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('x')
        _subprocess.run(['git', '-C', str(repo), 'add', add_file],
                        capture_output=True)

    r = _subprocess.run(['git', '-C', str(repo), 'diff', '--cached', '--quiet'],
                        capture_output=True)
    r2 = _subprocess.run(['git', '-C', str(repo), 'diff', '--quiet'],
                         capture_output=True)
    if r.returncode == 0 and r2.returncode == 0:
        repo.joinpath('src', 'noop').write_text('noop')
        _subprocess.run(['git', '-C', str(repo), 'add', '.'], capture_output=True)

    _subprocess.run(['git', '-C', str(repo), 'commit', '-q', '-m', 'feature'],
                    capture_output=True)


def _assert_guard(expected_pass, desc, repo_dir):
    global _pass, _fail
    ok, msg = guard_test_deletion(repo_dir, 'main')
    if ok == expected_pass:
        _pass += 1
        print(f'  PASS: {desc}')
    else:
        _fail += 1
        print(f'  FAIL: {desc} (expected pass={expected_pass}, got pass={ok}, msg={msg})')


print('guard_test_deletion tests')

# Case 1: no files deleted → pass
d = _tempfile.mkdtemp()
_make_repo(d)
_assert_guard(True, 'no files deleted → pass', d)
_shutil.rmtree(d)

# Case 2: test file deleted → fail
d = _tempfile.mkdtemp()
_make_repo(d, del_file='tests/test_app.py')
_assert_guard(False, 'test file deleted (test_app.py) → fail', d)
_shutil.rmtree(d)

# Case 3: non-test file deleted → pass
d = _tempfile.mkdtemp()
_make_repo(d, del_file='src/app.py')
_assert_guard(True, 'non-test file deleted (src/app.py) → pass', d)
_shutil.rmtree(d)

# Case 4: test file added → pass
d = _tempfile.mkdtemp()
_make_repo(d, add_file='tests/test_new.py')
_assert_guard(True, 'test file added → pass', d)
_shutil.rmtree(d)

# Case 5: multiple test files deleted → fail
d = _tempfile.mkdtemp()
_make_repo(d, del_file='tests/test_app.py')
_subprocess.run(['git', '-C', d, 'rm', '-q', 'tests/test_util.py'], capture_output=True)
_subprocess.run(['git', '-C', d, 'commit', '-q', '-m', 'delete more tests'],
                capture_output=True)
_assert_guard(False, 'multiple test files deleted → fail', d)
_shutil.rmtree(d)

print(f'\nResults: {_pass} passed, {_fail} failed')
if _fail > 0:
    exit(1)
