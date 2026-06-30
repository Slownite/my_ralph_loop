#!/usr/bin/env xonsh
"""Tests for ralf/lib/issues.xsh — issue file frontmatter manipulation."""

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
    source @(str(ralf.joinpath('lib', 'issues.xsh')))

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

def _assert_false(v, desc):
    global _tc, _tf
    if not v:
        _tc += 1
        print(f'  PASS: {desc}')
    else:
        _tf += 1
        print(f'  FAIL: {desc} (expected False)')

print('issues module tests')

# ---- extract_number ----
_assert_eq(extract_number('001-foo.md'), 1, 'extract_number: 001-foo -> 1')
_assert_eq(extract_number('42-bar.md'), 42, 'extract_number: 42-bar -> 42')
_assert_eq(extract_number('abc.md'), 0, 'extract_number: abc -> 0')
_assert_eq(extract_number(''), 0, 'extract_number: empty -> 0')

# ---- extract_title ----
_assert_eq(extract_title('# Hello'), 'Hello', 'extract_title: h1')
_assert_eq(extract_title('## Hello'), 'Hello', 'extract_title: h2')
_assert_eq(extract_title('body\n# Title\nmore'), 'Title', 'extract_title: second line')
_assert_eq(extract_title('no heading'), 'untitled', 'extract_title: none found')
_assert_eq(extract_title(''), 'untitled', 'extract_title: empty body')

# ---- slugify ----
_assert_eq(slugify('Hello World'), 'hello-world', 'slugify: simple')
_assert_eq(slugify('Hello   World!!!'), 'hello-world', 'slugify: multi-space+symbols')
_assert_eq(slugify('  --hello--  '), 'hello', 'slugify: edge dashes')
_assert_eq(slugify('ABC'), 'abc', 'slugify: lowercase')

# ---- read_issue ----
td = _tempfile.mkdtemp()
try:
    fp = str(_pathlib.Path(td).joinpath('test.md'))
    _pathlib.Path(fp).write_text('---\nstatus: pending\n---\n\nBody text\n')
    fm, body = read_issue(fp)
    _assert_eq(fm.get('status'), 'pending', 'read_issue: frontmatter status')
    _assert_eq(body, 'Body text', 'read_issue: body')

    fp2 = str(_pathlib.Path(td).joinpath('plain.md'))
    _pathlib.Path(fp2).write_text('Just body\n')
    fm2, body2 = read_issue(fp2)
    _assert_eq(fm2, {}, 'read_issue: no frontmatter -> empty dict')
    _assert_eq(body2, 'Just body\n', 'read_issue: no frontmatter body')

    fp3 = str(_pathlib.Path(td).joinpath('emptyfm.md'))
    _pathlib.Path(fp3).write_text('---\n---\n\nBody\n')
    fm3, body3 = read_issue(fp3)
    _assert_eq(fm3, {}, 'read_issue: empty frontmatter -> empty dict')
    _assert_eq(body3, 'Body', 'read_issue: empty frontmatter body')

    fp4 = str(_pathlib.Path(td).joinpath('fm-only.md'))
    _pathlib.Path(fp4).write_text('---\nstatus: done\n---\n')
    fm4, body4 = read_issue(fp4)
    _assert_eq(fm4.get('status'), 'done', 'read_issue: fm-only status')
    _assert_eq(body4, '', 'read_issue: fm-only body empty')
finally:
    _shutil.rmtree(td)

# ---- write_issue ----
td = _tempfile.mkdtemp()
try:
    fp = str(_pathlib.Path(td).joinpath('w.md'))
    write_issue(fp, {'status': 'in_progress'}, 'Work in progress')
    content = _pathlib.Path(fp).read_text()
    _assert_true(content.startswith('---\nstatus: in_progress\n---\n'), 'write_issue: format')
    _assert_true('Work in progress' in content, 'write_issue: body')
finally:
    _shutil.rmtree(td)

# ---- add_frontmatter_if_missing ----
td = _tempfile.mkdtemp()
try:
    fp = str(_pathlib.Path(td).joinpath('no-front.md'))
    _pathlib.Path(fp).write_text('No frontmatter')
    result = add_frontmatter_if_missing(fp)
    _assert_true(result, 'add_frontmatter_if_missing: added to plain file')
    content = _pathlib.Path(fp).read_text()
    _assert_true(content.startswith('---\nstatus: pending\n---\n'), 'add_frontmatter_if_missing: prepended')

    result2 = add_frontmatter_if_missing(fp)
    _assert_false(result2, 'add_frontmatter_if_missing: already present -> False')
finally:
    _shutil.rmtree(td)

# ---- set_status ----
td = _tempfile.mkdtemp()
try:
    fp = str(_pathlib.Path(td).joinpath('status.md'))
    _pathlib.Path(fp).write_text('---\nstatus: pending\n---\n\nWork\n')
    set_status(fp, 'done')
    fm, body = read_issue(fp)
    _assert_eq(fm.get('status'), 'done', 'set_status: pending -> done')
    _assert_eq(body, 'Work', 'set_status: body unchanged')
finally:
    _shutil.rmtree(td)

# ---- get_issue_paths ----
td = _tempfile.mkdtemp()
try:
    _assert_eq(get_issue_paths('/nonexistent/path'), [], 'get_issue_paths: no dir -> []')

    issues_dir = _pathlib.Path(td).joinpath('docs', 'issues')
    issues_dir.mkdir(parents=True)
    _pathlib.Path(str(issues_dir.joinpath('001-a.md'))).write_text('a')
    _pathlib.Path(str(issues_dir.joinpath('002-b.md'))).write_text('b')
    paths = get_issue_paths(str(issues_dir))
    _assert_eq(len(paths), 2, 'get_issue_paths: found 2 files')
    _assert_true('002-b' in str(paths[1]), 'get_issue_paths: sorted order')
finally:
    _shutil.rmtree(td)

print(f'\nResults: {_tc} passed, {_tf} failed')
if _tf > 0:
    exit(1)
