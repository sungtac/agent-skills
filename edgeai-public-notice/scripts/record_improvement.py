#!/usr/bin/env python3
"""Append a reviewed, reproducible improvement record to the shared state."""
from pathlib import Path
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path('/home/edge_ai/edgeai-public-notice')
STATE = ROOT / 'state' / 'improvements.jsonl'

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--issue', required=True)
    ap.add_argument('--condition', required=True)
    ap.add_argument('--change', required=True)
    ap.add_argument('--verification', required=True)
    args = ap.parse_args()
    STATE.parent.mkdir(parents=True, exist_ok=True)
    record = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'issue': args.issue,
        'reproduction_condition': args.condition,
        'change': args.change,
        'verification': args.verification,
    }
    with STATE.open('a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')
    sync = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'sync_skill.py')], text=True, capture_output=True)
    print(f'RECORDED {STATE}')
    if sync.returncode:
        print('SYNC_PENDING: run sync_skill.py with permission to update protected skill roots')
        return 1
    print(sync.stdout.strip())
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
