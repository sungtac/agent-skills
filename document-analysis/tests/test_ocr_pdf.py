from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "ocr-pdf.sh"


class OcrPdfTests(unittest.TestCase):
    def test_failed_text_extraction_after_ocr_leaves_no_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            analysis = root / "analysis"
            analysis.mkdir()
            payload = b"document-A bytes"
            (analysis / "manifest.json").write_text(json.dumps({
                "schema_version": 1, "source": "A.pdf", "artifacts": [],
                "source_sha256": hashlib.sha256(payload).hexdigest()}), encoding="utf-8")
            source = root / "A.pdf"
            source.write_bytes(payload)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            ocrmypdf = fake_bin / "ocrmypdf"
            ocrmypdf.write_text('#!/bin/bash\ncp "${@: -2:1}" "${@: -1}"\n')
            pdftotext = fake_bin / "pdftotext"
            # Fails like a damaged PDF, after writing partial output.
            pdftotext.write_text('#!/bin/sh\necho "Syntax Error: broken xref" >&2\necho partial > "$2"\nexit 1\n')
            for fake in (ocrmypdf, pdftotext):
                fake.chmod(0o755)
            result = subprocess.run(
                ["bash", str(SCRIPT), str(source), str(analysis)],
                capture_output=True,
                text=True,
                env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
            )
            self.assertEqual(1, result.returncode)
            self.assertIn("broken xref", result.stderr)
            self.assertFalse((analysis / "extracted.txt").exists())


if __name__ == "__main__":
    unittest.main()
