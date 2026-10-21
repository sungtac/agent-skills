from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "extract-pdf.sh"
PROVENANCE_MESSAGE = "does not match the manifest"


def sha256_bytes(data: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(data)
    return digest.hexdigest()


def write_manifest(analysis_dir: Path, **fields: object) -> None:
    base = {"schema_version": 1, "source": "recorded.pdf", "artifacts": []}
    base.update(fields)
    (analysis_dir / "manifest.json").write_text(json.dumps(base) + "\n", encoding="utf-8")


def run_extract(source: Path, analysis_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), str(source), str(analysis_dir)],
        capture_output=True,
        text=True,
    )


class ExtractPdfProvenanceTests(unittest.TestCase):
    def test_rejects_source_that_does_not_match_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            analysis = root / "analysis"
            analysis.mkdir()
            # Manifest attests to document A, but we try to extract document B.
            write_manifest(analysis, source_sha256=sha256_bytes(b"document-A bytes"))
            substitute = root / "B.pdf"
            substitute.write_bytes(b"document-B bytes")
            result = run_extract(substitute, analysis)
            self.assertEqual(2, result.returncode)
            self.assertIn(PROVENANCE_MESSAGE, result.stderr)
            self.assertFalse((analysis / "extracted.txt").exists())

    def test_rejects_manifest_without_recorded_source_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            analysis = root / "analysis"
            analysis.mkdir()
            write_manifest(analysis)  # no source_sha256
            source = root / "A.pdf"
            source.write_bytes(b"document-A bytes")
            result = run_extract(source, analysis)
            self.assertEqual(2, result.returncode)
            self.assertIn("no recorded source_sha256", result.stderr)
            self.assertFalse((analysis / "extracted.txt").exists())

    def test_matching_source_passes_the_provenance_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            analysis = root / "analysis"
            analysis.mkdir()
            payload = b"document-A bytes"
            write_manifest(analysis, source_sha256=sha256_bytes(payload))
            source = root / "A.pdf"
            source.write_bytes(payload)
            result = run_extract(source, analysis)
            # The source matches the manifest, so the provenance guard must not
            # fire. (Extraction itself may still fail because this fixture is not
            # a real PDF; that is outside the provenance guard's scope.)
            self.assertNotIn(PROVENANCE_MESSAGE, result.stderr)


    def test_failed_pdftotext_reports_diagnostics_and_leaves_no_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            analysis = root / "analysis"
            analysis.mkdir()
            payload = b"document-A bytes"
            write_manifest(analysis, source_sha256=sha256_bytes(payload))
            source = root / "A.pdf"
            source.write_bytes(payload)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake = fake_bin / "pdftotext"
            # Fails like a damaged PDF, after writing partial output.
            fake.write_text('#!/bin/sh\necho "Syntax Error: broken xref" >&2\necho partial > "$2"\nexit 1\n')
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


    def test_relative_analysis_dir_records_the_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            analysis = root / "analysis"
            analysis.mkdir()
            payload = b"document-A bytes"
            write_manifest(analysis, source_sha256=sha256_bytes(payload))
            (root / "A.pdf").write_bytes(payload)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake = fake_bin / "pdftotext"
            fake.write_text('#!/bin/sh\n[ "$1" = -v ] && { echo "pdftotext version 0"; exit 0; }\necho text > "$2"\n')
            fake.chmod(0o755)
            result = subprocess.run(
                ["bash", str(SCRIPT), "A.pdf", "analysis"],
                capture_output=True,
                text=True,
                cwd=root,
                env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
            )
            self.assertEqual(0, result.returncode, result.stderr)
            manifest = json.loads((analysis / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(["extracted.txt"], manifest["artifacts"])


if __name__ == "__main__":
    unittest.main()
