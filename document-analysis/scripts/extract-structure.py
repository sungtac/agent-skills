#!/usr/bin/env python3
"""Extract page-level PDF structure with PyMuPDF without modifying the PDF."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
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
    # Bind this extraction to the source attested in the manifest (same guard as
    # extract-pdf.sh): refuse to extract from a document whose bytes differ from
    # the recorded source_sha256, so a substituted file cannot inherit another
    # document's provenance and still pass verify-result.py.
    try:
        recorded = json.loads((analysis_dir / "manifest.json").read_text(encoding="utf-8")).get("source_sha256")
    except (OSError, ValueError) as error:
        print(f"Cannot read manifest for provenance check: {error}", file=sys.stderr)
        return 2
    if not recorded:
        print("Manifest has no recorded source_sha256; cannot verify provenance.", file=sys.stderr)
        return 2
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    if digest.hexdigest() != recorded:
        print("Source does not match the manifest's recorded source_sha256; refusing to extract a different document than the one analysed.", file=sys.stderr)
        return 2
    if output.exists():
        print(f"Refusing to overwrite existing artifact: {output}", file=sys.stderr)
        return 1
    try:
        import pymupdf
    except ImportError:
        print("PyMuPDF is required; install it in the document-analysis virtual environment.", file=sys.stderr)
        return 127

    with pymupdf.open(source) as document:
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
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=analysis_dir, delete=False) as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
                temporary = Path(stream.name)
            os.replace(temporary, output)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        version = getattr(pymupdf, "__version__", "unknown")
        script_dir = Path(__file__).resolve().parent
        try:
            status = os.spawnv(
                os.P_WAIT,
                sys.executable,
                [sys.executable, str(script_dir / "record-manifest.py"), str(analysis_dir), "--processor", "pymupdf", "--version", version, "--artifact", str(output)],
            )
        except OSError as error:
            print(f"Could not record PyMuPDF artifact: {error}", file=sys.stderr)
            status = 1
        if status != 0:
            try:
                output.unlink()
            except OSError as error:
                print(f"Could not remove unrecorded artifact: {error}", file=sys.stderr)
            return status
        return status


if __name__ == "__main__":
    raise SystemExit(main())
