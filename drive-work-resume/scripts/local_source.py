#!/usr/bin/env python3
"""Local-filesystem work-library backend for drive-work-resume.

``LocalBackend`` implements the same backend interface as the Drive backend
(drive_work_resume.RcloneDrive / work_history.HistoryDrive): ``source``,
``outbox``, ``list_year``, ``list_books`` and ``run_task`` for listing and search,
plus ``history_folder``, ``children``, ``upload`` and ``download`` for work
history. The generic code (drive_work_resume.execute and work_history's resolve,
validate_task, checkpoint, flush and read_history) therefore serves both backends
unchanged; nothing outside this module special-cases a local library.

A folder's id is the SHA-256 of its resolved path bytes, which satisfies the
shared ``drive_id`` validator. Only folders this instance has itself listed can
be used, so history is always written under a verified direct child of the year
folder. Symlinked folders and files are never listed or followed. Search is
name/path based: there is no content index.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from drive_work_resume import (FOLDER_MIME, HISTORY_FOLDER, NAME_RE, TaskDeliveryError,
                               WorkError, current_year, title_matches, write_file_atomically)

MAX_RECORD_BYTES = 200000


def local_id(path: Path) -> str:
    """A path-stable, drive_id-compatible identifier (64 hex chars).

    Hashes the raw path bytes, so names that are not valid UTF-8 still work.
    """
    return hashlib.sha256(os.fsencode(path.resolve())).hexdigest()


def local_url(path: Path) -> str:
    return path.resolve().as_uri()


def display(name: str) -> str:
    """A printable form of a file-system name (undecodable bytes become U+FFFD)."""
    return os.fsencode(name).decode("utf-8", errors="replace")


def read_bounded(path: Path) -> str:
    """Read at most MAX_RECORD_BYTES and decode leniently.

    One oversized or non-UTF-8 record must not abort a whole history read.
    """
    with open(path, "rb") as handle:
        raw = handle.read(MAX_RECORD_BYTES + 1)
    if len(raw) > MAX_RECORD_BYTES:
        return "(기록이 너무 커서 생략됨)"
    return raw.decode("utf-8", errors="replace")


def _umask() -> int:
    mask = os.umask(0)
    os.umask(mask)
    return mask


def _modified_iso(entry: os.DirEntry) -> str | None:
    try:
        return datetime.fromtimestamp(entry.stat(follow_symlinks=False).st_mtime, timezone.utc).isoformat()
    except OSError:
        return None


def scan_tree(root: Path, problems: list[str]) -> Iterator[tuple[Path, list[os.DirEntry], list[os.DirEntry]]]:
    """Yield (folder, sub-folder entries, regular-file entries) for a whole tree.

    Symlinks, sockets and other special files are never yielded or followed.
    os.scandir caches each entry's type, so classifying costs no extra syscall.
    A folder that cannot be read is recorded in ``problems`` instead of being
    skipped silently, so callers can report the walk as incomplete.
    """
    pending = [root]
    while pending:
        current = pending.pop()
        try:
            with os.scandir(current) as iterator:
                entries = list(iterator)
        except OSError:
            problems.append("A folder could not be read; results may be incomplete")
            continue
        folders: list[os.DirEntry] = []
        files: list[os.DirEntry] = []
        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    folders.append(entry)
                elif entry.is_file(follow_symlinks=False):
                    files.append(entry)
            except OSError:
                problems.append("An entry could not be inspected; results may be incomplete")
        folders.sort(key=lambda entry: entry.name.casefold())
        yield current, folders, files
        pending.extend(Path(entry.path) for entry in reversed(folders))


def _md5(path: Path) -> str:
    digest = hashlib.md5()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


class LocalBackend:
    source = "local"
    outbox = "folder_outbox"  # separate from the Drive outbox; only this backend delivers it
    creates_books = True  # history sync may create a missing task folder here

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
        year = current_year(config)
        target = config["_source"]["root"] / year
        if not target.is_dir() or target.is_symlink():
            raise WorkError(f"Expected exactly one {year} folder; found 0")
        return {"id": self._remember(target), "name": year, "mimeType": FOLDER_MIME,
                "url": local_url(target)}

    def list_books(self, parent_id: str) -> list[dict[str, Any]]:
        parent = self._folder(parent_id)
        books = []
        with os.scandir(parent) as iterator:
            entries = [entry for entry in iterator
                       if not entry.is_symlink() and entry.is_dir(follow_symlinks=False)]
        for entry in sorted(entries, key=lambda entry: entry.name.casefold()):
            path = Path(entry.path)
            books.append({"id": self._remember(path), "name": display(entry.name), "parents": [parent_id],
                          "mimeType": FOLDER_MIME, "url": local_url(path)})
        return books

    def run_task(self, config: dict[str, Any], request: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
        book = self._folder(task["id"])
        problems: list[str] = []
        task_out = {"id": task["id"], "number": request["task_number"], "name": task["name"],
                    "url": task["url"], "source": self.source}

        def cache_report() -> dict[str, Any]:
            now = datetime.now(timezone.utc).isoformat()
            complete = not problems
            note = "; ".join(dict.fromkeys(problems)) if problems else "local filesystem; live listing"
            return {
                "started_at": now, "fetched_at": now, "stale": False,
                "enumeration_complete": complete, "coverage_note": note,
                "refresh_reason": "live", "refresh_complete": complete,
                "refresh_issue": None if complete else note, "folder_queries": 0,
            }

        if request["intent"] == "refresh_task":
            folder_count = file_count = 0
            for _current, folders, files in scan_tree(book, problems):
                folder_count += len(folders)
                file_count += len(files)
            return {
                "intent": request["intent"], "year": current_year(config),
                "task": task_out, "cache": cache_report(),
                "folder_count": folder_count, "file_count": file_count,
            }

        keyword = request["keyword"]
        hits: list[dict[str, Any]] = []
        for current, _folders, files in scan_tree(book, problems):
            for entry in files:
                title = display(entry.name)
                if not title_matches(title, keyword):
                    continue
                full = current / entry.name
                hits.append({
                    "id": local_id(full), "title": title,
                    "relative_path": display(str(full.relative_to(book))),
                    "mime_type": None, "modified_time": _modified_iso(entry),
                    "url": local_url(full), "matches": ["name"],
                })
        index_report: dict[str, Any] = {"queries": 0, "complete": True, "issues": []}
        if request["search_mode"] == "indexed_and_title":
            # No content index exists locally: a 관련 search is never complete.
            index_report = {"queries": 0, "complete": False,
                            "issues": ["Local source: file contents were not searched; names/paths only"]}
        return {
            "intent": request["intent"], "year": current_year(config),
            "task": task_out, "keyword": keyword, "search_mode": request["search_mode"],
            "cache": cache_report(), "index": index_report,
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
        with os.scandir(self._folder(folder_id)) as iterator:
            for entry in iterator:
                if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                    continue
                if name is not None and entry.name != name:
                    continue
                path = Path(entry.path)
                items.append({"id": local_id(path), "name": entry.name, "mimeType": None,
                              "url": local_url(path), "md5Checksum": _md5(path)})
        return sorted(items, key=lambda item: item["name"])

    def ensure_book(self, config: dict[str, Any], name: str) -> dict[str, Any]:
        """Create (or reuse) the named task folder so synced history has a home."""
        if not name or name in (".", "..") or "/" in name or "\x00" in name or "�" in name:
            raise TaskDeliveryError(f"Task folder name '{name}' cannot be created locally")
        year = config["_source"]["root"] / current_year(config)
        book = year / name
        if year.is_symlink() or book.is_symlink():
            raise TaskDeliveryError("A symlink is in the way of the task folder")
        book.mkdir(parents=True, exist_ok=True)  # umask permissions, like the rest of the library
        return {"id": self._remember(book), "name": name, "mimeType": FOLDER_MIME,
                "url": local_url(book)}

    def upload(self, folder_id: str, filename: str, body: str) -> None:
        if not NAME_RE.fullmatch(filename):
            raise WorkError("Invalid history filename")
        target = self._folder(folder_id) / filename
        if target.is_symlink():
            raise TaskDeliveryError("History record path is a symlink")
        try:
            # Exclusive create: a record is immutable, even against a racing writer
            # or a sync client; normal permissions keep a shared library readable.
            write_file_atomically(target, body, mode=0o666 & ~_umask(), exclusive=True)
        except FileExistsError:
            if target.is_symlink() or read_bounded(target) != body:
                raise TaskDeliveryError("Remote history content conflicts with the queued record") from None

    def download(self, folder_id: str, filename: str, strict: bool = False) -> str:
        """Read a record. ``strict`` (used when copying) refuses instead of degrading.

        A lenient read shows a placeholder for an oversized or non-UTF-8 file; a
        strict read raises, so such a placeholder is never copied to another library.
        """
        if not NAME_RE.fullmatch(filename):
            raise WorkError("Invalid history filename")
        target = self._folder(folder_id) / filename
        if target.is_symlink() or not target.is_file():
            raise WorkError("History record is missing")
        if not strict:
            return read_bounded(target)
        with open(target, "rb") as handle:
            raw = handle.read(MAX_RECORD_BYTES + 1)
        try:
            if len(raw) > MAX_RECORD_BYTES:
                raise ValueError("too large")
            return raw.decode("utf-8")
        except ValueError:
            raise TaskDeliveryError(f"'{filename}' is not a valid history record (too large or not UTF-8)") from None
