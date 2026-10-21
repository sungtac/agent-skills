# Drive scope and cache contract

## Private configuration

Store private configuration at ~/.codex/drive-work-resume/config.json with owner-only permissions. Keep Drive IDs, file names, and paths out of the source repository.

~~~json
{
  "schema_version": 1,
  "year_parent": {
    "id": "GOOGLE_DRIVE_FOLDER_ID",
    "label": "02_업무"
  },
  "active_year": {
    "mode": "system",
    "override": null
  },
  "task_number_regex": "^(?P<number>0*[1-9][0-9]{0,2})_",
  "cache": {
    "directory": "~/.codex/drive-work-resume/cache",
    "max_age_hours": 168,
    "refresh_policy": "bootstrap_if_missing_or_explicit_or_exhaustive",
    "max_parent_ids_per_index_query": 20,
    "max_parent_queries": 60,
    "max_pages_per_parent_query": 5,
    "list_children_top_k": 1000
  }
}
~~~

active_year.mode: system means the current system year. Set override only when the owner deliberately wants a different year. A missing matching year folder is an error to report, not a reason to search another year.

### Local folder source

To point the same year-folder > `NN번` task structure at a local directory instead of Drive, add a `source` block. `year_parent`, `cache`, and the rclone remote are then unnecessary.

~~~json
{
  "schema_version": 1,
  "active_year": { "mode": "system", "override": null },
  "task_number_regex": "^(?P<number>0*[1-9][0-9]{0,2})_",
  "source": { "type": "local", "root": "/absolute/path/to/02_업무" }
}
~~~

`root` must be an existing absolute directory; `<root>/<year>/` holds the work books. Absence of `source` (or `"type": "drive"`) keeps the Google Drive backend. Local listing and search are live — there is no cache, so the reported cache is always fresh and complete — and search matches file names/paths only (no content index). A symlinked book or file is never listed or followed. History records are immutable dated files in the selected book's `_업무기록` folder; like Drive, a checkpoint is first queued in a private per-backend outbox (`folder_outbox`, separate from the Drive `outbox`) and then filed, so a failure leaves it pending rather than lost.

Only one source is active. There is no automatic Drive↔local priority or fallback, because alternating would split a task's history across two libraries. Keep one canonical library; when changing it, checkpoint first and copy each task's `_업무기록` folder into the new library (see SKILL.md, "Choosing a source").

## Task resolution

1. List the configured year folder directly.
2. Keep folders whose names match task_number_regex.
3. Match the user's number against the numeric value of the named number group, so `01_` is task 1.
4. Return one match only. On zero or multiple matches, display candidates without guessing.

A display order is never an identifier.

For the current-work list, do not apply this numbered-task filter: show every direct child folder of the selected year folder. Numberless folders are work folders too; only a numbered lookup requires the NN_ prefix.

## Cache format

Store one cache per task under the configured cache directory. It must include the task root, the time of the directory walk, every observed descendant folder, and file metadata only. Do not store file bodies.

~~~json
{
  "schema_version": 1,
  "task_folder_id": "GOOGLE_DRIVE_FOLDER_ID",
  "task_relative_root": "18_Example",
  "fetched_at": "2026-10-21T00:00:00Z",
  "enumeration_complete": true,
  "coverage_note": "all listed folders completed below configured limits",
  "folders": [
    {
      "id": "GOOGLE_DRIVE_FOLDER_ID",
      "relative_path": "."
    }
  ],
  "files": [
    {
      "id": "GOOGLE_DRIVE_FILE_ID",
      "title": "example-manual.pdf",
      "parent_ids": ["GOOGLE_DRIVE_FOLDER_ID"],
      "relative_path": "03_회의·보고/03_매뉴얼/example-manual.pdf",
      "mime_type": "application/pdf",
      "modified_time": "2026-10-21T00:00:00Z",
      "url": "https://drive.google.com/file/d/GOOGLE_DRIVE_FILE_ID/view"
    }
  ]
}
~~~

Build this cache automatically on the first search of a task, or refresh it for an explicit 새로고침, 전체, 모두, or 정확히 request. For the desktop connector, walk folders with list_folder, record IDs, paths, and file metadata, and mark enumeration_complete: false if any folder is truncated, paginated without all pages retrieved, inaccessible, or fails. The CLI helper uses scoped `rclone backend query` calls and reports failed queries or the configured query limit as incomplete. Cache data is collected over a walk; it is not an atomic snapshot.

If a refresh fails, retain an existing cache and clearly report that the requested refresh and any dependent index search were incomplete. Do not repeat a whole traversal on authentication, quota, or timeout failures; split a grouped filter only when the server rejects the filter itself.

Do not infer that a stale cache will notice a new subfolder, renamed file, or moved file. A normal search must say that its scope is limited to the cached timestamp.

## Search procedure

1. Search the cached file titles locally with the user keyword. These are title matches and require no Drive search.
2. When the parser returns search_mode indexed_and_title, also query the Google Drive index. Its results can match names or indexed content. In the desktop connector set best_effort_fetch=false and read search entries from its `results` collection; `list_folder` uses a separate `files` collection. In CLI the helper issues a scoped `fullText contains` query through rclone and does not download file bodies.
3. Build a parent filter from cached folder IDs. Use verified OR groups of at most max_parent_ids_per_index_query. If a group fails, split it into smaller groups. Do not assume a larger untested group works.
4. For the desktop connector follow each returned page token until exhausted or max_pages_per_parent_query is reached. The rclone backend query handles its own pagination. Stop after max_parent_queries and state that the result is partial.
5. Keep a Drive result only if at least one of its parent IDs is cached. Deduplicate by file ID. If a file has several cached parents, use the shortest cached relative path and say it has multiple paths when useful.
6. Exclude trashed items when the Drive tool supports that filter.

A no-result response from the Drive index means no index match in the searched cached scope. It does not prove that unindexed file contents lack the keyword.

## Refresh reporting

Every subtree-search response states:

- selected task folder
- cache timestamp
- cache completeness
- folder, query, and page limits reached, if any
- whether the user requested an exhaustive refresh

The refresh operation reads Drive and updates only the local cache. The CLI invocation can also retry previously queued history uploads, which write only to the verified task's `_업무기록` folder.
