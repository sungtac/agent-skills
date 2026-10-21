import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from drive_work_resume import FOLDER_MIME, WorkError, read_config
from local_source import MAX_RECORD_BYTES, LocalBackend
import work_history
from work_history import HistoryDrive, sync_history

REGEX = r"^(?P<number>0*[1-9][0-9]{0,2})_"
SEOUL = ZoneInfo("Asia/Seoul")


def record_name(day: int, tag: str) -> str:
    return f"2026-02-{day:02d}_090000_000000_" + tag * 32 + ".md"


class FakeDriveMirror(HistoryDrive):
    """In-memory Drive library; inherits creates_books=False and ensure_book from HistoryDrive."""

    def __init__(self, books=(), records=None, offline=False):
        self.books = list(books)
        self.records = records or {}   # book id -> {filename: body}
        self.offline = offline

    def list_year(self, config):
        if self.offline:
            raise WorkError("simulated offline")
        return {"id": "year", "name": "2026", "mimeType": FOLDER_MIME}

    def list_books(self, parent_id):
        return [{"id": name.replace(" ", "_"), "name": name, "mimeType": FOLDER_MIME} for name in self.books]

    def history_folder(self, task_id, create):
        if create:
            self.records.setdefault(task_id, {})
        return task_id if task_id in self.records else None

    def children(self, folder, name=None):
        return [{"id": f, "name": f, "mimeType": "text/markdown"} for f in self.records[folder]]

    def upload(self, folder, filename, body):
        self.records[folder][filename] = body

    def download(self, folder, filename, strict=False):
        return self.records[folder][filename]


class SyncCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.a, self.b = base / "a", base / "b"
        (self.a / "2026" / "01_기획").mkdir(parents=True)
        (self.a / "2026" / "02_개발").mkdir()
        self.b.mkdir()
        path = base / "config.json"
        path.write_text(json.dumps({
            "schema_version": 1, "active_year": {"mode": "system", "override": "2026"},
            "task_number_regex": REGEX, "source": {"type": "local", "root": str(self.a)},
        }), encoding="utf-8")
        self.config = read_config(path)
        self.mirror_config = {**self.config, "_source": {"type": "local", "root": self.b}}

    def history(self, root, book="01_기획"):
        return root / "2026" / book / "_업무기록"

    def put(self, root, name, body, book="01_기획"):
        folder = self.history(root, book)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(body, encoding="utf-8")

    def sync(self, names=None):
        return sync_history(LocalBackend(), self.config, LocalBackend(), self.mirror_config, names)


class SyncTests(SyncCase):
    def test_new_mirror_receives_records_and_only_books_with_history(self):
        self.put(self.a, record_name(1, "a"), "첫 기록")
        self.put(self.a, record_name(2, "b"), "둘째 기록")
        report = self.sync()
        self.assertEqual((report["books"], report["to_mirror"], report["to_primary"]), (1, 2, 0))
        self.assertTrue(report["complete"])
        self.assertEqual(sorted(p.name for p in self.history(self.b).iterdir()),
                         [record_name(1, "a"), record_name(2, "b")])
        self.assertFalse((self.b / "2026" / "02_개발").exists())

    def test_sync_is_bidirectional_and_idempotent(self):
        self.put(self.a, record_name(1, "a"), "드라이브에서 쓴 기록")
        self.put(self.b, record_name(2, "b"), "로컬에서 쓴 기록")
        first = self.sync()
        self.assertEqual((first["to_mirror"], first["to_primary"]), (1, 1))
        for root in (self.a, self.b):
            self.assertEqual(len(list(self.history(root).iterdir())), 2)
        second = self.sync()
        self.assertEqual((second["to_mirror"], second["to_primary"], second["conflicts"]), (0, 0, []))

    def test_conflict_is_reported_and_nothing_is_overwritten(self):
        name = record_name(3, "c")
        self.put(self.a, name, "원본 A")
        self.put(self.b, name, "다른 B")
        report = self.sync()
        self.assertEqual(report["conflicts"], [f"01_기획/{name}"])
        self.assertFalse(report["complete"])
        self.assertEqual((self.history(self.a) / name).read_text(encoding="utf-8"), "원본 A")
        self.assertEqual((self.history(self.b) / name).read_text(encoding="utf-8"), "다른 B")

    def test_invalid_record_is_never_propagated(self):
        self.put(self.a, record_name(4, "d"), "x" * (MAX_RECORD_BYTES + 1))
        report = self.sync()
        self.assertTrue(report["skipped"])
        self.assertFalse(self.history(self.b).exists() and any(self.history(self.b).iterdir()))

    def test_names_limit_the_sync_to_one_task(self):
        self.put(self.a, record_name(1, "a"), "기획", book="01_기획")
        self.put(self.a, record_name(1, "b"), "개발", book="02_개발")
        report = self.sync(names={"02_개발"})
        self.assertEqual(report["books"], 1)
        self.assertFalse((self.b / "2026" / "01_기획").exists())

    def test_checkpoint_records_reach_the_mirror(self):
        task = work_history.resolve(LocalBackend(), self.config, "1", None)
        state = Path(self.temp.name) / "state"
        work_history.bind(state, "s", task)
        work_history.checkpoint(LocalBackend(), self.config, state, "s",
                                {"goal": "g", "done": ["d"]}, datetime(2026, 2, 5, 9, tzinfo=SEOUL))
        self.assertEqual(self.sync(names={task["name"]})["to_mirror"], 1)


class DriveMirrorTests(SyncCase):
    def test_drive_task_folders_are_never_created(self):
        self.put(self.a, record_name(1, "a"), "기록")
        drive = FakeDriveMirror(books=[])
        report = sync_history(LocalBackend(), self.config, drive, self.config)
        self.assertEqual(report["to_mirror"], 0)
        self.assertIn("does not exist on Drive", report["skipped"][0])
        self.assertEqual(drive.records, {})

    def test_drive_records_come_down_and_local_records_go_up(self):
        self.put(self.a, record_name(1, "a"), "로컬 기록")
        drive = FakeDriveMirror(books=["01_기획"], records={"01_기획": {record_name(2, "b"): "드라이브 기록"}})
        report = sync_history(LocalBackend(), self.config, drive, self.config)
        self.assertEqual((report["to_mirror"], report["to_primary"]), (1, 1))
        self.assertEqual(drive.records["01_기획"][record_name(1, "a")], "로컬 기록")
        self.assertEqual((self.history(self.a) / record_name(2, "b")).read_text(encoding="utf-8"), "드라이브 기록")

    def test_unreachable_drive_stops_without_touching_anything(self):
        self.put(self.a, record_name(1, "a"), "기록")
        report = sync_history(LocalBackend(), self.config, FakeDriveMirror(offline=True), self.config)
        self.assertEqual(report["issues"], ["simulated offline"])
        self.assertFalse(report["complete"])

    def test_drive_records_are_copied_byte_exactly_and_non_utf8_is_refused(self):
        class RawDriveMirror(FakeDriveMirror):
            # Real HistoryDrive.download over a faked rclone transport returning bytes.
            remote = "gdrive:"
            download = HistoryDrive.download

            def command(self, args):
                folder = args[args.index("--drive-root-folder-id") + 1]
                return self.records[folder][args[1].split(":", 1)[1]]

        crlf, bad = record_name(1, "a"), record_name(2, "b")
        drive = RawDriveMirror(books=["01_기획"], records={"01_기획": {crlf: "윈도우\r\n기록\n".encode(),
                                                                         bad: b"\xff\xfe bad"}})
        report = sync_history(LocalBackend(), self.config, drive, self.config)
        self.assertEqual((self.history(self.a) / crlf).read_bytes(), "윈도우\r\n기록\n".encode())
        self.assertIn("not UTF-8", report["skipped"][0])
        self.assertFalse((self.history(self.a) / bad).exists())

    def test_duplicate_drive_task_names_are_skipped_not_guessed(self):
        class DuplicateDrive(FakeDriveMirror):
            def list_books(self, parent_id):
                return [{"id": "idA", "name": "01_기획", "mimeType": FOLDER_MIME},
                        {"id": "idB", "name": "01_기획", "mimeType": FOLDER_MIME}]

        self.put(self.a, record_name(1, "a"), "로컬 기록")
        drive = DuplicateDrive(records={"idA": {record_name(2, "b"): "A 기록"}, "idB": {}})
        report = sync_history(LocalBackend(), self.config, drive, self.config)
        self.assertIn("ambiguous", report["skipped"][0])
        self.assertFalse(report["complete"])
        self.assertEqual(drive.records, {"idA": {record_name(2, "b"): "A 기록"}, "idB": {}})
        self.assertFalse((self.history(self.a) / record_name(2, "b")).exists())


class MirrorConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def load(self, **extra):
        data = {"schema_version": 1, "active_year": {"mode": "system", "override": "2026"},
                "task_number_regex": REGEX, "year_parent": {"id": "abc123"},
                "cache": {"directory": "~/x", "max_age_hours": 1,
                          "max_parent_ids_per_index_query": 1, "max_parent_queries": 1}}
        data.update(extra)
        path = self.base / "c.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return read_config(path)

    def test_drive_primary_with_local_mirror(self):
        config = self.load(mirror={"type": "local", "root": str(self.base)})
        backend, view = work_history.make_mirror(config)
        self.assertIsInstance(backend, LocalBackend)
        self.assertEqual(view["_source"]["root"], self.base)

    def test_mirror_must_be_the_other_library_type(self):
        with self.assertRaises(WorkError):
            self.load(mirror={"type": "drive"})

    def test_no_mirror_configured(self):
        self.assertIsNone(work_history.make_mirror(self.load()))


class SyncLockTests(unittest.TestCase):
    def test_cli_sync_holds_the_state_lock(self):
        # Two sessions syncing at once could upload the same record twice
        # (Drive allows duplicate names); the CLI must serialise them.
        import fcntl, io, os
        from unittest.mock import patch
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        (base / "lib" / "2026").mkdir(parents=True)
        config = base / "config.json"
        config.write_text(json.dumps({
            "schema_version": 1, "active_year": {"mode": "system", "override": "2026"},
            "task_number_regex": REGEX, "year_parent": {"id": "abc123"},
            "source": {"type": "local", "root": str(base / "lib")}, "mirror": {"type": "drive"},
        }), encoding="utf-8")
        state = base / "state"
        seen = {}

        def probe(*_args, **_kwargs):
            fd = os.open(state / "history.lock", os.O_RDWR)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                seen["held"] = False
            except BlockingIOError:
                seen["held"] = True
            finally:
                os.close(fd)
            return {"complete": True}

        argv = ["work_history.py", "--config", str(config), "--state-dir", str(state), "sync"]
        with patch.object(sys, "argv", argv), patch.object(work_history, "sync_history", probe), \
             patch.object(sys, "stdout", io.StringIO()):
            self.assertEqual(work_history.main(), 0)
        self.assertTrue(seen["held"])


if __name__ == "__main__":
    unittest.main()
