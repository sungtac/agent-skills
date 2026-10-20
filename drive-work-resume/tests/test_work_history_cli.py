"""Exercise the real CLI and subprocess boundary against a synthetic Drive backend."""
import json
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'work_history.py'
FAKE_RCLONE = r'''#!/usr/bin/env python3
import hashlib, json, os, re, sys, uuid
from pathlib import Path
path=Path(os.environ['FAKE_DRIVE_STORE'])
data=json.loads(path.read_text())
a=sys.argv[1:]
if os.environ.get('FAKE_DRIVE_OFFLINE') == '1':
    sys.exit(1)
def save():
    path.write_text(json.dumps(data, ensure_ascii=False))
def arg(flag):
    return a[a.index(flag)+1]
if a[:2] == ['backend','query']:
    expression=a[3]
    parents=re.findall(r"'([A-Za-z0-9_-]+)' in parents",expression)
    match=re.search(r"name = '([^']+)'",expression)
    found=[e for e in data['items'] if any(p in e['parents'] for p in parents)]
    if match:
        found=[e for e in found if e['name']==match.group(1)]
    if "mimeType = 'application/vnd.google-apps.folder'" in expression:
        found=[e for e in found if e['mimeType']=='application/vnd.google-apps.folder']
    print(json.dumps(found, ensure_ascii=False) if found else 'null')
elif a[0] == 'mkdir':
    parent=arg('--drive-root-folder-id')
    name=a[1].split(':',1)[1]
    if not any(e['name']==name and parent in e['parents'] for e in data['items']):
        data['items'].append({'id':uuid.uuid4().hex,'name':name,'parents':[parent],
                              'mimeType':'application/vnd.google-apps.folder'})
    save()
elif a[0] == 'copyto':
    assert '--immutable' in a and '--ignore-existing' in a
    parent=arg('--drive-root-folder-id')
    name=a[2].split(':',1)[1]
    body=Path(a[1]).read_text()
    if not any(e['name']==name and parent in e['parents'] for e in data['items']):
        data['items'].append({'id':uuid.uuid4().hex,'name':name,'parents':[parent],
                              'mimeType':'text/markdown','body':body,
                              'md5Checksum':hashlib.md5(body.encode()).hexdigest()})
    save()
elif a[0] == 'cat':
    parent=arg('--drive-root-folder-id')
    name=a[1].split(':',1)[1]
    found=[e for e in data['items'] if e['name']==name and parent in e['parents']]
    if len(found)!=1: sys.exit(1)
    print(found[0]['body'],end='')
else:
    sys.exit(2)
'''


class HistoryCLITests(unittest.TestCase):
    def test_cli_upload_offline_queue_retry_and_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / 'rclone'
            fake.write_text(FAKE_RCLONE, encoding='utf-8')
            fake.chmod(0o700)
            store = root / 'drive.json'
            folder_mime = 'application/vnd.google-apps.folder'
            store.write_text(json.dumps({'items': [
                {'id': 'year', 'name': '2026', 'parents': ['library'], 'mimeType': folder_mime},
                {'id': 'task', 'name': '01_TEST', 'parents': ['year'], 'mimeType': folder_mime},
            ]}), encoding='utf-8')
            config = root / 'config.json'
            config.write_text(json.dumps({'schema_version': 1, 'year_parent': {'id': 'library'},
                'active_year': {'mode': 'system', 'override': 2026},
                'task_number_regex': r'^(?P<number>0*[1-9][0-9]{0,2})_',
                'cache': {'directory': str(root / 'cache'), 'max_age_hours': 24,
                          'max_parent_ids_per_index_query': 10, 'max_parent_queries': 20}}), encoding='utf-8')
            host_session = os.environ.get('CODEX_SESSION_ID', '')
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', host_session):
                host_session = 'synthetic_cli_session'
            env = {**os.environ, 'PATH': str(root) + os.pathsep + os.environ['PATH'],
                   'FAKE_DRIVE_STORE': str(store), 'CODEX_SESSION_ID': host_session}
            state = root / '.codex/drive-work-resume'
            hook_path = Path.home() / '.codex/hooks/completion_audit.py'
            hook = None
            if hook_path.exists():
                spec = importlib.util.spec_from_file_location('completion_audit_integration', hook_path)
                hook = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(hook)
            def dirty():
                if hook is None or not hasattr(hook, 'has_dirty_work'):
                    return None  # Hook integration is optional outside this installation.
                with patch.object(hook.Path, 'home', return_value=root):
                    return hook.has_dirty_work({'session_id': host_session})
            def cli(*args, data=None, offline=False):
                process = subprocess.run([sys.executable, str(SCRIPT), '--config', str(config),
                    '--state-dir', str(state), *args], text=True, capture_output=True,
                    input=json.dumps(data) if data is not None else None,
                    env={**env, 'FAKE_DRIVE_OFFLINE': '1' if offline else '0'}, timeout=20)
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                return json.loads(process.stdout)
            cli('bind', '--task', '1')
            if hook is not None and hasattr(hook, 'has_dirty_work'):
                self.assertTrue(dirty())
            first = cli('checkpoint', data={'goal': 'synthetic', 'done': ['first'], 'next': ['second']})
            self.assertEqual(first['sync']['pending'], 0)
            if hook is not None and hasattr(hook, 'has_dirty_work'):
                self.assertFalse(dirty())
            cli('mark')
            if hook is not None and hasattr(hook, 'has_dirty_work'):
                self.assertTrue(dirty())
            second = cli('checkpoint', data={'goal': 'synthetic', 'done': ['second'], 'next': ['third']}, offline=True)
            self.assertEqual(second['sync']['pending'], 1)
            if hook is not None and hasattr(hook, 'has_dirty_work'):
                self.assertFalse(dirty())
            resumed = cli('read', '--task', '1')
            self.assertEqual(resumed['sync']['delivered'], 1)
            self.assertEqual(resumed['pending'], 0)
            self.assertEqual(resumed['records'][0]['filename'], second['filename'])
            self.assertIn('third', resumed['records'][0]['body'])
            records = [item for item in json.loads(store.read_text())['items'] if item['mimeType'] == 'text/markdown']
            self.assertEqual(len(records), 2)


if __name__ == '__main__':
    unittest.main()
