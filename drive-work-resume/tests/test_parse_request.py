import unittest

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from parse_request import parse_request


class ParseRequestTests(unittest.TestCase):
    def test_current_work_list_is_deterministic(self):
        self.assertEqual(
            parse_request("현재 업무 리스트"),
            {
                "intent": "list_current_tasks",
                "deterministic": True,
                "normalized_text": "현재 업무 리스트",
            },
        )

    def test_numbered_manual_related_search_uses_index_and_titles(self):
        result = parse_request("18번에서 매뉴얼 관련 파일 모두 찾아줘.")
        self.assertEqual(result["intent"], "search_task")
        self.assertTrue(result["deterministic"])
        self.assertEqual(result["task_number"], "18")
        self.assertEqual(result["keyword"], "매뉴얼")
        self.assertEqual(result["search_mode"], "indexed_and_title")
        self.assertTrue(result["refresh_requested"])

    def test_natural_list_request_is_supported(self):
        result = parse_request("현재 업무 목록 보여줘")
        self.assertEqual(result["intent"], "list_current_tasks")

    def test_zero_padded_number_is_normalized(self):
        result = parse_request("01번에서 양식 파일 찾아줘")
        self.assertEqual(result["task_number"], "1")
        self.assertFalse(result["refresh_requested"])

    def test_explicit_refresh_is_supported(self):
        result = parse_request("01번 업무 새로고침해줘")
        self.assertEqual(result["intent"], "refresh_task")
        self.assertEqual(result["task_number"], "1")

    def test_refresh_words_are_not_part_of_search_keyword(self):
        result = parse_request("18번에서 매뉴얼 관련 파일 새로고침해서 찾아줘")
        self.assertEqual(result["keyword"], "매뉴얼")
        self.assertEqual(result["search_mode"], "indexed_and_title")
        self.assertTrue(result["refresh_requested"])

    def test_plain_filename_search_uses_title_cache_only(self):
        result = parse_request("18번에서 장비 기동 매뉴얼 파일 검색해줘")
        self.assertEqual(result["intent"], "search_task")
        self.assertEqual(result["keyword"], "장비 기동 매뉴얼")
        self.assertEqual(result["search_mode"], "title")

    def test_ambiguous_phrase_is_not_guessed(self):
        result = parse_request("매뉴얼 찾아줘")
        self.assertEqual(result["intent"], "unrecognized")
        self.assertFalse(result["deterministic"])


if __name__ == "__main__":
    unittest.main()
