#!/usr/bin/env python3
"""Inspect a document without modifying it and emit routing evidence as JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def command_output(args: list[str]) -> tuple[int | None, str, str]:
    try:
        completed = subprocess.run(args, capture_output=True, text=True, timeout=45)
        return completed.returncode, completed.stdout, completed.stderr
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, "", str(error)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, help="Write JSON to this path instead of stdout")
    arguments = parser.parse_args()
    source = arguments.source.expanduser().resolve()

    if not source.is_file():
        print(f"Not a readable file: {source}", file=sys.stderr)
        return 2

    result: dict[str, object] = {
        "schema_version": 1,
        "inspected_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "filename": source.name,
        "suffix": source.suffix.lower(),
        "size_bytes": source.stat().st_size,
        "sha256": sha256(source),
        "file_type": None,
        "pdf": None,
        "routing": {"recommended_processor": "apache-tika", "needs_ocr_review": False, "reasons": []},
        "warnings": [],
    }

    if shutil.which("file"):
        _, stdout, _ = command_output(["file", "--brief", "--mime-type", str(source)])
        result["file_type"] = stdout.strip() or None

    is_pdf = source.suffix.lower() == ".pdf" or result["file_type"] == "application/pdf"
    if is_pdf:
        pdf: dict[str, object] = {"pdfinfo_available": bool(shutil.which("pdfinfo"))}
        result["pdf"] = pdf
        result["routing"] = {"recommended_processor": "poppler", "needs_ocr_review": False, "reasons": []}
        if not shutil.which("pdfinfo"):
            result["warnings"].append("pdfinfo is unavailable; PDF encryption and page count were not inspected.")
        else:
            code, stdout, stderr = command_output(["pdfinfo", str(source)])
            pdf["pdfinfo_exit_code"] = code
            if stderr.strip():
                result["warnings"].append("pdfinfo diagnostic: " + stderr.strip())
            if code != 0:
                pdf["inspection_error"] = stderr.strip() or "pdfinfo could not read the PDF"
                result["routing"] = {
                    "recommended_processor": None,
                    "needs_ocr_review": False,
                    "reasons": ["PDF is unreadable, encrypted, or malformed."],
                }
            else:
                fields = {}
                for line in stdout.splitlines():
                    if ":" in line:
                        key, value = line.split(":", 1)
                        fields[key.strip().lower()] = value.strip()
                pdf["pages"] = int(fields["pages"]) if fields.get("pages", "").isdigit() else None
                encrypted = fields.get("encrypted", "").lower().startswith("yes")
                pdf["encrypted"] = encrypted
                if encrypted:
                    result["routing"] = {
                        "recommended_processor": None,
                        "needs_ocr_review": False,
                        "reasons": ["PDF is encrypted; request authorized access rather than attempting a bypass."],
                    }
                elif shutil.which("pdftotext"):
                    code, text, error = command_output(["pdftotext", "-f", "1", "-l", "3", str(source), "-"])
                    text_length = len(text.strip()) if code == 0 else 0
                    pdf["text_probe_pages"] = min(3, pdf["pages"] or 3)
                    pdf["text_probe_characters"] = text_length
                    pdf["text_probe_exit_code"] = code
                    if code != 0:
                        result["warnings"].append(error.strip() or "pdftotext probe failed.")
                    elif text_length < 40:
                        result["routing"] = {
                            "recommended_processor": "ocrmypdf",
                            "needs_ocr_review": True,
                            "reasons": ["The first pages contain too little extractable text."],
                        }
                else:
                    result["warnings"].append("pdftotext is unavailable; text-layer quality was not inspected.")

    serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(serialized, encoding="utf-8")
    else:
        sys.stdout.write(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
