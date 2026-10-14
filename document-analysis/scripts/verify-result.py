#!/usr/bin/env python3
"""Verify an analysis directory and write a concise quality report."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("analysis_dir", type=Path)
    parser.add_argument("--strict", action="store_true", help="Return nonzero for warnings as well as failures")
    arguments = parser.parse_args()
    analysis_dir = arguments.analysis_dir.expanduser().resolve()
    manifest_path = analysis_dir / "manifest.json"
    report_path = analysis_dir / "quality-report.md"
    failures: list[str] = []
    warnings: list[str] = []
    if not manifest_path.is_file():
        print(f"Missing manifest: {manifest_path}", file=sys.stderr)
        return 2
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"Invalid manifest: {error}", file=sys.stderr)
        return 2
    for item in manifest.get("warnings", []):
        warnings.append("Source/tool diagnostic: " + str(item))

    source = Path(str(manifest.get("source", "")))
    if not source.is_file():
        failures.append(f"Source is unavailable: `{source}`")
    elif manifest.get("source_sha256") != sha256(source):
        failures.append("Source SHA-256 differs from the value recorded at analysis start.")

    expected_artifacts = manifest.get("artifacts", [])
    for artifact in expected_artifacts:
        candidate = analysis_dir / artifact
        if not candidate.is_file() or candidate.stat().st_size == 0:
            failures.append(f"Missing or empty recorded artifact: `{artifact}`")

    extracted = analysis_dir / "extracted.txt"
    if not extracted.is_file() or extracted.stat().st_size == 0:
        failures.append("Missing or empty required artifact: `extracted.txt`")
    else:
        text = extracted.read_text(encoding="utf-8", errors="replace")
        if len(text.strip()) < 40:
            warnings.append("Extracted text is very short; inspect the document or use OCR.")
        replacement_ratio = text.count("\ufffd") / max(len(text), 1)
        if replacement_ratio > 0.01:
            warnings.append("Extracted text contains a high proportion of replacement characters.")
        page_segments = [page.strip() for page in text.split("\f")]
        while page_segments and not page_segments[-1]:
            page_segments.pop()
        page_texts = page_segments
        expected_pages = manifest.get("page_count")
        if expected_pages is None and source.suffix.lower() == ".pdf":
            try:
                info = subprocess.run(["pdfinfo", str(source)], capture_output=True, text=True, timeout=45, check=False)
                if info.returncode == 0:
                    for line in info.stdout.splitlines():
                        if line.startswith("Pages:"):
                            expected_pages = int(line.split(":", 1)[1].strip())
                            break
            except (OSError, subprocess.TimeoutExpired):
                pass
        nonempty_count = sum(bool(page) for page in page_texts)
        if expected_pages is not None and len(page_texts) != expected_pages:
            warnings.append(f"Text extraction yielded {len(page_texts)} page boundaries ({nonempty_count} with text); PDF metadata reports {expected_pages} pages.")
        sparse_pages = [str(index) for index, page in enumerate(page_texts, start=1) if len(page) < 12]
        if sparse_pages:
            warnings.append("Pages with very little extracted text (possible scanned pages): " + ", ".join(sparse_pages))

    if any(item.get("name") == "ocrmypdf" for item in manifest.get("processors", [])):
        warnings.append("OCR text can contain recognition errors; compare the OCR output with the rendered source page(s).")
    ocr_log = analysis_dir / "ocr-run.log"
    if ocr_log.is_file():
        log_text = ocr_log.read_text(encoding="utf-8", errors="replace")
        if "possibly poor OCR" in log_text.lower() or "lots of diacritics" in log_text.lower():
            warnings.append("OCR engine reported a low-confidence or potentially poor page; visual review is required.")
    pymupdf_log = analysis_dir / "pymupdf-diagnostics.log"
    if pymupdf_log.is_file() and pymupdf_log.stat().st_size:
        warnings.append("PyMuPDF emitted parser diagnostics; inspect `pymupdf-diagnostics.log` and review affected pages.")

    lines = [
        "# Analysis quality report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Source: `{source}`",
        f"Result: **{'FAIL' if failures else ('PASS WITH WARNINGS' if warnings else 'PASS')}**",
        "",
        "## Processors",
        "",
    ]
    processors = manifest.get("processors", [])
    lines.extend([f"- `{item.get('name', 'unknown')}` — {item.get('version', 'unknown')}" for item in processors] or ["- None recorded"])
    lines.extend(["", "## Failures", ""])
    lines.extend([f"- {item}" for item in failures] or ["- None"])
    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- {item}" for item in warnings] or ["- None"])
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if "quality-report.md" not in manifest.setdefault("artifacts", []):
        manifest["artifacts"].append("quality-report.md")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(report_path)
    if failures or (arguments.strict and warnings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
