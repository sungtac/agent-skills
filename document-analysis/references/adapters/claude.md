# Claude Code adapter

Claude Code has no Drive connector in this setup; it reaches Google Drive through the owner's configured rclone remote (`gdrive:`), read-only. The rules mirror the Codex adapter so both orchestrators behave the same way.

For an explicitly named local path, use the path directly. For a general request to find a personal document, search Google Drive first. If Drive has no relevant file, or `rclone listremotes` has no `gdrive:` remote, search local storage and say Drive was not searched.

Search Drive by metadata only, scoped to non-trashed files, for example:

    rclone backend query gdrive: "name contains '<keyword>' and trashed = false"

Quote the keyword for the Drive query language (escape `\` and `'`). Show the matching names, folders, and modification times; on several plausible matches, ask which one rather than guessing.

Copy the chosen file by its ID into the Windows user's Downloads folder, under `document-analysis/` (on this PC `C:\Users\sungt\Downloads\document-analysis\`, WSL `/mnt/c/Users/sungt/Downloads/document-analysis/`; on another PC resolve it with `wslpath "$(cmd.exe /c 'echo %USERPROFILE%' 2>/dev/null | tr -d '\r')"/Downloads`, and outside WSL use `~/Downloads`):

    rclone backend copyid gdrive: <FILE_ID> <downloads>/document-analysis/<collision-safe-name>

For a native Google Docs/Sheets/Slides file add `--drive-export-formats docx,xlsx,pptx,pdf` and say the copy is an export, not the original bytes. `copyid` uses the given last path component verbatim as the file name, so give an export the extension of the format it receives (`.docx` for Docs, `.xlsx` for Sheets, `.pptx` for Slides, otherwise `.pdf`). Use a collision-safe filename and check it does not exist first: `copyid` copies like `rclone copyto` and would replace an existing local file.

Verify the saved byte count (and `md5Checksum` when Drive reports one) against the query metadata before local processing; on a mismatch, delete the partial copy and stop. An export has no Drive `size` or `md5Checksum`; check it is non-empty instead and say it could not be verified against Drive. Never write, rename, move, or delete anything on Drive. Put the analysis directory beside the local copy and report both Windows and WSL paths. If rclone cannot be used, stop and report that limitation instead of treating any text preview as a local extraction.

For a local Windows-mounted source, use Linux temporary storage for OCR and rendering, but place final outputs beside the source. Tell the user when a path is on `/mnt/c`.
