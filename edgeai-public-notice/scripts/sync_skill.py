#!/usr/bin/env python3
"""Synchronize the shared EdgeAI skill to Codex and Claude skill roots."""
from pathlib import Path
import argparse
import filecmp
import shutil

ROOT = Path('/home/edge_ai/edgeai-public-notice')
TARGETS = [
    Path('/home/edge_ai/.codex/skills/edgeai-public-notice'),
    Path('/home/edge_ai/.claude/skills/edgeai-public-notice'),
]

def files(root):
    return sorted(p.relative_to(root) for p in root.rglob('*') if p.is_file())

def same(a, b):
    af, bf = set(files(a)), set(files(b))
    return af == bf and all(filecmp.cmp(a/x, b/x, shallow=False) for x in af)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true')
    args = ap.parse_args()
    if args.check:
        bad = [str(t) for t in TARGETS if not t.exists() or not same(ROOT, t)]
        if bad:
            print('OUT_OF_SYNC')
            print('\n'.join(bad))
            return 1
        print('SYNC_OK')
        return 0
    for target in TARGETS:
        target.mkdir(parents=True, exist_ok=True)
        for rel in files(ROOT):
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, dest)
    print('SYNC_OK')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
