---
name: document-analysis
description: Analyze local or connected-cloud documents without altering originals. Use for PDF text extraction, layout or table inspection, scanned-document OCR, multi-format extraction, and evidence-backed document summaries; not for creating or substantively editing documents.
---

# Document Analysis

Use this skill to obtain reliable, traceable source material before interpreting a document. The active agent chooses and interprets the extraction output; local tools do not call an LLM.

The bundled command scripts target Linux/WSL. In a native Windows runtime, use them only when a compatible Bash/Linux environment with the dependencies is available; otherwise report the platform limitation.

## Safety and output contract

- Never modify, move, delete, or overwrite the source document.
- For a named local path, use that path. For a general personal-document search, read the active runtime adapter before searching.
- Save persistent outputs beside the local analysis copy in `<source-name>.analysis/`. If it already exists, create a timestamp-suffixed directory instead of overwriting it.
- Write temporary OCR and rendering files outside the source directory. If the source directory is not writable, report that and request an output location; do not silently redirect results.
- Do not bypass encryption, attempt passwords, or upload document contents to an external service unless the user explicitly requests it.

## Workflow

1. Read [routing.md](references/routing.md), run `scripts/health-check.sh` and `scripts/inspect-document.py`, then create the result folder with `scripts/prepare-analysis-dir.py` before writing artifacts.
2. For an ordinary text PDF, use Poppler. Read [pdf-extraction.md](references/pdf-extraction.md) when layout, tables, images, or coordinates matter; use `scripts/extract-structure.sh` for the PyMuPDF artifact.
3. For a scanned or poor-quality PDF, read [ocr.md](references/ocr.md), run OCR with `kor+eng` by default, then extract from the generated OCR PDF.
4. For non-PDF office documents, read [tika.md](references/tika.md) and use `scripts/extract-document-tika.sh`.
5. Run `scripts/verify-result.py` before relying on an extraction. Read [verification.md](references/verification.md) for high-stakes or disputed material.
6. Report source, output path, processors and versions, limitations, and pages needing review.

## Runtime adapters

- In Codex, read [adapters/codex.md](references/adapters/codex.md).
- In Hermes, read [adapters/hermes.md](references/adapters/hermes.md).
- In another runtime, use the generic rules above and identify its file and cloud-document access method before acting.
