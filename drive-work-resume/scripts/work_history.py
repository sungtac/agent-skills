#!/usr/bin/env python3
"""Checkpoint and resume a single verified Google Drive work folder."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid
from zoneinfo import ZoneInfo

from drive_work_resume import (DEFAULT_CONFIG, FOLDER_MIME, HISTORY_FOLDER, NAME_RE, RcloneDrive,
                               TaskDeliveryError, WorkError, current_year, drive_id, file_url,
                               parent_filter, quote_drive, read_config, resolve_task,
                               write_file_atomically)

STATE_DIR = Path.home() / '.codex/drive-work-resume'
SESSION_RE = re.compile(r'^[A-Za-z0-9_-]{1,128}$')
FIELDS = ('goal', 'discussion', 'decisions', 'done', 'pending', 'next', 'links')


def private_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)


def atomic_write(path: Path, contents: str) -> None:
    private_dir(path.parent)
    write_file_atomically(path, contents, mode=0o600)


@contextmanager
def lock(state: Path):
    private_dir(state)
    fd = os.open(state / 'history.lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def session_id() -> str:
    # Provider-neutral: Codex and Claude Code each export their own host session ID.
    value = os.environ.get('CODEX_SESSION_ID') or os.environ.get('CLAUDE_CODE_SESSION_ID') or ''
    if not SESSION_RE.fullmatch(value):
        raise WorkError('Host session ID (CODEX_SESSION_ID or CLAUDE_CODE_SESSION_ID) is unavailable; '
                        'automatic task binding is disabled')
    return value


def session_file(state: Path, session: str) -> Path:
    if not SESSION_RE.fullmatch(session):
        raise WorkError('Invalid host session ID')
    return state / 'sessions' / (session + '.json')


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise WorkError('Local history state is unavailable or invalid') from exc


def session_state(state: Path, session: str) -> dict:
    path = session_file(state, session)
    if not path.exists():
        return {}
    value = read_json(path)
    if not isinstance(value, dict):
        raise WorkError('Local session state is invalid')
    return value


def save_session(state: Path, session: str, value: dict) -> None:
    atomic_write(session_file(state, session), json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def resolve(drive, config: dict, number: str | None = None, name: str | None = None) -> dict:
    if (number is None) == (name is None):
        raise WorkError('Select exactly one task number or exact folder name')
    if number is not None and not re.fullmatch(r'0*[1-9][0-9]{0,2}', number):
        raise WorkError('Task number must be a numbered folder prefix')
    year = drive.list_year(config)
    folders = drive.list_books(drive_id(year['id']))
    if number is not None:
        folder = resolve_task(folders, str(int(number)), config['task_number_regex'])
    else:
        matches = [entry for entry in folders if entry.get('name') == name]
        if len(matches) != 1:
            raise WorkError(f'Exact task name has {len(matches)} matching folders; do not guess')
        folder = matches[0]
    task = {'id': drive_id(folder['id']), 'name': folder['name'], 'number': str(int(number)) if number else None,
            'year': current_year(config), 'url': file_url(folder)}
    if drive.source != 'drive':  # Drive tasks keep their historical shape
        task['source'] = drive.source
    return task


def bind(state: Path, session: str, task: dict, dirty: bool = True) -> dict:
    with lock(state):
        old = session_state(state, session)
        if old.get('dirty') and old.get('task', {}).get('id') != task['id']:
            old_source = old.get('task', {}).get('source', 'drive')
            if old_source != task.get('source', 'drive'):
                # Without this hint a source switch leaves the session stuck:
                # the other backend refuses to file the old task (see checkpoint).
                raise WorkError(f'Previous task has unsaved work in the {old_source} work library; '
                                f'switch the config source back to {old_source} and checkpoint it '
                                'before switching tasks')
            raise WorkError('Previous task has unsaved work; checkpoint it before switching tasks')
        value = {'schema_version': 1, 'task': task, 'dirty': bool(dirty or old.get('dirty'))}
        save_session(state, session, value)
        return value


def binding(state: Path, session: str) -> dict:
    value = session_state(state, session)
    task = value.get('task')
    if not isinstance(task, dict):
        raise WorkError('No task is bound to this host session')
    drive_id(task.get('id'))
    return task


def mark(state: Path, session: str) -> dict:
    with lock(state):
        value = session_state(state, session)
        if not isinstance(value.get('task'), dict):
            raise WorkError('No task is bound to this host session')
        drive_id(value['task'].get('id'))
        value['dirty'] = True
        save_session(state, session, value)
        return value


def validate_task(drive, config: dict, task: dict) -> dict:
    # Recheck the original year so queued work remains deliverable after New Year.
    year = str(task.get('year', ''))
    if not re.fullmatch(r'\d{4}', year):
        raise WorkError('Stored task year is invalid')
    old_config = {**config, 'active_year': {**config['active_year'], 'override': year}}
    target_year = drive.list_year(old_config)
    matches = [entry for entry in drive.list_books(drive_id(target_year['id']))
               if entry.get('id') == task.get('id')]
    if len(matches) != 1:
        raise TaskDeliveryError('The bound task is no longer a verified direct child of its year folder')
    return matches[0]


def validate_snapshot(value) -> dict:
    if not isinstance(value, dict) or set(value) - set(FIELDS):
        raise WorkError('Snapshot must be an object with only the documented fields')
    clean = {}
    for field in FIELDS:
        raw = value.get(field, [])
        if isinstance(raw, str):
            raw = [raw] if raw.strip() else []
        if not isinstance(raw, list) or len(raw) > 40 or any(not isinstance(x, str) for x in raw):
            raise WorkError('Each snapshot field must be text or a list of at most 40 text items')
        clean[field] = [x.strip() for x in raw if x.strip()]
        if any(len(x) > 4000 for x in clean[field]):
            raise WorkError('Snapshot item is too long')
    if not clean['goal'] or not (clean['done'] or clean['pending'] or clean['next']):
        raise WorkError('Snapshot needs a goal and at least one completed, pending, or next item')
    if len(json.dumps(clean, ensure_ascii=False)) > 40000:
        raise WorkError('Snapshot is too long')
    return clean


def render(task: dict, snapshot: dict, stamp: datetime, event: str) -> str:
    labels = {'goal': '업무 목표', 'discussion': '논의 요약', 'decisions': '결정 사항',
              'done': '완료한 일', 'pending': '남은 일과 확인 사항', 'next': '다음에 할 일', 'links': '관련 파일'}
    lines = ['# 업무 진행 기록', '', f'- 기록 시각: {stamp.isoformat()}',
             f'- 업무: {task["name"]}', f'- 기록 ID: {event}', '']
    for field in FIELDS:
        lines.extend(['## ' + labels[field], ''])
        lines.extend(['- ' + item.replace('\n', '\n  ') for item in snapshot[field]] or ['- 없음'])
        lines.append('')
    return '\n'.join(lines)


def valid_envelope(value) -> dict:
    if not isinstance(value, dict) or value.get('schema_version') != 1:
        raise WorkError('Invalid local outbox record')
    filename = value.get('filename', '')
    match = NAME_RE.fullmatch(filename) if isinstance(filename, str) else None
    if not match:
        raise WorkError('Invalid local outbox filename')
    try:
        datetime.strptime('_'.join(match.groups()[:3]), '%Y-%m-%d_%H%M%S_%f')
    except ValueError as exc:
        raise WorkError('Invalid local outbox timestamp') from exc
    task = value.get('task')
    if not isinstance(task, dict) or not isinstance(task.get('name'), str):
        raise WorkError('Invalid local outbox task')
    drive_id(task.get('id'))
    if not isinstance(value.get('body'), str) or len(value['body']) > 100000:
        raise WorkError('Invalid local outbox body')
    return value


def queued(state: Path, task_id: str | None = None, outbox: str = 'outbox') -> list[tuple[Path, dict]]:
    # Each backend keeps its own outbox directory so a queued record is only
    # ever delivered by the backend that created it.
    folder = state / outbox
    if not folder.exists():
        return []
    result = []
    for path in sorted(folder.glob('*.json')):
        value = valid_envelope(read_json(path))
        if task_id is None or value['task']['id'] == task_id:
            result.append((path, value))
    return result


class HistoryDrive(RcloneDrive):
    creates_books = False  # sync never creates task folders on the owner's Drive

    def command(self, args: list[str]) -> str:
        command = ['rclone', *args, '--retries', '1', '--low-level-retries', '6',
                   '--contimeout', '8s', '--timeout', '45s']
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=70, check=False)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise WorkError('Google Drive operation could not be completed') from exc
        if result.returncode:
            raise WorkError('Google Drive operation failed; check connection, permission, or quota')
        return result.stdout

    def children(self, parent: str, name: str | None = None) -> list[dict]:
        expression = f'{parent_filter([parent])} and trashed = false'
        if name is not None:
            expression += f' and name = {quote_drive(name)}'
        return [entry for entry in self.query(expression)
                if parent in (entry.get('parents') or []) and (name is None or entry.get('name') == name)]

    def history_folder(self, task_id: str, create: bool) -> str | None:
        matches = self.children(task_id, HISTORY_FOLDER)
        if not matches and create:
            self.command(['mkdir', self.remote + HISTORY_FOLDER, '--drive-root-folder-id', task_id])
            matches = self.children(task_id, HISTORY_FOLDER)
        if not matches:
            return None
        if len(matches) != 1 or matches[0].get('mimeType') != FOLDER_MIME:
            raise TaskDeliveryError('History folder name is ambiguous or is not a folder')
        return drive_id(matches[0].get('id'))

    def upload(self, folder: str, filename: str, body: str) -> None:
        # Local per-host lock + immutable names; never overwrite an existing remote file.
        existing = self.children(folder, filename)
        if len(existing) > 1:
            raise TaskDeliveryError('Duplicate remote history filename; manual resolution required')
        if not existing:
            with tempfile.NamedTemporaryFile('w', encoding='utf-8', delete=False) as handle:
                local = handle.name
                os.fchmod(handle.fileno(), 0o600)
                handle.write(body)
            try:
                self.command(['copyto', local, self.remote + filename, '--drive-root-folder-id', folder,
                              '--immutable', '--ignore-existing'])
            finally:
                os.unlink(local)
            existing = self.children(folder, filename)
        if len(existing) != 1 or existing[0].get('mimeType') == FOLDER_MIME:
            raise TaskDeliveryError('Uploaded history could not be uniquely verified')
        checksum = existing[0].get('md5Checksum')
        expected = hashlib.md5(body.encode('utf-8')).hexdigest()
        if checksum:
            if checksum != expected:
                raise TaskDeliveryError('Remote history content conflicts with the queued record')
        elif self.download(folder, filename) != body:
            raise TaskDeliveryError('Remote history content conflicts with the queued record')

    def download(self, folder: str, filename: str, strict: bool = False) -> str:
        # rclone either returns the exact body or fails, so strict needs no extra check.
        if not NAME_RE.fullmatch(filename):
            raise WorkError('Invalid history filename')
        return self.command(['cat', self.remote + filename, '--drive-root-folder-id', folder])

    def ensure_book(self, config: dict, name: str) -> dict:
        # Task folders on Drive belong to the owner; history sync never creates them.
        raise TaskDeliveryError(f"Task folder '{name}' does not exist on Drive; "
                                'create it there to sync its history')


def flush_locked(drive, config: dict, state: Path, task_id: str | None = None) -> dict:
    delivered = 0
    failures = []
    blocked_tasks = set()
    for path, value in queued(state, task_id, drive.outbox):
        if value['task']['id'] in blocked_tasks:
            continue
        try:
            task = value['task']
            validate_task(drive, config, task)
            folder = drive.history_folder(task['id'], create=True)
            drive.upload(folder, value['filename'], value['body'])
            path.unlink()
            delivered += 1
        except TaskDeliveryError as exc:
            failures.append(str(exc))
            blocked_tasks.add(value['task']['id'])
        except (WorkError, OSError) as exc:
            failures.append(str(exc))
            break  # Avoid repeated network failures; retain this and later items.
    remaining = len(queued(state, task_id, drive.outbox))
    return {'delivered': delivered, 'pending': remaining, 'issues': list(dict.fromkeys(failures))}


def flush(drive, config: dict, state: Path, task_id: str | None = None) -> dict:
    with lock(state):
        return flush_locked(drive, config, state, task_id)


def checkpoint(drive, config: dict, state: Path, session: str, snapshot, now: datetime | None = None) -> dict:
    snapshot = validate_snapshot(snapshot)
    with lock(state):
        task = binding(state, session)
        # A task bound under one work library must never be filed into another.
        bound_source = task.get('source', 'drive')
        if bound_source != drive.source:
            raise WorkError(f'The bound task belongs to a different work library ({bound_source}); '
                            f'switch the config source back to {bound_source} to checkpoint it')
        # Offline should not lose a summary: verified binding is checked again during delivery.
        stamp = now or datetime.now(ZoneInfo('Asia/Seoul'))
        if stamp.tzinfo is None:
            raise WorkError('Checkpoint time must include a timezone')
        stamp = stamp.astimezone(ZoneInfo('Asia/Seoul'))
        event = uuid.uuid4().hex
        filename = stamp.strftime('%Y-%m-%d_%H%M%S_%f_') + event + '.md'
        envelope = {'schema_version': 1, 'task': task, 'filename': filename,
                    'body': render(task, snapshot, stamp, event)}
        atomic_write(state / drive.outbox / (event + '.json'), json.dumps(envelope, ensure_ascii=False) + '\n')
        try:
            current = session_state(state, session)
            if current.get('task', {}).get('id') == task['id']:
                current['dirty'] = False
                save_session(state, session, current)
            outcome = flush_locked(drive, config, state, task['id'])
        except (WorkError, OSError) as exc:
            # The event is already durable. Do not misreport it as lost merely
            # because a corrupt queue or session-state failure prevented sync.
            outcome = {'delivered': 0, 'pending': None, 'issues': [str(exc)]}
        return {'task': task['name'], 'filename': filename, 'stored_locally': True, 'sync': outcome}


def read_history(drive, config: dict, state: Path, task: dict, start: date | None,
                 end: date | None, limit: int, before: str | None = None) -> dict:
    if start and end and start > end:
        raise WorkError('Start date must not be after end date')
    if not 1 <= limit <= 100:
        raise WorkError('Limit must be between 1 and 100')
    if before is not None and not NAME_RE.fullmatch(before):
        raise WorkError('Invalid history pagination cursor')
    validate_task(drive, config, task)
    candidates: dict[str, dict] = {}
    # Keep local flushes from moving an entry between the remote and outbox
    # snapshots while this read is collecting their metadata.
    with lock(state):
        folder = drive.history_folder(task['id'], create=False)
        if folder:
            for item in drive.children(folder):
                name = item.get('name', '')
                match = NAME_RE.fullmatch(name) if isinstance(name, str) else None
                if not match or item.get('mimeType') == FOLDER_MIME:
                    continue
                try:
                    day = date.fromisoformat(match.group(1))
                except ValueError:
                    continue
                if (start and day < start) or (end and day > end):
                    continue
                if name in candidates:
                    raise WorkError('Duplicate remote history filename; manual resolution required')
                candidates[name] = {'source': drive.source, 'item': item}
        local_records = queued(state, task['id'], drive.outbox)
    for _, value in local_records:
        name = value['filename']
        day = date.fromisoformat(NAME_RE.fullmatch(name).group(1))
        if (start and day < start) or (end and day > end):
            continue
        # Detect conflicts even if an upload succeeded but verification failed.
        if name in candidates:
            checksum = candidates[name]['item'].get('md5Checksum')
            if checksum and checksum != hashlib.md5(value['body'].encode('utf-8')).hexdigest():
                raise WorkError('Remote history content conflicts with the queued record')
            if not checksum and drive.download(folder, name) != value['body']:
                raise WorkError('Remote history content conflicts with the queued record')
        # Prefer the local record when delivery status is uncertain, and expose that status.
        candidates[name] = {'source': 'pending', 'body': value['body']}
    names = sorted((name for name in candidates if before is None or name < before), reverse=True)
    result = []
    for name in names[:limit]:
        entry = candidates[name]
        body = entry.get('body') if entry['source'] == 'pending' else drive.download(folder, name)
        result.append({'filename': name, 'source': entry['source'], 'body': body,
                       'url': file_url(entry['item']) if entry['source'] != 'pending' else None})
    return {'task': task['name'], 'records': result, 'matched': len(names),
            'truncated': len(names) > limit,
            'next_before': names[limit - 1] if len(names) > limit else None,
            'pending': len(local_records)}


def make_backend(config: dict):
    """Select the work-library backend once from the config normalized by read_config."""
    source = config.get('_source')
    if source is None:
        # A raw config that names a source was never validated; silently falling
        # back to Drive would run rclone against the wrong library.
        if config.get('source') is not None:
            raise WorkError('Configuration must be loaded with read_config before use')
        source = {'type': 'drive'}
    if source['type'] == 'local':
        from local_source import LocalBackend
        return LocalBackend()
    return HistoryDrive(config.get('rclone_remote', 'gdrive:'))


def make_mirror(config: dict):
    """(mirror backend, config view for it), or None when no mirror is configured."""
    mirror = config.get('_mirror')
    if mirror is None:
        if config.get('mirror') is not None:
            raise WorkError('Configuration must be loaded with read_config before use')
        return None
    view = {**config, '_source': mirror}
    return make_backend(view), view


def _records(backend, book: dict) -> tuple[str | None, dict[str, dict]]:
    folder = backend.history_folder(book['id'], create=False)
    if not folder:
        return None, {}
    records = {}
    for item in backend.children(folder):
        name = item.get('name')
        if isinstance(name, str) and NAME_RE.fullmatch(name) and item.get('mimeType') != FOLDER_MIME:
            records[name] = item
    return folder, records


def _same_record(a, a_folder: str, a_item: dict, b, b_folder: str, b_item: dict, name: str) -> bool:
    a_sum, b_sum = a_item.get('md5Checksum'), b_item.get('md5Checksum')
    if a_sum and b_sum:
        return a_sum == b_sum
    return a.download(a_folder, name, strict=True) == b.download(b_folder, name, strict=True)


def _books(backend, config: dict) -> dict[str, dict]:
    year = backend.list_year(config)
    return {book['name']: book for book in backend.list_books(drive_id(year['id']))}


def sync_history(primary, config: dict, mirror, mirror_config: dict, names: set | None = None) -> dict:
    """Union-merge work-history records between two libraries, matched by task folder name.

    Records are immutable dated files, so a record found on only one side is copied
    to the other. Nothing is ever overwritten or deleted: same-named records with
    different content are reported as conflicts and left as they are. A missing task
    folder is created only where the backend allows it (local); Drive task folders
    belong to the owner and are never created.
    """
    report = {'books': 0, 'to_mirror': 0, 'to_primary': 0,
              'conflicts': [], 'skipped': [], 'issues': []}
    primary_books = _books(primary, config)
    try:
        mirror_books = _books(mirror, mirror_config)
    except WorkError as exc:
        if not mirror.creates_books:  # cannot be repaired here, e.g. Drive unreachable
            report['issues'].append(str(exc))
            report['complete'] = False
            return report
        mirror_books = {}  # a new local mirror: its year folder is created on demand
    targets = sorted(set(primary_books) | set(mirror_books), key=str.casefold)
    if names is not None:
        targets = [name for name in targets if name in names]
    for name in targets:
        try:
            p_book, m_book = primary_books.get(name), mirror_books.get(name)
            p_folder, p_records = _records(primary, p_book) if p_book else (None, {})
            m_folder, m_records = _records(mirror, m_book) if m_book else (None, {})
            if not p_records and not m_records:
                continue
            if p_book is None:
                p_book = primary.ensure_book(config, name)
            if m_book is None:
                m_book = mirror.ensure_book(mirror_config, name)
            report['books'] += 1
            for record in sorted(set(p_records) | set(m_records)):
                if record in p_records and record in m_records:
                    if not _same_record(primary, p_folder, p_records[record],
                                        mirror, m_folder, m_records[record], record):
                        report['conflicts'].append(f'{name}/{record}')
                    continue
                if record in p_records:
                    body = primary.download(p_folder, record, strict=True)
                    m_folder = m_folder or mirror.history_folder(m_book['id'], create=True)
                    mirror.upload(m_folder, record, body)
                    report['to_mirror'] += 1
                else:
                    body = mirror.download(m_folder, record, strict=True)
                    p_folder = p_folder or primary.history_folder(p_book['id'], create=True)
                    primary.upload(p_folder, record, body)
                    report['to_primary'] += 1
        except TaskDeliveryError as exc:
            report['skipped'].append(f'{name}: {exc}')
        except (WorkError, OSError) as exc:
            report['issues'].append(str(exc))
            break  # a library or network failure: stop instead of repeating it per task
    report['complete'] = not (report['conflicts'] or report['skipped'] or report['issues'])
    return report


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('Use YYYY-MM-DD') from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--state-dir', type=Path, default=STATE_DIR)
    sub = parser.add_subparsers(dest='command', required=True)
    bind_parser = sub.add_parser('bind')
    bind_target = bind_parser.add_mutually_exclusive_group(required=True)
    bind_target.add_argument('--task')
    bind_target.add_argument('--name', help='Exact direct-child folder name')
    sub.add_parser('mark')
    cp = sub.add_parser('checkpoint')
    cp.add_argument('--input', type=Path, help='Snapshot JSON file; stdin if omitted')
    sub.add_parser('flush')
    sy = sub.add_parser('sync', help='Union-merge work history with the configured mirror library')
    sync_target = sy.add_mutually_exclusive_group()
    sync_target.add_argument('--task', help='Only this numbered task (default: every task)')
    sync_target.add_argument('--name', help='Only this exact direct-child folder name')
    rd = sub.add_parser('read')
    read_target = rd.add_mutually_exclusive_group(required=True)
    read_target.add_argument('--task')
    read_target.add_argument('--name', help='Exact direct-child folder name')
    rd.add_argument('--from', dest='start', type=parse_date)
    rd.add_argument('--to', dest='end', type=parse_date)
    rd.add_argument('--limit', type=int, default=1)
    rd.add_argument('--before', help='The next_before value from the prior page')
    args = parser.parse_args()
    try:
        config = read_config(args.config)
        drive = make_backend(config)
        if args.command == 'bind':
            result = {'binding': bind(args.state_dir, session_id(), resolve(drive, config, args.task, args.name)),
                      'sync': flush(drive, config, args.state_dir)}
        elif args.command == 'mark':
            result = {'binding': mark(args.state_dir, session_id()), 'sync': flush(drive, config, args.state_dir)}
        elif args.command == 'checkpoint':
            data = json.loads(args.input.read_text(encoding='utf-8') if args.input else sys.stdin.read())
            result = checkpoint(drive, config, args.state_dir, session_id(), data)
            # Keep the mirror current after every checkpoint; a sync failure never
            # hides the checkpoint result itself.
            mirror = make_mirror(config)
            if mirror:
                try:
                    result['mirror_sync'] = sync_history(drive, config, *mirror, names={result['task']})
                except (WorkError, OSError) as exc:
                    result['mirror_sync_error'] = str(exc)
        elif args.command == 'sync':
            mirror = make_mirror(config)
            if not mirror:
                raise WorkError('No mirror library is configured; add "mirror" to the configuration')
            names = None
            if args.task or args.name:
                names = {resolve(drive, config, args.task, args.name)['name']}
            result = {'flush': flush(drive, config, args.state_dir),
                      'mirror_sync': sync_history(drive, config, *mirror, names=names)}
        elif args.command == 'flush':
            result = flush(drive, config, args.state_dir)
        else:
            task = resolve(drive, config, args.task, args.name)
            sync = flush(drive, config, args.state_dir)
            result = read_history(drive, config, args.state_dir, task, args.start, args.end, args.limit, args.before)
            if sync['pending'] or sync['delivered'] or sync['issues']:
                result['sync'] = sync
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (WorkError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
