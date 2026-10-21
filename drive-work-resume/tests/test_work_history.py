import hashlib
import os
import re
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from drive_work_resume import FOLDER_MIME, WorkError
from work_history import (HistoryDrive, bind, checkpoint, flush, queued, read_history,
                          resolve, session_state, validate_snapshot)


def item(item_id, name, parent, mime=FOLDER_MIME):
    return {'id': item_id, 'name': name, 'parents': [parent], 'mimeType': mime}


class FakeHistoryDrive(HistoryDrive):
    # Inherits the backend interface (source/outbox/list_year/list_books); the
    # Drive transport methods below are faked.
    def __init__(self):
        self.items = [item('year', '2026', 'library'), item('task', '01_업무', 'year'),
                      item('taskB', '02_업무', 'year'), item('unnumbered', '업무 이름', 'year')]
        self.records = {}
        self.offline = False
        self.downloaded = []

    def query(self, expression):
        if self.offline:
            raise WorkError('simulated offline')
        parents = re.findall(r"'([A-Za-z0-9_-]+)' in parents", expression)
        entries = [x for x in self.items if any(p in parents for p in x['parents'])]
        if f"mimeType = '{FOLDER_MIME}'" in expression:
            entries = [x for x in entries if x['mimeType'] == FOLDER_MIME]
        if "name = '2026'" in expression:
            entries = [x for x in entries if x['name'] == '2026']
        return entries

    def history_folder(self, task_id, create):
        if self.offline:
            raise WorkError('simulated offline')
        if create:
            self.records.setdefault(task_id, {})
        return task_id if task_id in self.records else None

    def upload(self, folder, filename, body):
        if self.offline:
            raise WorkError('simulated offline')
        if filename in self.records[folder] and self.records[folder][filename] != body:
            raise WorkError('simulated conflict')
        self.records[folder][filename] = body

    def children(self, folder):
        return [item('file_' + str(i), name, folder, 'text/markdown')
                for i, name in enumerate(self.records[folder])]

    def download(self, folder, filename):
        self.downloaded.append(filename)
        return self.records[folder][filename]


class WorkHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / 'state'
        self.session = 'host_session_1'
        self.config = {'year_parent': {'id': 'library'},
                       'active_year': {'mode': 'system', 'override': 2026},
                       'task_number_regex': r'^(?P<number>0*[1-9][0-9]{0,2})_'}
        self.drive = FakeHistoryDrive()
        self.task = resolve(self.drive, self.config, '1')
        self.snapshot = {'goal': '과제 준비', 'discussion': ['일정 논의'], 'decisions': ['방향 결정'],
                         'done': ['자료 조사'], 'pending': ['검토'], 'next': ['초안 작성'], 'links': []}
        bind(self.state, self.session, self.task)

    def at(self, day, hour=10):
        return datetime(2026, 10, day, hour, tzinfo=ZoneInfo('Asia/Seoul'))

    def test_resolves_unnumbered_exact_name_and_refuses_ambiguous_number(self):
        self.assertEqual(resolve(self.drive, self.config, name='업무 이름')['id'], 'unnumbered')
        self.drive.items.append(item('duplicate', '1_다른업무', 'year'))
        with self.assertRaises(WorkError):
            resolve(self.drive, self.config, '1')

    def test_switch_requires_previous_checkpoint(self):
        other = resolve(self.drive, self.config, '2')
        with self.assertRaisesRegex(WorkError, 'unsaved'):
            bind(self.state, self.session, other)
        checkpoint(self.drive, self.config, self.state, self.session, self.snapshot, self.at(1))
        bind(self.state, self.session, other)
        self.assertEqual(session_state(self.state, self.session)['task']['id'], 'taskB')

    def test_offline_queue_private_retry_and_no_duplicate(self):
        self.drive.offline = True
        response = checkpoint(self.drive, self.config, self.state, self.session, self.snapshot, self.at(1))
        self.assertEqual(response['sync']['pending'], 1)
        self.assertFalse(session_state(self.state, self.session)['dirty'])
        outbox_path, envelope = queued(self.state)[0]
        self.assertEqual(outbox_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(outbox_path.parent.stat().st_mode & 0o777, 0o700)
        self.drive.offline = False
        result = flush(self.drive, self.config, self.state)
        self.assertEqual((result['delivered'], result['pending']), (1, 0))
        # A retry of the same persisted event verifies the same remote content and is idempotent.
        from work_history import atomic_write
        import json
        atomic_write(outbox_path, json.dumps(envelope, ensure_ascii=False))
        self.assertEqual(flush(self.drive, self.config, self.state)['delivered'], 1)
        self.assertEqual(len(self.drive.records['task']), 1)

    def test_conflict_and_moved_task_keep_queue(self):
        self.drive.offline = True
        checkpoint(self.drive, self.config, self.state, self.session, self.snapshot, self.at(1))
        path, entry = queued(self.state)[0]
        self.drive.offline = False
        self.drive.records['task'] = {entry['filename']: 'unexpected'}
        result = flush(self.drive, self.config, self.state)
        self.assertEqual(result['pending'], 1)
        self.assertEqual(self.drive.records['task'][entry['filename']], 'unexpected')
        self.drive.items[1]['parents'] = ['elsewhere']
        result = flush(self.drive, self.config, self.state)
        self.assertEqual(result['pending'], 1)
        self.assertTrue(path.exists())

    def test_one_moved_task_does_not_block_other_queued_tasks(self):
        task_b = resolve(self.drive, self.config, '2')
        bind(self.state, 'another_session', task_b)
        self.drive.offline = True
        checkpoint(self.drive, self.config, self.state, self.session, self.snapshot, self.at(1))
        checkpoint(self.drive, self.config, self.state, 'another_session', self.snapshot, self.at(1))
        self.drive.offline = False
        self.drive.items[1]['parents'] = ['elsewhere']
        result = flush(self.drive, self.config, self.state)
        self.assertEqual((result['delivered'], result['pending']), (1, 1))
        self.assertEqual(len(self.drive.records['taskB']), 1)
        self.assertEqual(queued(self.state)[0][1]['task']['id'], 'task')

    def test_concurrent_checkpoints_remain_separate(self):
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(
                lambda day: checkpoint(self.drive, self.config, self.state, self.session,
                                       self.snapshot, self.at(day)), range(1, 9)))
        self.assertEqual(len({entry['filename'] for entry in results}), 8)
        self.assertEqual(len(self.drive.records['task']), 8)
        self.assertEqual(len(queued(self.state)), 0)

    def test_resume_does_not_lose_a_record_during_concurrent_flush(self):
        self.drive.offline = True
        checkpoint(self.drive, self.config, self.state, self.session, self.snapshot, self.at(1))
        self.drive.offline = False
        self.drive.records['task'] = {}
        original_children = self.drive.children
        started = Event()
        with ThreadPoolExecutor(max_workers=1) as executor:
            def concurrent_flush():
                started.set()
                return flush(self.drive, self.config, self.state)
            def children(folder):
                self.future = executor.submit(concurrent_flush)
                self.assertTrue(started.wait(2))
                return original_children(folder)
            self.drive.children = children
            result = read_history(self.drive, self.config, self.state, self.task, None, None, 1)
            self.assertEqual(len(result['records']), 1)
            self.assertEqual(result['records'][0]['source'], 'pending')
            self.assertEqual(self.future.result(timeout=5)['delivered'], 1)

    def test_different_session_cannot_implicitly_reuse_binding(self):
        with self.assertRaisesRegex(WorkError, 'No task is bound'):
            checkpoint(self.drive, self.config, self.state, 'another_session', self.snapshot, self.at(1))

    def test_pending_and_remote_conflict_is_visible_at_resume(self):
        self.drive.offline = True
        checkpoint(self.drive, self.config, self.state, self.session, self.snapshot, self.at(1))
        _, envelope = queued(self.state)[0]
        self.drive.offline = False
        self.drive.records['task'] = {envelope['filename']: 'conflict'}
        # Simulate the checksum returned by real Drive metadata.
        original = self.drive.children
        def children(folder):
            return [{**entry, 'md5Checksum': hashlib.md5(b'conflict').hexdigest()}
                    for entry in original(folder)]
        self.drive.children = children
        with self.assertRaisesRegex(WorkError, 'conflicts'):
            read_history(self.drive, self.config, self.state, self.task, None, None, 1)
        self.drive.children = original
        with self.assertRaisesRegex(WorkError, 'conflicts'):
            read_history(self.drive, self.config, self.state, self.task, None, None, 1)

    def test_latest_and_inclusive_range_read_only_selected_bodies(self):
        for day in (1, 3, 5):
            checkpoint(self.drive, self.config, self.state, self.session, self.snapshot, self.at(day))
        latest = read_history(self.drive, self.config, self.state, self.task, None, None, 1)
        self.assertTrue(latest['records'][0]['filename'].startswith('2026-10-05'))
        self.assertTrue(latest['truncated'])
        self.assertEqual(len(self.drive.downloaded), 1)
        self.drive.downloaded.clear()
        selected = read_history(self.drive, self.config, self.state, self.task, date(2026, 10, 1), date(2026, 10, 3), 10)
        self.assertEqual([r['filename'][:10] for r in selected['records']], ['2026-10-03', '2026-10-01'])
        self.assertEqual(len(self.drive.downloaded), 2)
        page1 = read_history(self.drive, self.config, self.state, self.task, None, None, 2)
        page2 = read_history(self.drive, self.config, self.state, self.task, None, None, 2, page1['next_before'])
        self.assertEqual([r['filename'][:10] for r in page1['records'] + page2['records']],
                         ['2026-10-05', '2026-10-03', '2026-10-01'])
        self.assertIsNone(page2['next_before'])

    def test_snapshot_validation(self):
        with self.assertRaises(WorkError):
            validate_snapshot({'goal': 'goal', 'raw_transcript': 'private', 'next': 'do'})
        with self.assertRaises(WorkError):
            validate_snapshot({'goal': 'goal'})

    def test_corrupt_outbox_is_reported_without_upload(self):
        from work_history import atomic_write
        import json
        path = self.state / 'outbox' / ('a' * 32 + '.json')
        atomic_write(path, json.dumps({'schema_version': 1,
            'filename': '2026-10-01_100000_000000_' + 'a' * 32 + '.md',
            'task': None, 'body': 'test'}))
        with self.assertRaisesRegex(WorkError, 'Invalid local outbox task'):
            flush(self.drive, self.config, self.state)
        self.assertTrue(path.exists())
        self.assertEqual(self.drive.records, {})
        response = checkpoint(self.drive, self.config, self.state, self.session, self.snapshot, self.at(1))
        self.assertTrue(response['stored_locally'])
        self.assertIsNone(response['sync']['pending'])
        self.assertTrue(response['sync']['issues'])
        self.assertEqual(len(list((self.state / 'outbox').glob('*.json'))), 2)

    def test_real_upload_logic_rejects_collision_without_overwrite(self):
        class Simulated(HistoryDrive):
            def __init__(self):
                self.calls = []
            def children(self, folder, name):
                return [{'id': 'file', 'mimeType': 'text/markdown', 'md5Checksum': hashlib.md5(b'other').hexdigest()}]
            def command(self, args):
                self.calls.append(args)
                return ''
        drive = Simulated()
        with self.assertRaisesRegex(WorkError, 'conflicts'):
            drive.upload('folder', '2026-10-01_100000_000000_' + 'a' * 32 + '.md', 'our body')
        self.assertEqual(drive.calls, [])


if __name__ == '__main__':
    unittest.main()
