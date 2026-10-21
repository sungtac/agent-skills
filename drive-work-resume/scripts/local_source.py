#!/usr/bin/env python3
"""Local-filesystem work-library backend for drive-work-resume.

Mirrors the Drive backend's year-folder > ``NN번`` task-book structure on a
configured local directory. Listing and search are live (no rclone, no cache);
search is name/path based (there is no content index). A task's stable id is the
SHA-256 of its absolute path, which satisfies the shared ``drive_id`` validator
so session binding, the outbox envelope check, and work-history reuse unchanged.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from drive_work_resume import (FOLDER_MIME, WorkError, current_year, resolve_task,
                               task_number, title_matches)


def local_id(path: Path) -> str:
    """A path-stable, drive_id-compatible identifier (64 hex chars)."""
    return hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()


def local_url(path: Path) -> str:
    return path.resolve().as_uri()


def year_dir(config: dict[str, Any]) -> Path:
    """The <root>/<year> directory, required to exist exactly like the Drive year folder."""
    root = config["_source"]["root"]
    if not isinstance(root, Path):
        root = Path(str(root)).expanduser()
    year = current_year(config)
    target = (root / year)
    if not target.is_dir() or target.is_symlink():
        raise WorkError(f"Expected exactly one {year} folder; found 0")
    return target.resolve()


def local_books(year: Path) -> list[dict[str, Any]]:
    """Direct-child folders of the year directory, one work book each.

    Symlinked directories are skipped so a book can never redirect outside the
    configured tree.
    """
    books: list[dict[str, Any]] = []
    for entry in sorted(year.iterdir(), key=lambda p: p.name.casefold()):
        if entry.is_dir() and not entry.is_symlink():
            resolved = entry.resolve()
            books.append({
                "id": local_id(resolved),
                "name": entry.name,
                "path": str(resolved),
                "mimeType": FOLDER_MIME,
                "url": local_url(resolved),
            })
    return books


def _modified_iso(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return None


def execute_local(config: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    """Run a parsed request against the local work library, matching the Drive JSON shape."""
    if request["intent"] == "unrecognized":
        raise WorkError(request["reason"])
    year = year_dir(config)
    books = local_books(year)
    pattern = config["task_number_regex"]

    if request["intent"] == "list_current_tasks":
        return {
            "intent": request["intent"], "year": current_year(config),
            "folders": [
                {"name": b["name"], "number": task_number(b["name"], pattern), "url": b["url"]}
                for b in books
            ],
        }

    task = resolve_task(books, request["task_number"], pattern)
    book_path = Path(task["path"]).resolve()
    if book_path.parent != year or not book_path.is_dir():
        raise WorkError("Resolved task is not a verified direct child of the year folder")
    now = datetime.now(timezone.utc).isoformat()
    cache_report = {
        "started_at": now, "fetched_at": now, "stale": False,
        "enumeration_complete": True, "coverage_note": "local filesystem; live listing",
        "refresh_reason": "live", "refresh_complete": True, "refresh_issue": None,
        "folder_queries": 0,
    }
    task_out = {"id": task["id"], "number": request["task_number"], "name": task["name"],
                "url": task["url"], "path": str(book_path), "source": "local"}

    if request["intent"] == "refresh_task":
        folder_count = file_count = 0
        for root_dir, dirs, files in os.walk(book_path, followlinks=False):
            # Exclude symlinked directories so the count matches the Drive backend,
            # which never treats a symlink as a real sub-folder.
            dirs[:] = [d for d in dirs if not (Path(root_dir) / d).is_symlink()]
            folder_count += len(dirs)
            file_count += len(files)
        return {
            "intent": request["intent"], "year": current_year(config),
            "task": task_out, "cache": cache_report,
            "folder_count": folder_count, "file_count": file_count,
        }

    keyword = request["keyword"]
    hits: list[dict[str, Any]] = []
    for root_dir, dirs, files in os.walk(book_path, followlinks=False):
        dirs.sort(key=str.casefold)
        for fname in files:
            if not title_matches(fname, keyword):
                continue
            full = Path(root_dir) / fname
            if full.is_symlink():
                continue
            hits.append({
                "id": local_id(full), "title": fname,
                "relative_path": str(full.relative_to(book_path)),
                "mime_type": None, "modified_time": _modified_iso(full),
                "url": local_url(full), "matches": ["name"],
            })
    index_report: dict[str, Any] = {"queries": 0, "complete": True, "issues": []}
    if request["search_mode"] == "indexed_and_title":
        index_report["issues"] = ["Local source: name/path search only; no content index"]
    return {
        "intent": request["intent"], "year": current_year(config),
        "task": task_out, "keyword": keyword, "search_mode": request["search_mode"],
        "cache": cache_report, "index": index_report,
        "results": sorted(hits, key=lambda item: item["relative_path"].casefold()),
    }
