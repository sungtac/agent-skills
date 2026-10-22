#!/usr/bin/env python3
"""Deterministic smoke harness for the portable EdgeAI notice skill."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = ['문제 없음', '검증 완료', '선정 가능성 높음', '구매 확정', '리스크 없음']
REQUIRED_PACKET_KEYS = {'case_id', 'as_of', 'notice_id', 'document_ids', 'status'}

def digest(path):
    h = hashlib.sha256()
    for p in sorted(x for x in path.rglob('*') if x.is_file()):
        h.update(str(p.relative_to(path)).encode())
        h.update(p.read_bytes())
    return h.hexdigest()

def check_packet_fixture(path):
    data = json.loads(path.read_text(encoding='utf-8'))
    missing = REQUIRED_PACKET_KEYS - set(data)
    if missing:
        raise AssertionError(f'packet missing: {sorted(missing)}')
    if data['status'] not in {'READY', 'RESTRICTED', 'EVIDENCE_PENDING', 'HOLD'}:
        raise AssertionError('invalid packet status')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fixture', default=str(ROOT / 'tests' / 'fixtures' / 'minimal-packet.json'))
    args = ap.parse_args()
    check_packet_fixture(Path(args.fixture))
    for p in ROOT.rglob('*'):
        if p.is_file() and p.suffix in {'.md', '.yaml'}:
            text = p.read_text(encoding='utf-8')
            if '[TODO:' in text:
                raise AssertionError(f'unfinished scaffold: {p}')
    sync = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'sync_skill.py'), '--check'], text=True, capture_output=True)
    if sync.returncode:
        raise AssertionError(sync.stdout + sync.stderr)
    print('HARNESS_PASS')

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (AssertionError, json.JSONDecodeError) as exc:
        print(f'HARNESS_FAIL: {exc}')
        raise SystemExit(1)
