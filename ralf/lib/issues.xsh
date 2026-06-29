"""Issue file scanning and frontmatter manipulation."""

import pathlib as _pathlib
import re as _re

def get_issue_paths(issues_dir='docs/issues/'):
    p = _pathlib.Path(issues_dir)
    if not p.exists():
        return []
    return sorted(p.glob('*.md'))

def read_issue(path):
    """Return (frontmatter_dict[str, str], body_str)."""
    content = _pathlib.Path(path).read_text()
    frontmatter = {}
    body = content
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            for line in parts[1].strip().split('\n'):
                if ':' in line:
                    k, v = line.split(':', 1)
                    frontmatter[k.strip()] = v.strip()
            body = parts[2].strip()
    return frontmatter, body

def write_issue(path, frontmatter, body):
    lines = ['---']
    for k, v in frontmatter.items():
        lines.append(f'{k}: {v}')
    lines.append('---')
    _pathlib.Path(path).write_text('\n'.join(lines) + '\n\n' + body.strip() + '\n')

def add_frontmatter_if_missing(path):
    p = _pathlib.Path(path)
    content = p.read_text()
    if content.startswith('---'):
        return False
    p.write_text('---\nstatus: pending\n---\n\n' + content)
    return True

def set_status(path, status):
    fm, body = read_issue(path)
    fm['status'] = status
    write_issue(path, fm, body)

def extract_number(filename):
    m = _re.match(r'(\d+)', filename)
    return int(m.group(1)) if m else 0

def extract_title(body):
    for line in body.split('\n'):
        line = line.strip()
        if line.startswith('# ') or line.startswith('## '):
            return line.lstrip('#').strip()
    return 'untitled'

def slugify(title):
    s = title.lower()
    s = _re.sub(r'[^a-z0-9]+', '-', s)
    s = s.strip('-')
    return s[:50].rstrip('-')
