#!/usr/bin/env python3
"""Extract page-level PDF structure with PyMuPDF without modifying the PDF."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("analysis_dir", type=Path)
    arguments = parser.parse_args()
    source = arguments.source.expanduser().resolve()
    analysis_dir = arguments.analysis_dir.expanduser().resolve()
    output = analysis_dir / "structured.json"
    if not source.is_file() or source.suffix.lower() != ".pdf":
        print(f"Not a PDF file: {source}", file=sys.stderr)
        return 2
    if not (analysis_dir / "manifest.json").is_file():
        print(f"Analysis directory has no manifest: {analysis_dir}", file=sys.stderr)
        return 2
    if output.exists():
        print(f"Refusing to overwrite existing artifact: {output}", file=sys.stderr)
        return 1
    try:
        import pymupdf
    except ImportError:
        print("PyMuPDF is required; install it in the document-analysis virtual environment.", file=sys.stderr)
        return 127

    document = pymupdf.open(source)
    pages = []
    for number, page in enumerate(document, start=1):
        blocks = []
        for block in page.get_text("blocks"):
            x0, y0, x1, y1, text, block_no, block_type = block
            if block_type == 0:
                blocks.append({"bbox": [x0, y0, x1, y1], "text": text, "block_number": block_no})
        tables = []
        if hasattr(page, "find_tables"):
            try:
                found = page.find_tables()
                for table in found.tables:
                    tables.append({"bbox": list(table.bbox), "rows": table.extract()})
            except Exception as error:  # Table detection is optional and version-dependent.
                tables.append({"error": str(error)})
        pages.append(
            {
                "page": number,
                "size": [page.rect.width, page.rect.height],
                "text_blocks": blocks,
                "embedded_image_count": len(page.get_images(full=True)),
                "tables": tables,
            }
        )
    payload = {"schema_version": 1, "source": str(source), "page_count": len(document), "pages": pages}
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    version = getattr(pymupdf, "__version__", "unknown")
    script_dir = Path(__file__).resolve().parent
    status = os.spawnv(
        os.P_WAIT,
        sys.executable,
        [sys.executable, str(script_dir / "record-manifest.py"), str(analysis_dir), "--processor", "pymupdf", "--version", version, "--artifact", str(output)],
    )
    return status


if __name__ == "__main__":
    raise SystemExit(main())
