"""Parse every source/fixture without modifying infrastructure."""
import ast
import json
from pathlib import Path
import re

import yaml

root = Path(__file__).resolve().parents[1]
sources = list(root.glob('*.py')) + list((root / 'tests').glob('*.py'))
for source in sources:
    ast.parse(source.read_text(encoding='utf-8'), filename=str(source))
for fixture in (root / 'tests' / 'fixtures').glob('*.json'):
    json.loads(fixture.read_text(encoding='utf-8'))
manifest = json.loads((root / 'validation-manifest.json').read_text())
assert re.fullmatch(r'nginx:1\.30@sha256:[a-f0-9]{64}', manifest['nginx_image'])
assert re.fullmatch(r'[a-f0-9]{64}', manifest['xray']['sha256'])
assert all(re.fullmatch(r'[a-f0-9]{40}', sha) for sha in manifest['actions'].values())
for source in [root / 'config.example.yaml', *list((root / '.github' / 'workflows').glob('*.yml'))]:
    assert isinstance(yaml.safe_load(source.read_text(encoding='utf-8')), dict)
print(f'AST {len(sources)} files; JSON, YAML and pinned validation manifest PASS')
