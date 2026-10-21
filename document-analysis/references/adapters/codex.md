# Codex adapter

For an explicitly named local path, use the path directly. For a general request to find a personal document, search connected Google Drive first. If Drive has no relevant file or is unavailable, search local storage.

For a Drive file, search and read metadata first, then fetch stored files with the Drive connector's raw-file option and without inline base64. Materialize the returned authenticated file reference as a local copy under `C:\\Users\\sungt\\Downloads\\document-analysis\\` (WSL: `/mnt/c/Users/sungt/Downloads/document-analysis/`); use a collision-safe filename and never print, log, or retain its temporary download handle. Verify the saved byte count against Drive metadata before local processing; a native Google Docs/Sheets/Slides file arrives as an export with no Drive byte count, so say it is an export, check it is non-empty, and say it could not be verified against Drive. Do not modify the Drive original. Put the analysis directory beside the local copy and report both Windows and WSL paths. If this runtime cannot materialize the file reference safely, stop and report that limitation rather than treating connector text as a local extraction.

For a local Windows-mounted source, use Linux temporary storage for OCR and rendering, but place final outputs beside the source. Tell the user when a path is on `/mnt/c`.
