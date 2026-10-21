import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from drive_work_resume import TaskDeliveryError, WorkError, execute, read_config
from local_source import MAX_RECORD_BYTES, LocalBackend, local_id
from parse_request import parse_request
import work_history


REGEX = r"^(?P<number>0*[1-9][0-9]{0,2})_"
SEOUL = ZoneInfo("Asia/Seoul")


def write_config(root: Path, config_path: Path, **overrides) -> Path:
    data = {
        "schema_version": 1,
        "active_year": {"mode": "system", "override": "2026"},
        "task_number_regex": REGEX,
        "source": {"type": "local", "root": str(root)},
    }
    data.update(overrides)
    config_path.write_text(json.dumps(data), encoding="utf-8")
    return config_path


def make_library(base: Path) -> Path:
    """A 2026 year folder with two numbered books and one unnumbered book."""
    year = base / "2026"
    (year / "01_기획" / "03_매뉴얼").mkdir(parents=True)
    (year / "01_기획" / "03_매뉴얼" / "제품 매뉴얼.pdf").write_text("x", encoding="utf-8")
    (year / "01_기획" / "메모.txt").write_text("y", encoding="utf-8")
    (year / "02_개발").mkdir()
    (year / "자유 업무").mkdir()  # unnumbered book
    return year


class LocalCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        make_library(self.base)
        self.config = read_config(write_config(self.base, self.base / "config.json"))
        self.state = self.base / "state"
        self.session = "synthetic_session"

    def run_text(self, text, config=None):
        return execute(LocalBackend(), config or self.config, parse_request(text))

    def bind_task(self, number="1"):
        task = work_history.resolve(LocalBackend(), self.config, number, None)
        work_history.bind(self.state, self.session, task)
        return task

    def snapshot(self):
        return {"goal": "매뉴얼 정리", "done": ["초안"], "next": ["검토"]}

    def checkpoint(self, day=None):
        when = datetime(2026, 2, day, 9, 0, tzinfo=SEOUL) if day else None
        return work_history.checkpoint(LocalBackend(), self.config, self.state, self.session,
                                       self.snapshot(), when)

    def read(self, task, start=None, end=None, limit=10, before=None):
        return work_history.read_history(LocalBackend(), self.config, self.state, task,
                                         start, end, limit, before)


class LocalConfigTests(LocalCase):
    def test_valid_local_config_sets_source(self):
        self.assertEqual(self.config["_source"]["type"], "local")
        self.assertEqual(self.config["_source"]["root"], self.base)
        self.assertIsInstance(work_history.make_backend(self.config), LocalBackend)

    def test_missing_root_directory_is_rejected(self):
        with self.assertRaises(WorkError):
            read_config(write_config(self.base / "nope", self.base / "c.json"))

    def test_relative_root_is_rejected(self):
        with self.assertRaises(WorkError):
            read_config(write_config(self.base, self.base / "c.json",
                                     source={"type": "local", "root": "relative/path"}))

    def test_unknown_source_type_is_rejected(self):
        with self.assertRaises(WorkError):
            read_config(write_config(self.base, self.base / "c.json", source={"type": "ftp"}))

    def test_absent_source_defaults_to_drive(self):
        path = self.base / "c.json"
        path.write_text(json.dumps({
            "schema_version": 1, "year_parent": {"id": "abc123"},
            "active_year": {"mode": "system", "override": None},
            "task_number_regex": REGEX,
            "cache": {"directory": "~/x", "max_age_hours": 1,
                      "max_parent_ids_per_index_query": 1, "max_parent_queries": 1},
        }), encoding="utf-8")
        config = read_config(path)
        self.assertEqual(config["_source"]["type"], "drive")
        self.assertIsInstance(work_history.make_backend(config), work_history.HistoryDrive)


class LocalListAndSearchTests(LocalCase):
    def test_list_includes_unnumbered_and_resolves_numbers(self):
        out = self.run_text("현재 업무 리스트")
        self.assertEqual([f["name"] for f in out["folders"]], ["01_기획", "02_개발", "자유 업무"])
        numbers = {f["name"]: f["number"] for f in out["folders"]}
        self.assertEqual(numbers["01_기획"], "1")
        self.assertIsNone(numbers["자유 업무"])

    def test_list_skips_symlinked_book(self):
        os.symlink(self.base / "2026" / "01_기획", self.base / "2026" / "99_링크")
        names = [f["name"] for f in self.run_text("현재 업무 리스트")["folders"]]
        self.assertNotIn("99_링크", names)

    def test_search_matches_file_names(self):
        out = self.run_text("1번에서 매뉴얼 찾아줘")
        self.assertEqual([r["relative_path"] for r in out["results"]],
                         [os.path.join("03_매뉴얼", "제품 매뉴얼.pdf")])
        self.assertEqual(out["results"][0]["matches"], ["name"])
        self.assertEqual(out["task"]["source"], "local")

    def test_related_search_notes_no_content_index(self):
        out = self.run_text("1번에서 관련 매뉴얼 찾아줘")
        self.assertEqual(out["search_mode"], "indexed_and_title")
        self.assertTrue(out["index"]["issues"])

    def test_refresh_counts_descendants(self):
        out = self.run_text("1번 새로고침 해줘")
        self.assertEqual(out["file_count"], 2)
        self.assertEqual(out["folder_count"], 1)

    def test_refresh_excludes_symlinked_subfolders(self):
        book = self.base / "2026" / "02_개발"
        (book / "real_sub").mkdir()
        os.symlink(book / "real_sub", book / "link_sub")
        self.assertEqual(self.run_text("2번 새로고침 해줘")["folder_count"], 1)

    def test_missing_year_folder_errors(self):
        empty = self.base / "empty"
        empty.mkdir()
        with self.assertRaises(WorkError):
            self.run_text("현재 업무 리스트", read_config(write_config(empty, empty / "c.json")))

    def test_unknown_number_is_an_error(self):
        with self.assertRaises(WorkError):
            self.run_text("7번에서 매뉴얼 찾아줘")


class LocalHistoryTests(LocalCase):
    def history_dir(self, book="01_기획"):
        return self.base / "2026" / book / "_업무기록"

    def test_checkpoint_files_record_and_clears_dirty(self):
        self.bind_task("1")
        result = self.checkpoint(3)
        self.assertTrue(result["stored_locally"])
        self.assertEqual(result["sync"], {"delivered": 1, "pending": 0, "issues": []})
        self.assertTrue(result["filename"].startswith("2026-02-03_"))
        files = list(self.history_dir().glob("*.md"))
        self.assertEqual(len(files), 1)
        self.assertIn("매뉴얼 정리", files[0].read_text(encoding="utf-8"))
        self.assertFalse(work_history.session_state(self.state, self.session)["dirty"])

    def test_read_returns_records_newest_first_with_pagination(self):
        task = self.bind_task("1")
        for day in (3, 5, 4):
            self.checkpoint(day)
        page1 = self.read(task, limit=2)
        self.assertEqual([r["filename"][:10] for r in page1["records"]], ["2026-02-05", "2026-02-04"])
        self.assertTrue(page1["truncated"])
        self.assertEqual(page1["records"][0]["source"], "local")
        self.assertTrue(page1["records"][0]["url"].startswith("file://"))
        page2 = self.read(task, limit=2, before=page1["next_before"])
        self.assertEqual([r["filename"][:10] for r in page2["records"]], ["2026-02-03"])

    def test_read_respects_date_filter(self):
        task = self.bind_task("1")
        for day in (3, 10):
            self.checkpoint(day)
        out = self.read(task, date(2026, 2, 4), date(2026, 2, 28))
        self.assertEqual([r["filename"][:10] for r in out["records"]], ["2026-02-10"])

    def test_checkpoint_does_not_lose_summary_when_book_moves(self):
        # Review finding 1: a validation failure must not discard the summary.
        self.bind_task("1")
        os.rename(self.base / "2026" / "01_기획", self.base / "2026" / "01_기획_완료")
        result = self.checkpoint()
        self.assertTrue(result["stored_locally"])
        self.assertEqual(result["sync"]["pending"], 1)
        self.assertTrue(result["sync"]["issues"])
        self.assertEqual(len(list((self.state / LocalBackend.outbox).glob("*.json"))), 1)

    def test_history_files_keep_shared_permissions(self):
        # Review finding 2: never force private perms onto a shared library.
        old = os.umask(0o022)
        try:
            self.bind_task("1")
            self.checkpoint()
        finally:
            os.umask(old)
        hist = self.history_dir()
        self.assertEqual(stat.S_IMODE(hist.stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(next(hist.glob("*.md")).stat().st_mode), 0o644)

    def test_read_survives_oversized_and_non_utf8_records(self):
        # Review finding 3: one bad record must not abort the whole read.
        task = self.bind_task("1")
        hist = self.history_dir()
        hist.mkdir()
        good = "2026-02-01_120000_000000_" + "a" * 32 + ".md"
        huge = "2026-02-02_120000_000000_" + "b" * 32 + ".md"
        bad = "2026-02-03_120000_000000_" + "c" * 32 + ".md"
        (hist / good).write_text("정상 기록", encoding="utf-8")
        (hist / huge).write_text("x" * (MAX_RECORD_BYTES + 10), encoding="utf-8")
        (hist / bad).write_bytes(b"\xff\xfe not utf-8 \x80")
        out = self.read(task)
        self.assertEqual(out["matched"], 3)
        bodies = {r["filename"]: r["body"] for r in out["records"]}
        self.assertEqual(bodies[good], "정상 기록")
        self.assertIn("생략", bodies[huge])
        self.assertIn("not utf-8", bodies[bad])

    def test_task_pointing_outside_the_library_is_rejected(self):
        # Review finding 6: a book is only ever a listed, non-symlink direct child.
        outside = self.base / "outside"
        outside.mkdir()
        os.symlink(outside, self.base / "2026" / "09_외부")
        task = {"id": local_id(outside), "name": "09_외부", "number": "9", "year": "2026",
                "url": None, "source": "local"}
        with self.assertRaises(TaskDeliveryError):
            work_history.validate_task(LocalBackend(), self.config, task)

    def test_history_requires_a_listed_folder(self):
        with self.assertRaises(WorkError):
            LocalBackend().history_folder(local_id(self.base / "outside"), create=True)

    def test_binding_from_lister_result_allows_checkpoint(self):
        out = self.run_text("1번에서 매뉴얼 찾아줘")
        work_history.bind(self.state, self.session, {**out["task"], "year": out["year"]})
        self.assertEqual(self.checkpoint()["sync"]["delivered"], 1)

    def test_local_backend_refuses_drive_bound_task(self):
        work_history.bind(self.state, self.session,
                          {"id": "a" * 64, "name": "01_기획", "number": "1", "year": "2026", "url": None})
        with self.assertRaisesRegex(WorkError, "different work library"):
            self.checkpoint()

    def test_drive_backend_refuses_local_bound_task(self):
        self.bind_task("1")
        with self.assertRaisesRegex(WorkError, "different work library"):
            work_history.checkpoint(work_history.HistoryDrive(), self.config, self.state,
                                    self.session, self.snapshot())

    def test_local_flush_never_delivers_drive_outbox(self):
        drive_record = self.state / "outbox" / ("d" * 32 + ".json")
        work_history.atomic_write(drive_record, json.dumps({
            "schema_version": 1, "filename": "2026-02-01_120000_000000_" + "d" * 32 + ".md",
            "task": {"id": "a" * 64, "name": "01_기획"}, "body": "drive"}))
        result = work_history.flush(LocalBackend(), self.config, self.state)
        self.assertEqual(result, {"delivered": 0, "pending": 0, "issues": []})
        self.assertTrue(drive_record.exists())


class LocalCLITests(unittest.TestCase):
    """End-to-end through both scripts, exactly as the host model runs them."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        make_library(self.base)
        self.config = write_config(self.base, self.base / "config.json")
        self.state = self.base / "state"
        self.env = {**os.environ, "CODEX_SESSION_ID": "cli_session"}

    def run_script(self, script, *args, stdin=None):
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / script), *args],
            input=stdin, capture_output=True, text=True, env=self.env, timeout=60)
        self.assertNotIn("Traceback", proc.stderr)
        return proc.returncode, json.loads(proc.stdout)

    def test_list_search_checkpoint_read(self):
        common = ["--config", str(self.config), "--state-dir", str(self.state)]
        rc, out = self.run_script("drive_work_resume.py", "--text", "현재 업무 리스트", *common)
        self.assertEqual((rc, len(out["folders"])), (0, 3))
        rc, out = self.run_script("drive_work_resume.py", "--text", "1번에서 매뉴얼 찾아줘", *common)
        self.assertEqual(out["history_binding"], "bound_and_marked_for_checkpoint")
        rc, out = self.run_script("work_history.py", *common, "checkpoint",
                                  stdin=json.dumps({"goal": "정리", "done": ["초안"], "next": ["검토"]}))
        self.assertEqual((rc, out["sync"]["delivered"]), (0, 1))
        rc, out = self.run_script("work_history.py", *common, "read", "--task", "1")
        self.assertEqual((rc, len(out["records"])), (0, 1))

    def test_errors_are_reported_as_json_not_tracebacks(self):
        empty = self.base / "empty"
        empty.mkdir()
        config = write_config(empty, empty / "c.json")
        for script, args in (("drive_work_resume.py", ["--text", "현재 업무 리스트"]),
                             ("work_history.py", ["read", "--task", "1"])):
            if script == "work_history.py":
                argv = ["--config", str(config), "--state-dir", str(self.state), *args]
            else:
                argv = [*args, "--config", str(config), "--state-dir", str(self.state)]
            rc, out = self.run_script(script, *argv)
            self.assertEqual(rc, 1)
            self.assertIn("2026", out["error"])


if __name__ == "__main__":
    unittest.main()
