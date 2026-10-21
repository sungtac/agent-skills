#!/usr/bin/env python3
"""List or search work folders and retry previously queued history uploads."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any

from parse_request import parse_request

FOLDER_MIME = "application/vnd.google-apps.folder"
DEFAULT_CONFIG = Path.home() / ".codex/drive-work-resume/config.json"


class WorkError(Exception):
    """An expected configuration, scope, or Drive operation failure."""


class GroupQueryError(WorkError):
    """A Drive query was rejected as an invalid grouped filter."""


class TaskDeliveryError(WorkError):
    """A task-specific scope or content conflict, not a general network failure."""


# Shared by every backend. Defined here (not in work_history) so a backend never
# has to import work_history, which is also run directly as ``__main__``.
HISTORY_FOLDER = "_업무기록"
NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{6})_(\d{6})_([a-f0-9]{32})\.md$")


def quote_drive(value: str) -> str:
    """Quote a literal for the Google Drive query language."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def drive_id(value: Any) -> str:
    """Reject unexpected IDs before placing them in a query."""
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise WorkError("Invalid Drive folder ID in configuration or cache")
    return value


class RcloneDrive:
    """Google Drive work-library backend (rclone).

    Backend interface shared with local_source.LocalBackend: ``source``,
    ``outbox``, ``list_year(config)``, ``list_books(parent_id)`` and
    ``run_task(config, request, task)``; work_history.HistoryDrive adds the
    history methods (``history_folder``, ``children``, ``upload``, ``download``).
    """

    source = "drive"
    outbox = "outbox"

    def __init__(self, remote: str = "gdrive:") -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]+:", remote):
            raise WorkError("Invalid rclone remote")
        self.remote = remote

    def query(self, expression: str) -> list[dict[str, Any]]:
        command = [
            "rclone", "backend", "query", self.remote, expression,
            "--retries", "1", "--low-level-retries", "6",
            "--contimeout", "8s", "--timeout", "45s",
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=70, check=False)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise WorkError("Google Drive query could not be completed") from exc
        if result.returncode:
            stderr = result.stderr.lower()
            if "error 400" in stderr and ("invalid" in stderr or "query" in stderr):
                raise GroupQueryError("Google Drive rejected the query filter")
            raise WorkError("Google Drive query failed; check the gdrive connection or API quota")
        try:
            items = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise WorkError("Google Drive returned an invalid query response") from exc
        # rclone's Drive backend serializes a successful empty search as null.
        if items is None:
            return []
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise WorkError("Google Drive returned an unexpected query response")
        return items

    def list_year(self, config: dict[str, Any]) -> dict[str, Any]:
        return year_folder(self, config)

    def list_books(self, parent_id: str) -> list[dict[str, Any]]:
        return direct_folders(self, parent_id)

    def run_task(self, config: dict[str, Any], request: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
        return drive_task_operation(self, config, request, task)


def read_config(path: Path) -> dict[str, Any]:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
        if config.get("schema_version") != 1:
            raise ValueError("Unsupported schema")
        if config["active_year"].get("mode") != "system":
            raise ValueError("Unsupported year mode")
        re.compile(config["task_number_regex"])
        # Source selects the work-library backend. Absence or "drive" keeps the
        # Google Drive behavior; "local" points the same year-folder > NN번 task
        # structure at a local filesystem directory (no rclone, no cache needed).
        source = config.get("source") or {"type": "drive"}
        stype = source.get("type", "drive")
        if stype == "local":
            root = Path(str(source["root"])).expanduser()
            if not root.is_absolute() or not root.is_dir():
                raise ValueError("Local source root must be an existing absolute directory")
            config["_source"] = {"type": "local", "root": root}
        elif stype == "drive":
            drive_id(config["year_parent"]["id"])
            limits = config["cache"]
            for key in ("max_parent_ids_per_index_query", "max_parent_queries", "max_age_hours"):
                if int(limits[key]) < 1:
                    raise ValueError("Invalid cache limit")
            config["_source"] = {"type": "drive"}
        else:
            raise ValueError("Unsupported source type")
        return config
    except (OSError, KeyError, TypeError, ValueError, re.error) as exc:
        raise WorkError("Private work-library configuration is missing or invalid") from exc


def parent_filter(parent_ids: list[str]) -> str:
    if not parent_ids:
        raise WorkError("A scoped parent folder is required")
    return "(" + " or ".join(f"{quote_drive(drive_id(item))} in parents" for item in parent_ids) + ")"


def current_year(config: dict[str, Any]) -> str:
    override = config["active_year"].get("override")
    year = str(override if override is not None else datetime.now().astimezone().year)
    if not re.fullmatch(r"[0-9]{4}", year):
        raise WorkError("Configured year is invalid")
    return year


def year_folder(drive: RcloneDrive, config: dict[str, Any]) -> dict[str, Any]:
    parent = drive_id(config["year_parent"]["id"])
    year = current_year(config)
    expression = (
        f"{parent_filter([parent])} and mimeType = {quote_drive(FOLDER_MIME)} "
        f"and name = {quote_drive(year)} and trashed = false"
    )
    folders = [item for item in drive.query(expression)
               if item.get("name") == year and item.get("mimeType") == FOLDER_MIME
               and parent in (item.get("parents") or [])]
    if len(folders) != 1:
        raise WorkError(f"Expected exactly one {year} folder; found {len(folders)}")
    drive_id(folders[0].get("id"))
    return folders[0]


def direct_folders(drive: RcloneDrive, parent_id: str) -> list[dict[str, Any]]:
    expression = (
        f"{parent_filter([parent_id])} and mimeType = {quote_drive(FOLDER_MIME)} "
        "and trashed = false"
    )
    folders = [
        item for item in drive.query(expression)
        if item.get("mimeType") == FOLDER_MIME and parent_id in item.get("parents", [])
    ]
    return sorted(folders, key=lambda item: item.get("name", "").casefold())


def task_number(name: str, pattern: str) -> str | None:
    match = re.match(pattern, name)
    if not match:
        return None
    try:
        return str(int(match.group("number")))
    except (IndexError, ValueError):
        raise WorkError("Invalid task-number pattern in configuration") from None


def resolve_task(folders: list[dict[str, Any]], number: str, pattern: str) -> dict[str, Any]:
    matches = [item for item in folders if task_number(item.get("name", ""), pattern) == number]
    if len(matches) != 1:
        candidates = matches if matches else [item for item in folders if task_number(item.get("name", ""), pattern)]
        names = ", ".join(item.get("name", "") for item in candidates)
        raise WorkError(f"Task number {number} has {len(matches)} matching folders; candidates: {names}")
    drive_id(matches[0].get("id"))
    return matches[0]


def join_relative(parent: str, name: str) -> str:
    return name if parent == "." else f"{parent}/{name}"


def file_url(item: dict[str, Any]) -> str | None:
    link = item.get("webViewLink") or item.get("url")
    if link:
        return str(link)
    item_id = item.get("id")
    return f"https://drive.google.com/open?id={item_id}" if item_id else None


def refresh_cache(drive: RcloneDrive, task: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    settings = config["cache"]
    group_size = int(settings["max_parent_ids_per_index_query"])
    query_limit = int(settings["max_parent_queries"])
    root_id = drive_id(task["id"])
    folders = {root_id: {"id": root_id, "relative_path": "."}}
    files: dict[str, dict[str, Any]] = {}
    pending = [root_id]
    problems: list[str] = []
    query_count = 0
    started = datetime.now(timezone.utc).isoformat()

    while pending:
        if query_count >= query_limit:
            problems.append("Folder-query limit reached")
            break
        group, pending = pending[:group_size], pending[group_size:]
        expression = f"{parent_filter(group)} and trashed = false"
        query_count += 1
        try:
            entries = drive.query(expression)
        except GroupQueryError:
            if len(group) > 1:
                group_size = max(1, len(group) // 2)
                pending = group + pending
            else:
                problems.append("A folder could not be listed")
            continue
        except WorkError:
            problems.append("Google Drive listing failed; refresh stopped")
            break
        for item in entries:
            item_id, title = item.get("id"), item.get("name")
            parents = item.get("parents") or []
            relevant = [parent for parent in parents if parent in group and parent in folders]
            if not item_id or not isinstance(title, str) or not relevant:
                problems.append("Some listing metadata was missing or outside the requested parents")
                continue
            path = min((join_relative(folders[parent]["relative_path"], title) for parent in relevant), key=len)
            if item.get("mimeType") == FOLDER_MIME:
                drive_id(item_id)
                if item_id not in folders:
                    folders[item_id] = {"id": item_id, "relative_path": path}
                    pending.append(item_id)
                elif len(path) < len(folders[item_id]["relative_path"]):
                    folders[item_id]["relative_path"] = path
                continue
            previous = files.get(item_id)
            combined_parents = set(previous.get("parent_ids", [])) if previous else set()
            combined_parents.update(relevant)
            files[item_id] = {
                "id": item_id,
                "title": title,
                "parent_ids": sorted(combined_parents),
                "relative_path": min([path, previous["relative_path"]], key=len) if previous else path,
                "mime_type": item.get("mimeType"),
                "modified_time": item.get("modifiedTime"),
                "url": file_url(item),
            }

    return {
        "schema_version": 1,
        "task_folder_id": root_id,
        "task_relative_root": task.get("name"),
        "started_at": started,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "enumeration_complete": not problems,
        "coverage_note": "; ".join(dict.fromkeys(problems)) if problems else "all queried folders completed",
        "folder_queries": query_count,
        "folders": sorted(folders.values(), key=lambda item: item["relative_path"].casefold()),
        "files": sorted(files.values(), key=lambda item: item["relative_path"].casefold()),
    }


def cache_path(config: dict[str, Any], root_id: str) -> Path:
    return Path(config["cache"]["directory"]).expanduser() / f"{drive_id(root_id)}.json"


def load_cache(config: dict[str, Any], root_id: str, number: str) -> dict[str, Any] | None:
    path = cache_path(config, root_id)
    legacy = path.parent / f"{number}.json"
    for candidate in (path, legacy):
        try:
            cache = json.loads(candidate.read_text(encoding="utf-8"))
            if (
                cache.get("schema_version") == 1 and cache.get("task_folder_id") == root_id
                and isinstance(cache.get("folders"), list) and isinstance(cache.get("files"), list)
                and cache.get("fetched_at")
            ):
                return cache
        except (OSError, ValueError, AttributeError):
            continue
    return None


def save_cache(config: dict[str, Any], cache: dict[str, Any]) -> None:
    path = cache_path(config, cache["task_folder_id"])
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temp_name = handle.name
            os.fchmod(handle.fileno(), 0o600)
            json.dump(cache, handle, ensure_ascii=False, indent=2)
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def cache_is_stale(cache: dict[str, Any], max_age_hours: int) -> bool:
    try:
        when = datetime.fromisoformat(cache["fetched_at"].replace("Z", "+00:00"))
        if when.tzinfo is None:
            return True
        return datetime.now(timezone.utc) - when > timedelta(hours=max_age_hours)
    except (KeyError, ValueError, TypeError):
        return True


def title_matches(title: str, keyword: str) -> bool:
    words = keyword.casefold().split()
    return bool(words) and all(word in title.casefold() for word in words)


def index_search(
    drive: RcloneDrive, cache: dict[str, Any], keyword: str, config: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    settings = config["cache"]
    folder_paths = {drive_id(folder["id"]): folder["relative_path"] for folder in cache["folders"]}
    ids = list(folder_paths)
    chunk_size = int(settings["max_parent_ids_per_index_query"])
    pending = [ids[index:index + chunk_size] for index in range(0, len(ids), chunk_size)]
    clauses = [f"fullText contains {quote_drive(word)}" for word in keyword.split() if word]
    if not clauses:
        raise WorkError("Search keyword is empty")
    found: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    calls = 0
    while pending:
        if calls >= int(settings["max_parent_queries"]):
            problems.append("Index-query limit reached")
            break
        group = pending.pop(0)
        expression = f"{parent_filter(group)} and trashed = false and " + " and ".join(clauses)
        calls += 1
        try:
            entries = drive.query(expression)
        except GroupQueryError:
            if len(group) > 1:
                middle = len(group) // 2
                pending[0:0] = [group[:middle], group[middle:]]
            else:
                problems.append("A folder's index query failed")
            continue
        except WorkError:
            problems.append("Google Drive index query failed; search stopped")
            break
        for item in entries:
            parents = [parent for parent in (item.get("parents") or []) if parent in group and parent in folder_paths]
            if not item.get("id") or not item.get("name") or not parents:
                problems.append("An index result lacked a verified parent or required metadata")
                continue
            if item.get("mimeType") == FOLDER_MIME:
                continue
            relative = min((join_relative(folder_paths[parent], item["name"]) for parent in parents), key=len)
            found[item["id"]] = {
                "id": item["id"], "title": item["name"], "parent_ids": parents,
                "relative_path": relative, "mime_type": item.get("mimeType"),
                "modified_time": item.get("modifiedTime"), "url": file_url(item),
            }
    return list(found.values()), {"queries": calls, "complete": not problems, "issues": list(dict.fromkeys(problems))}


def execute(drive: Any, config: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    """Run a parsed request against any backend (Drive or local folder)."""
    if request["intent"] == "unrecognized":
        raise WorkError(request["reason"])
    year = drive.list_year(config)
    folders = drive.list_books(drive_id(year["id"]))
    if request["intent"] == "list_current_tasks":
        return {
            "intent": request["intent"], "year": current_year(config),
            "folders": [
                {"name": item["name"], "number": task_number(item["name"], config["task_number_regex"]), "url": file_url(item)}
                for item in folders
            ],
        }
    task = resolve_task(folders, request["task_number"], config["task_number_regex"])
    return drive.run_task(config, request, task)


def drive_task_operation(
    drive: RcloneDrive, config: dict[str, Any], request: dict[str, Any], task: dict[str, Any]
) -> dict[str, Any]:
    """Drive refresh/search for one resolved task: metadata cache plus optional index query."""
    root_id = drive_id(task["id"])
    cache = load_cache(config, root_id, request["task_number"])
    reason = "requested" if request["refresh_requested"] else "missing" if cache is None else None
    refresh_report = {"reason": reason, "complete": None, "folder_queries": 0, "issue": None}
    if reason:
        updated = refresh_cache(drive, task, config)
        refresh_report.update({
            "complete": updated["enumeration_complete"],
            "folder_queries": updated["folder_queries"],
            "issue": None if updated["enumeration_complete"] else updated["coverage_note"],
        })
        if updated["enumeration_complete"] or cache is None:
            cache = updated
            save_cache(config, cache)
    assert cache is not None
    cache_report = {
        "started_at": cache.get("started_at"), "fetched_at": cache["fetched_at"],
        "stale": cache_is_stale(cache, int(config["cache"]["max_age_hours"])),
        "enumeration_complete": cache.get("enumeration_complete", False),
        "coverage_note": cache.get("coverage_note"), "refresh_reason": reason,
        "refresh_complete": refresh_report["complete"],
        "refresh_issue": refresh_report["issue"],
        "folder_queries": refresh_report["folder_queries"],
    }
    if request["intent"] == "refresh_task":
        return {
            "intent": request["intent"], "year": current_year(config),
            "task": {"id": root_id, "number": request["task_number"], "name": task["name"], "url": file_url(task)},
            "cache": cache_report,
            "folder_count": len(cache["folders"]), "file_count": len(cache["files"]),
        }
    hits: dict[str, dict[str, Any]] = {}
    for item in cache["files"]:
        if title_matches(item.get("title", ""), request["keyword"]):
            hits[item["id"]] = {**item, "matches": ["title"]}
    index_report = {"queries": 0, "complete": True, "issues": []}
    if request["search_mode"] == "indexed_and_title":
        if reason and not refresh_report["complete"]:
            indexed = []
            index_report = {"queries": 0, "complete": False, "issues": ["Index search skipped because the refresh did not complete"]}
        else:
            indexed, index_report = index_search(drive, cache, request["keyword"], config)
        for item in indexed:
            labels = ["drive_index"]
            if title_matches(item["title"], request["keyword"]):
                labels.insert(0, "title")
            hits[item["id"]] = {**item, "matches": labels}
    return {
        "intent": request["intent"], "year": current_year(config),
        "task": {"id": root_id, "number": request["task_number"], "name": task["name"], "url": file_url(task)},
        "keyword": request["keyword"], "search_mode": request["search_mode"],
        "cache": cache_report,
        "index": index_report,
        "results": sorted(hits.values(), key=lambda item: item["relative_path"].casefold()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", required=True, help="Korean user request")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--state-dir", type=Path, default=Path.home() / ".codex/drive-work-resume")
    args = parser.parse_args()
    # Run as a script, this file is ``__main__`` while work_history/local_source
    # import it again as ``drive_work_resume``; catch both copies of WorkError.
    import work_history
    try:
        config = read_config(args.config)
        backend = work_history.make_backend(config)
        result = execute(backend, config, parse_request(args.text))
    except (WorkError, work_history.WorkError, OSError, ValueError, KeyError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1
    # Bind only after a scoped task has been resolved. A conflicting unsaved
    # task is never silently replaced; the search result itself is still useful.
    if result.get("task"):
        try:
            task = {**result["task"], "year": result["year"]}
            work_history.bind(args.state_dir, work_history.session_id(), task)
            result["history_binding"] = "bound_and_marked_for_checkpoint"
        except (work_history.WorkError, OSError) as exc:
            result["history_binding"] = "not_bound"
            result["history_issue"] = str(exc)
    try:
        sync = work_history.flush(backend, config, args.state_dir)
        if sync["pending"] or sync["delivered"] or sync["issues"]:
            result["history_sync"] = sync
    except (work_history.WorkError, OSError) as exc:
        result["history_sync_error"] = str(exc)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
