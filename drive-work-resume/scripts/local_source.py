#!/usr/bin/env python3
"""Local-filesystem work-library backend for drive-work-resume.

``LocalBackend`` implements the same backend interface as the Drive backend
(drive_work_resume.RcloneDrive / work_history.HistoryDrive): ``source``,
``outbox``, ``list_year``, ``list_books`` and ``run_task`` for listing and search,
plus ``history_folder``, ``children``, ``upload`` and ``download`` for work
history. The generic code (drive_work_resume.execute and work_history's resolve,
validate_task, checkpoint, flush and read_history) therefore serves both backends
unchanged; nothing outside this module special-cases a local library.

A folder's id is the SHA-256 of its resolved path, which satisfies the shared
``drive_id`` validator. Only folders this instance has itself listed can be used,
so history is always written under a verified direct child of the year folder.
Symlinked folders and files are never listed or followed. Search is name/path
based: there is no content index.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from drive_work_resume import (FOLDER_MIME, HISTORY_FOLDER, NAME_RE, TaskDeliveryError,
                               WorkError, current_year, title_matches)

MAX_RECORD_BYTES = 200000


def local_id(path: Path) -> str:
    """A path-stable, drive_id-compatible identifier (64 hex chars)."""
    return hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()


def local_url(path: Path) -> str:
    return path.resolve().as_uri()


def write_user_file(path: Path, contents: str) -> None:
    """Atomic write of user content with normal (umask) permissions.

    Unlike work_history.atomic_write it never forces private 0o700/0o600, so a
    history record written into a shared work library stays readable to others.
    """
    mask = os.umask(0)
    os.umask(mask)
    name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            name = handle.name
            os.fchmod(handle.fileno(), 0o666 & ~mask)
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def read_bounded(path: Path) -> str:
    """Read at most MAX_RECORD_BYTES and decode leniently.

    One oversized or non-UTF-8 record must not abort a whole history read.
    """
    with open(path, "rb") as handle:
        raw = handle.read(MAX_RECORD_BYTES + 1)
    if len(raw) > MAX_RECORD_BYTES:
        return "(기록이 너무 커서 생략됨)"
    return raw.decode("utf-8", errors="replace")


def _modified_iso(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return None


def _walk(root: Path):
    """os.walk that neither follows nor reports symlinked directories."""
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted((d for d in dirs if not (Path(current) / d).is_symlink()), key=str.casefold)
        yield Path(current), dirs, files


class LocalBackend:
    source = "local"
    outbox = "folder_outbox"  # separate from the Drive outbox; only this backend delivers it

    def __init__(self) -> None:
        self._paths: dict[str, Path] = {}

    def _remember(self, path: Path) -> str:
        resolved = path.resolve()
        item_id = local_id(resolved)
        self._paths[item_id] = resolved
        return item_id

    def _folder(self, folder_id: str) -> Path:
        path = self._paths.get(folder_id)
        if path is None:
            raise WorkError("Folder was not listed from the configured work library")
        return path

    # ── listing and search ──────────────────────────────────────────────────

    def list_year(self, config: dict[str, Any]) -> dict[str, Any]:
        root = config["_source"]["root"]
        if not isinstance(root, Path):
            root = Path(str(root)).expanduser()
        year = current_year(config)
        target = root / year
        if not target.is_dir() or target.is_symlink():
            raise WorkError(f"Expected exactly one {year} folder; found 0")
        return {"id": self._remember(target), "name": year, "mimeType": FOLDER_MIME,
                "url": local_url(target)}

    def list_books(self, parent_id: str) -> list[dict[str, Any]]:
        parent = self._folder(parent_id)
        books = []
        for entry in sorted(parent.iterdir(), key=lambda p: p.name.casefold()):
            if entry.is_dir() and not entry.is_symlink():
                books.append({"id": self._remember(entry), "name": entry.name, "parents": [parent_id],
                              "mimeType": FOLDER_MIME, "url": local_url(entry)})
        return books

    def run_task(self, config: dict[str, Any], request: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
        book = self._folder(task["id"])
        now = datetime.now(timezone.utc).isoformat()
        cache_report = {
            "started_at": now, "fetched_at": now, "stale": False,
            "enumeration_complete": True, "coverage_note": "local filesystem; live listing",
            "refresh_reason": "live", "refresh_complete": True, "refresh_issue": None,
            "folder_queries": 0,
        }
        task_out = {"id": task["id"], "number": request["task_number"], "name": task["name"],
                    "url": task["url"], "source": self.source}

        if request["intent"] == "refresh_task":
            folder_count = file_count = 0
            for _current, dirs, files in _walk(book):
                folder_count += len(dirs)
                file_count += len(files)
            return {
                "intent": request["intent"], "year": current_year(config),
                "task": task_out, "cache": cache_report,
                "folder_count": folder_count, "file_count": file_count,
            }

        keyword = request["keyword"]
        hits: list[dict[str, Any]] = []
        for current, _dirs, files in _walk(book):
            for fname in files:
                full = current / fname
                if full.is_symlink() or not title_matches(fname, keyword):
                    continue
                hits.append({
                    "id": local_id(full), "title": fname,
                    "relative_path": str(full.relative_to(book)),
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

    # ── work history ────────────────────────────────────────────────────────

    def history_folder(self, task_id: str, create: bool) -> str | None:
        folder = self._folder(task_id) / HISTORY_FOLDER
        if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
            raise TaskDeliveryError("History folder name is ambiguous or is not a folder")
        if not folder.exists():
            if not create:
                return None
            folder.mkdir()  # inherits umask so a shared library stays readable
        return self._remember(folder)

    def children(self, folder_id: str, name: str | None = None) -> list[dict[str, Any]]:
        items = []
        for path in sorted(self._folder(folder_id).iterdir()):
            if path.is_symlink() or not path.is_file():
                continue
            if name is not None and path.name != name:
                continue
            items.append({"id": local_id(path), "name": path.name, "mimeType": None,
                          "url": local_url(path)})
        return items

    def upload(self, folder_id: str, filename: str, body: str) -> None:
        if not NAME_RE.fullmatch(filename):
            raise WorkError("Invalid history filename")
        target = self._folder(folder_id) / filename
        if target.is_symlink():
            raise TaskDeliveryError("History record path is a symlink")
        if target.exists():  # immutable dated names: only identical content is a no-op
            if read_bounded(target) != body:
                raise TaskDeliveryError("Remote history content conflicts with the queued record")
            return
        write_user_file(target, body)

    def download(self, folder_id: str, filename: str) -> str:
        if not NAME_RE.fullmatch(filename):
            raise WorkError("Invalid history filename")
        target = self._folder(folder_id) / filename
        if target.is_symlink() or not target.is_file():
            raise WorkError("History record is missing")
        return read_bounded(target)
