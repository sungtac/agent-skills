import re
import sys
import tempfile
import unittest
import io
import json
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from drive_work_resume import FOLDER_MIME, GroupQueryError, RcloneDrive, WorkError, execute, resolve_task, year_folder
from parse_request import parse_request
import drive_work_resume
import work_history


def item(item_id, name, parent, mime=FOLDER_MIME):
    return {"id": item_id, "name": name, "parents": [parent], "mimeType": mime}


class FakeDrive:
    def __init__(self, reject_groups=False, add_outside_result=False):
        self.reject_groups = reject_groups
        self.add_outside_result = add_outside_result
        self.fail_task_listing = False
        self.queries = []
        self.items = [
            item("year", "2026", "library"),
            item("task", "01_업무", "year"),
            item("unnumbered", "그 외 업무", "year"),
            item("nestedA", "자료", "task"),
            item("nestedB", "별도", "task"),
            item("hwp", "장비_매뉴얼.hwp", "nestedA", "application/x-hwp"),
            item("pdf", "User Manual.pdf", "nestedB", "application/pdf"),
        ]

    def query(self, expression):
        self.queries.append(expression)
        parents = re.findall(r"'([A-Za-z0-9_-]+)' in parents", expression)
        if self.fail_task_listing and "task" in parents and "fullText contains" not in expression:
            raise WorkError("simulated quota failure")
        if self.reject_groups and len(parents) > 1:
            raise GroupQueryError("simulated grouped-query failure")
        results = [entry for entry in self.items if any(p in parents for p in entry["parents"])]
        if f"mimeType = '{FOLDER_MIME}'" in expression:
            results = [entry for entry in results if entry["mimeType"] == FOLDER_MIME]
        if "name = '2026'" in expression:
            results = [entry for entry in results if entry["name"] == "2026"]
        if "fullText contains" in expression:
            results = [entry for entry in results if entry["id"] in ("hwp", "pdf")]
            if self.add_outside_result:
                results.append(item("outside", "매뉴얼.pdf", "other", "application/pdf"))
        return results


class DriveWorkResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = {
            "year_parent": {"id": "library"},
            "active_year": {"mode": "system", "override": 2026},
            "task_number_regex": r"^(?P<number>0*[1-9][0-9]{0,2})_",
            "cache": {
                "directory": self.temp.name,
                "max_age_hours": 168,
                "max_parent_ids_per_index_query": 20,
                "max_parent_queries": 60,
            },
        }

    def test_list_includes_padded_and_unnumbered_direct_folders(self):
        result = execute(FakeDrive(), self.config, parse_request("현재 업무 리스트"))
        self.assertEqual([folder["name"] for folder in result["folders"]], ["01_업무", "그 외 업무"])
        self.assertEqual([folder["number"] for folder in result["folders"]], ["1", None])

    @patch('drive_work_resume.subprocess.run')
    def test_empty_rclone_query_null_is_a_valid_empty_result(self, run):
        run.return_value = SimpleNamespace(returncode=0, stdout='null', stderr='')
        self.assertEqual(RcloneDrive().query("name = 'missing'"), [])

    def test_year_folder_rejects_result_outside_the_configured_parent(self):
        class UntrustedResult:
            def query(self, expression):
                return [item('year', '2026', 'other')]
        with self.assertRaisesRegex(WorkError, 'found 0'):
            year_folder(UntrustedResult(), self.config)

    def test_task_cli_binds_and_marks_without_switching_a_dirty_task(self):
        state = Path(self.temp.name) / 'state'
        request_result = {'intent': 'search_task', 'year': '2026',
                          'task': {'id': 'task', 'name': '01_업무', 'number': '1', 'url': None}}
        args = ['drive_work_resume.py', '--text', '1번에서 매뉴얼 찾아줘', '--state-dir', str(state)]
        out = io.StringIO()
        with patch.object(sys, 'argv', args), patch.dict('os.environ', {'CODEX_SESSION_ID': 'synthetic_session'}), \
             patch.object(sys, 'stdout', out), patch.object(drive_work_resume, 'read_config', return_value=self.config), \
             patch.object(drive_work_resume, 'execute', return_value=request_result), \
             patch.object(work_history, 'flush', return_value={'delivered': 0, 'pending': 0, 'issues': []}):
            self.assertEqual(drive_work_resume.main(), 0)
        self.assertEqual(json.loads(out.getvalue())['history_binding'], 'bound_and_marked_for_checkpoint')
        binding = work_history.session_state(state, 'synthetic_session')
        self.assertTrue(binding['dirty'])
        self.assertEqual(binding['task']['id'], 'task')
        out = io.StringIO()
        request_result = {'intent': 'search_task', 'year': '2026',
                          'task': {'id': 'other', 'name': '02_업무', 'number': '2', 'url': None}}
        with patch.object(sys, 'argv', args), patch.dict('os.environ', {'CODEX_SESSION_ID': 'synthetic_session'}), \
             patch.object(sys, 'stdout', out), patch.object(drive_work_resume, 'read_config', return_value=self.config), \
             patch.object(drive_work_resume, 'execute', return_value=request_result), \
             patch.object(work_history, 'flush', return_value={'delivered': 0, 'pending': 0, 'issues': []}):
            self.assertEqual(drive_work_resume.main(), 0)
        self.assertEqual(json.loads(out.getvalue())['history_binding'], 'not_bound')
        self.assertEqual(work_history.session_state(state, 'synthetic_session')['task']['id'], 'task')

    def test_current_list_retries_previous_outbox_without_binding_a_task(self):
        state = Path(self.temp.name) / 'state'
        out = io.StringIO()
        args = ['drive_work_resume.py', '--text', '현재 업무 리스트', '--state-dir', str(state)]
        result = {'intent': 'list_current_tasks', 'year': '2026', 'folders': []}
        with patch.object(sys, 'argv', args), patch.object(sys, 'stdout', out), \
             patch.object(drive_work_resume, 'read_config', return_value=self.config), \
             patch.object(drive_work_resume, 'execute', return_value=result), \
             patch.object(work_history, 'flush', return_value={'delivered': 0, 'pending': 1, 'issues': ['offline']}) as retry:
            self.assertEqual(drive_work_resume.main(), 0)
        retry.assert_called_once()
        self.assertEqual(json.loads(out.getvalue())['history_sync']['pending'], 1)

    def test_duplicate_numeric_prefix_never_guesses(self):
        folders = [item("a", "01_업무", "year"), item("b", "1_업무", "year")]
        with self.assertRaisesRegex(WorkError, "01_업무, 1_업무"):
            resolve_task(folders, "1", self.config["task_number_regex"])

    def test_first_search_bootstraps_then_reuses_cache(self):
        drive = FakeDrive()
        request = parse_request("1번에서 매뉴얼 찾아줘")
        first = execute(drive, self.config, request)
        self.assertEqual(first["cache"]["refresh_reason"], "missing")
        self.assertEqual([entry["title"] for entry in first["results"]], ["장비_매뉴얼.hwp"])
        self.assertEqual((Path(self.temp.name) / "task.json").stat().st_mode & 0o777, 0o600)
        before = len(drive.queries)
        second = execute(drive, self.config, request)
        self.assertIsNone(second["cache"]["refresh_reason"])
        self.assertEqual(len(drive.queries) - before, 2)

    def test_exhaustive_related_search_retries_groups_and_checks_scope(self):
        drive = FakeDrive(reject_groups=True, add_outside_result=True)
        result = execute(drive, self.config, parse_request("01번에서 매뉴얼 관련 파일 모두 찾아줘"))
        self.assertTrue(result["cache"]["enumeration_complete"])
        self.assertEqual(result["cache"]["refresh_reason"], "requested")
        self.assertFalse(result["index"]["complete"])
        self.assertEqual({entry["id"] for entry in result["results"]}, {"hwp", "pdf"})
        self.assertTrue(all("outside" != entry["id"] for entry in result["results"]))

    def test_failed_refresh_preserves_cache_and_stops_index_queries(self):
        drive = FakeDrive()
        first = execute(drive, self.config, parse_request("1번에서 매뉴얼 찾아줘"))
        stored = (Path(self.temp.name) / "task.json").read_bytes()
        drive.fail_task_listing = True
        second = execute(drive, self.config, parse_request("1번에서 매뉴얼 관련 파일 모두 찾아줘"))
        self.assertFalse(second["cache"]["refresh_complete"])
        self.assertEqual(second["cache"]["fetched_at"], first["cache"]["fetched_at"])
        self.assertEqual((Path(self.temp.name) / "task.json").read_bytes(), stored)
        self.assertFalse(second["index"]["complete"])
        self.assertEqual(second["index"]["queries"], 0)

    def test_standalone_refresh_updates_cache(self):
        result = execute(FakeDrive(), self.config, parse_request("01번 폴더 새로고침해줘"))
        self.assertEqual(result["intent"], "refresh_task")
        self.assertTrue(result["cache"]["refresh_complete"])
        self.assertEqual(result["folder_count"], 3)
        self.assertEqual(result["file_count"], 2)

    def test_index_metadata_replaces_a_cached_old_title(self):
        drive = FakeDrive()
        execute(drive, self.config, parse_request("1번에서 매뉴얼 찾아줘"))
        next(entry for entry in drive.items if entry["id"] == "hwp")["name"] = "renamed.hwp"
        result = execute(drive, self.config, parse_request("1번에서 매뉴얼 관련 파일 찾아줘"))
        renamed = next(entry for entry in result["results"] if entry["id"] == "hwp")
        self.assertEqual(renamed["title"], "renamed.hwp")
        self.assertEqual(renamed["matches"], ["drive_index"])


if __name__ == "__main__":
    unittest.main()
