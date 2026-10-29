"""Heuristic scan of reachable Git blobs and current source files, locations only.

No secret values are printed. This cannot prove absence of arbitrary secrets.
"""
import json
import io
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(['git', '-c', 'safe.directory=' + ROOT.as_posix(), *args], cwd=ROOT)


patterns = {
    'private-key': rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----',
    'github-token': rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b',
    'jwt': rb'\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b',
    'aws-access': rb'\bAKIA[A-Z0-9]{16}\b',
}
hits = []


def scan(name, content):
    for label, pattern in patterns.items():
        for match in re.finditer(pattern, content):
            hits.append({'path': name, 'kind': label, 'line': content[:match.start()].count(b'\n') + 1})


objects = git('rev-list', '--objects', '--all').decode().splitlines()
count = 0
batch = subprocess.check_output(
    ['git', '-c', 'safe.directory=' + ROOT.as_posix(), 'cat-file', '--batch'],
    input=('\n'.join(row.split(' ', 1)[0] for row in objects) + '\n').encode(), cwd=ROOT)
stream = io.BytesIO(batch)
for row in objects:
    oid, _, name = row.partition(' ')
    header = stream.readline().split()
    if len(header) != 3:
        raise RuntimeError('Cannot read reachable Git object')
    content = stream.read(int(header[2]))
    if stream.read(1) != b'\n':
        raise RuntimeError('Invalid Git batch framing')
    if header[1] == b'blob':
        scan(name, content)
        count += 1
files = git('ls-files', '--cached', '--others', '--exclude-standard').decode().splitlines()
for name in set(files):
    path = ROOT / name
    if path.is_file():
        scan(name, path.read_bytes())
print(json.dumps({'reachableBlobs': count, 'worktreeFiles': len(set(files)), 'hits': hits}, indent=2))
raise SystemExit(bool(hits))
