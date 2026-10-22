#!/usr/bin/env python3
"""Validate the shared skill inventory, frontmatter, catalog, and deployments."""
from pathlib import Path
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent

def main():
    data = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))
    names = set(data['skills'])
    actual = {p.name for p in ROOT.iterdir() if p.is_dir() and (p / 'SKILL.md').exists()}
    if names != actual:
        raise AssertionError(f'inventory mismatch: manifest-only={sorted(names-actual)}, files-only={sorted(actual-names)}')
    for name in sorted(names):
        text = (ROOT / name / 'SKILL.md').read_text(encoding='utf-8')
        if not re.search(r'^name:', text, re.M) or '[TODO:' in text:
            raise AssertionError(f'invalid or unfinished skill: {name}')
    subprocess.run([sys.executable, str(ROOT / 'generate_skill_guide.py')], check=True)
    sync = subprocess.run([sys.executable, str(ROOT / 'sync_all_skills.py'), '--check'], text=True, capture_output=True)
    if sync.returncode:
        raise AssertionError(sync.stdout + sync.stderr)
    print(f'VALIDATION_PASS skills={len(names)}')

if __name__ == '__main__':
    try:
        main()
    except (AssertionError, json.JSONDecodeError) as exc:
        print(f'VALIDATION_FAIL: {exc}')
        raise SystemExit(1)
