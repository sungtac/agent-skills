import json
import os
import stat
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from drive_work_resume import WorkError, read_config
import local_source
import work_history
from work_history import TaskDeliveryError


REGEX = r"^(?P<number>0*[1-9][0-9]{0,2})_"


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


class LocalConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        make_library(self.base)

    def tearDown(self):
        self.temp.cleanup()

    def test_valid_local_config_sets_source(self):
        cfg = read_config(write_config(self.base, self.base / "config.json"))
        self.assertEqual(cfg["_source"]["type"], "local")
        self.assertEqual(cfg["_source"]["root"], self.base)

    def test_missing_root_directory_is_rejected(self):
        with self.assertRaises(WorkError):
            read_config(write_config(self.base / "nope", self.base / "c.json"))

    def test_relative_root_is_rejected(self):
        path = self.base / "c.json"
        path.write_text(json.dumps({
            "schema_version": 1, "active_year": {"mode": "system", "override": "2026"},
            "task_number_regex": REGEX, "source": {"type": "local", "root": "relative/path"},
        }), encoding="utf-8")
        with self.assertRaises(WorkError):
            read_config(path)

    def test_unknown_source_type_is_rejected(self):
        path = self.base / "c.json"
        path.write_text(json.dumps({
            "schema_version": 1, "active_year": {"mode": "system", "override": "2026"},
            "task_number_regex": REGEX, "source": {"type": "ftp"},
        }), encoding="utf-8")
        with self.assertRaises(WorkError):
            read_config(path)

    def test_absent_source_defaults_to_drive(self):
        # A drive config (no source) must still validate the drive way.
        path = self.base / "c.json"
        path.write_text(json.dumps({
            "schema_version": 1, "year_parent": {"id": "abc123"},
            "active_year": {"mode": "system", "override": None},
            "task_number_regex": REGEX,
            "cache": {"directory": "~/x", "max_age_hours": 1,
                      "max_parent_ids_per_index_query": 1, "max_parent_queries": 1},
        }), encoding="utf-8")
        self.assertEqual(read_config(path)["_source"]["type"], "drive")


class LocalExecuteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        make_library(self.base)
        self.config = read_config(write_config(self.base, self.base / "config.json"))

    def tearDown(self):
        self.temp.cleanup()

    def run_text(self, text):
        from parse_request import parse_request
        return local_source.execute_local(self.config, parse_request(text))

    def test_list_includes_unnumbered_and_resolves_numbers(self):
        out = self.run_text("현재 업무 리스트")
        names = [f["name"] for f in out["folders"]]
        self.assertEqual(names, ["01_기획", "02_개발", "자유 업무"])
        numbers = {f["name"]: f["number"] for f in out["folders"]}
        self.assertEqual(numbers["01_기획"], "1")
        self.assertIsNone(numbers["자유 업무"])

    def test_list_skips_symlinked_book(self):
        os.symlink(self.base / "2026" / "01_기획", self.base / "2026" / "99_링크")
        names = [f["name"] for f in self.run_text("현재 업무 리스트")["folders"]]
        self.assertNotIn("99_링크", names)

    def test_search_matches_file_names(self):
        out = self.run_text("1번에서 매뉴얼 찾아줘")
        paths = [r["relative_path"] for r in out["results"]]
        self.assertEqual(paths, [os.path.join("03_매뉴얼", "제품 매뉴얼.pdf")])
        self.assertEqual(out["results"][0]["matches"], ["name"])
        self.assertEqual(out["task"]["number"], "1")

    def test_related_search_notes_no_content_index(self):
        out = self.run_text("1번에서 관련 매뉴얼 찾아줘")
        self.assertEqual(out["search_mode"], "indexed_and_title")
        self.assertTrue(out["index"]["issues"])

    def test_refresh_counts_descendants(self):
        out = self.run_text("1번 새로고침 해줘")
        self.assertEqual(out["file_count"], 2)
        self.assertGreaterEqual(out["folder_count"], 1)

    def test_missing_year_folder_errors(self):
        empty = Path(self.temp.name) / "empty"
        empty.mkdir()
        cfg = read_config(write_config(empty, empty / "config.json"))
        from parse_request import parse_request
        with self.assertRaises(WorkError):
            local_source.execute_local(cfg, parse_request("현재 업무 리스트"))

    def test_unknown_number_is_ambiguous_error(self):
        from parse_request import parse_request
        with self.assertRaises(WorkError):
            local_source.execute_local(self.config, parse_request("7번에서 매뉴얼 찾아줘"))


class LocalHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        make_library(self.base)
        self.config = read_config(write_config(self.base, self.base / "config.json"))
        self.state = self.base / "state"
        self.session = "synthetic_session"

    def tearDown(self):
        self.temp.cleanup()

    def bind_task(self, number="1"):
        task = work_history.resolve_local(self.config, number, None)
        work_history.bind(self.state, self.session, task)
        return task

    def snapshot(self):
        return {"goal": "매뉴얼 정리", "done": ["초안"], "next": ["검토"]}

    def test_checkpoint_writes_into_history_folder_and_clears_dirty(self):
        self.bind_task("1")
        when = datetime(2026, 2, 3, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        result = work_history.checkpoint_local(self.config, self.state, self.session, self.snapshot(), now=when)
        self.assertTrue(result["stored_locally"])
        self.assertTrue(result["filename"].startswith("2026-02-03_"))
        hist = self.base / "2026" / "01_기획" / "_업무기록"
        files = list(hist.glob("*.md"))
        self.assertEqual(len(files), 1)
        self.assertIn("매뉴얼 정리", files[0].read_text(encoding="utf-8"))
        self.assertFalse(work_history.session_state(self.state, self.session)["dirty"])

    def test_read_returns_written_records_newest_first(self):
        self.bind_task("1")
        for day in (3, 5, 4):
            when = datetime(2026, 2, day, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
            work_history.checkpoint_local(self.config, self.state, self.session, self.snapshot(), now=when)
        task = work_history.resolve_local(self.config, "1", None)
        out = work_history.read_history_local(self.config, task, None, None, limit=2)
        self.assertEqual([r["filename"][:10] for r in out["records"]], ["2026-02-05", "2026-02-04"])
        self.assertTrue(out["truncated"])
        self.assertEqual(out["records"][0]["source"], "local")
        # pagination cursor returns the remaining record
        nxt = work_history.read_history_local(self.config, task, None, None, limit=2, before=out["next_before"])
        self.assertEqual([r["filename"][:10] for r in nxt["records"]], ["2026-02-03"])

    def test_read_respects_date_filter(self):
        self.bind_task("1")
        for day in (3, 10):
            when = datetime(2026, 2, day, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
            work_history.checkpoint_local(self.config, self.state, self.session, self.snapshot(), now=when)
        task = work_history.resolve_local(self.config, "1", None)
        out = work_history.read_history_local(self.config, task, date(2026, 2, 4), date(2026, 2, 28), limit=10)
        self.assertEqual([r["filename"][:10] for r in out["records"]], ["2026-02-10"])

    def test_validate_rejects_task_outside_year(self):
        task = work_history.resolve_local(self.config, "1", None)
        moved = dict(task, path=str(self.base), id=local_source.local_id(self.base))
        with self.assertRaises(TaskDeliveryError):
            work_history.validate_local_task(self.config, task | {"path": str(self.base / "2026")})
        with self.assertRaises(TaskDeliveryError):
            work_history.validate_local_task(self.config, moved)

    def test_binding_from_lister_result_allows_checkpoint(self):
        # The lister's execute_local task dict (not resolve_local) must carry
        # enough identity — including source — for a later local checkpoint.
        from parse_request import parse_request
        out = local_source.execute_local(self.config, parse_request("1번에서 매뉴얼 찾아줘"))
        bound = {**out["task"], "year": out["year"]}
        self.assertEqual(bound.get("source"), "local")
        work_history.bind(self.state, self.session, bound)
        result = work_history.checkpoint_local(self.config, self.state, self.session, self.snapshot())
        self.assertTrue(result["stored_locally"])

    def test_checkpoint_requires_local_binding(self):
        # Bind a non-local (drive-shaped) task, then local checkpoint must refuse.
        work_history.bind(self.state, self.session,
                          {"id": "a" * 64, "name": "01_기획", "number": "1", "year": "2026", "url": None})
        with self.assertRaises(WorkError):
            work_history.checkpoint_local(self.config, self.state, self.session, self.snapshot())

    def test_checkpoint_does_not_lose_summary_when_book_moves(self):
        # Finding 1: a validation failure must not discard the summary; it stays
        # durably queued in the local outbox and is reported as pending.
        self.bind_task("1")
        os.rename(self.base / "2026" / "01_기획", self.base / "2026" / "01_기획_완료")
        result = work_history.checkpoint_local(self.config, self.state, self.session, self.snapshot())
        self.assertTrue(result["stored_locally"])
        self.assertGreaterEqual(result["sync"]["pending"], 1)
        self.assertTrue(result["sync"]["issues"])
        outbox = list((self.state / work_history.LOCAL_OUTBOX).glob("*.json"))
        self.assertEqual(len(outbox), 1)  # the record is retained, not lost

    def test_history_files_keep_shared_permissions(self):
        # Finding 2: writing into a shared library must not force private perms.
        old = os.umask(0o022)
        try:
            self.bind_task("1")
            work_history.checkpoint_local(self.config, self.state, self.session, self.snapshot())
        finally:
            os.umask(old)
        hist = self.base / "2026" / "01_기획" / "_업무기록"
        self.assertTrue(stat.S_IMODE(hist.stat().st_mode) & 0o055, "history dir must stay group/other accessible")
        md = next(hist.glob("*.md"))
        self.assertTrue(stat.S_IMODE(md.stat().st_mode) & 0o044, "history file must stay group/other readable")

    def test_read_survives_oversized_and_non_utf8_records(self):
        # Finding 3: one bad record must not abort the whole read.
        self.bind_task("1")
        hist = self.base / "2026" / "01_기획" / "_업무기록"
        hist.mkdir(parents=True, exist_ok=True)
        stamp = "2026-02-01_120000_000000_" + "a" * 32 + ".md"
        (hist / stamp).write_text("정상 기록", encoding="utf-8")
        huge = "2026-02-02_120000_000000_" + "b" * 32 + ".md"
        (hist / huge).write_text("x" * (work_history.MAX_LOCAL_RECORD_BYTES + 10), encoding="utf-8")
        bad = "2026-02-03_120000_000000_" + "c" * 32 + ".md"
        (hist / bad).write_bytes(b"\xff\xfe not utf-8 \x80")
        task = work_history.resolve_local(self.config, "1", None)
        out = work_history.read_history_local(self.config, task, None, None, limit=10)
        self.assertEqual(out["matched"], 3)
        bodies = {r["filename"]: r["body"] for r in out["records"]}
        self.assertEqual(bodies[stamp], "정상 기록")
        self.assertIn("생략", bodies[huge])
        self.assertIn(bad, bodies)  # decoded leniently, not crashed

    def test_validate_rejects_symlinked_book(self):
        # Finding 6: a book reached via a symlink must be rejected explicitly.
        link = self.base / "2026" / "09_링크"
        os.symlink(self.base / "2026" / "01_기획", link)
        task = {"id": local_source.local_id(link.resolve()), "name": "09_링크", "number": "9",
                "year": "2026", "url": link.as_uri(), "path": str(link), "source": "local"}
        with self.assertRaises(TaskDeliveryError):
            work_history.validate_local_task(self.config, task)

    def test_refresh_excludes_symlinked_subfolders(self):
        # Finding 4: a symlinked sub-folder must not inflate folder_count.
        from parse_request import parse_request
        book = self.base / "2026" / "02_개발"
        (book / "real_sub").mkdir()
        os.symlink(book / "real_sub", book / "link_sub")
        self.config = read_config(write_config(self.base, self.base / "config.json"))
        out = local_source.execute_local(self.config, parse_request("2번 새로고침 해줘"))
        self.assertEqual(out["folder_count"], 1)


if __name__ == "__main__":
    unittest.main()
