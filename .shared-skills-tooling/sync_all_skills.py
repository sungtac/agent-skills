#!/usr/bin/env python3
"""Deploy the shared user-skill source to Codex and Claude roots."""
from pathlib import Path
import argparse
import filecmp
import json
import shutil

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / 'manifest.json'

def skill_names():
    data = json.loads(MANIFEST.read_text(encoding='utf-8'))
    return sorted(data['skills'])

def files(root):
    return sorted(p.relative_to(root) for p in root.rglob('*') if p.is_file())

def same_tree(a, b):
    if not a.exists() or not b.exists():
        return False
    af, bf = set(files(a)), set(files(b))
    return af == bf and all(filecmp.cmp(a/x, b/x, shallow=False) for x in af)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true')
    args = ap.parse_args()
    data = json.loads(MANIFEST.read_text(encoding='utf-8'))
    source_skills = set(skill_names())
    targets = [Path(x) for x in data['targets']]
    if args.check:
        errors = []
        for target in targets:
            for name in source_skills:
                if not same_tree(ROOT / name, target / name):
                    errors.append(str(target / name))
        if errors:
            print('OUT_OF_SYNC')
            print('\n'.join(errors))
            return 1
        print('SYNC_OK')
        return 0
    for target in targets:
        target.mkdir(parents=True, exist_ok=True)
        for name in source_skills:
            shutil.copytree(ROOT / name, target / name, dirs_exist_ok=True)
    print('SYNC_OK')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
