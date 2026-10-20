#!/usr/bin/env python3
"""Parse the narrow deterministic commands supported by drive-work-resume."""

from __future__ import annotations

import argparse
import json
import re
from typing import Any

LIST_PATTERN = re.compile(
    r"^현재\s*(?:업무|작업)\s*(?:리스트|목록)"
    r"(?:\s*(?:보여\s*줘|알려\s*줘|출력\s*해\s*줘))?$"
)
SEARCH_PATTERN = re.compile(
    r"^(?P<number>0*[1-9][0-9]{0,2})\s*번\s*(?:에서|의)\s*(?P<query>.+?)"
    r"\s*(?:찾아\s*줘|검색\s*해\s*줘|찾기|검색)$"
)
REFRESH_PATTERN = re.compile(
    r"^(?P<number>0*[1-9][0-9]{0,2})\s*번\s*(?:(?:업무|폴더)\s*)?"
    r"새로\s*고침\s*(?:해\s*줘|하기)$"
)
REFRESH_WORDS = re.compile(r"\s*새로\s*고침(?:해서|하고|한\s*뒤|후에?)?\s*")
TRAILING_QUERY_WORDS = re.compile(
    r"\s*(?:관련\s*)?(?:파일|자료)(?:을|를|들)?\s*(?:모두|전체)?\s*$"
)
TRAILING_QUANTIFIER = re.compile(r"\s*(?:모두|전체)\s*$")


def normalize(text: str) -> str:
    """Normalize user text without changing its semantic keywords."""
    return re.sub(r"\s+", " ", text.strip()).rstrip(".!?。")


def parse_request(text: str) -> dict[str, Any]:
    """Return one supported action or an explicit unsupported result."""
    normalized = normalize(text)
    if LIST_PATTERN.fullmatch(normalized):
        return {
            "intent": "list_current_tasks",
            "deterministic": True,
            "normalized_text": normalized,
        }

    refresh = REFRESH_PATTERN.fullmatch(normalized)
    if refresh:
        return {
            "intent": "refresh_task",
            "deterministic": True,
            "normalized_text": normalized,
            "task_number": str(int(refresh.group("number"))),
            "refresh_requested": True,
        }

    match = SEARCH_PATTERN.fullmatch(normalized)
    if match:
        raw_query = match.group("query").strip()
        keyword = TRAILING_QUERY_WORDS.sub("", REFRESH_WORDS.sub(" ", raw_query).strip())
        keyword = TRAILING_QUANTIFIER.sub("", keyword).strip()
        if keyword:
            return {
                "intent": "search_task",
                "deterministic": True,
                "normalized_text": normalized,
                "task_number": str(int(match.group("number"))),
                "keyword": keyword,
                "search_mode": "indexed_and_title" if "관련" in raw_query else "title",
                "refresh_requested": bool(re.search(r"새로\s*고침|모두|전체|정확히", normalized)),
            }

    return {
        "intent": "unrecognized",
        "deterministic": False,
        "normalized_text": normalized,
        "reason": "Supported forms are '현재 업무 리스트' and 'NN번에서 <키워드> 찾아줘'.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", required=True, help="Korean user request")
    args = parser.parse_args()
    print(json.dumps(parse_request(args.text), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
