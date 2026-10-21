from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "scripts" / "extract-structure.py"


class FakePage:
    rect = SimpleNamespace(width=100, height=200)

    def get_text(self, kind: str):
        self_kind = kind
        if self_kind != "blocks":
            raise AssertionError("unexpected text request")
        return [(0, 0, 10, 10, "text", 0, 0)]

    def get_images(self, full: bool):
        return []


class FakeDocument:
    def __iter__(self):
        return iter([FakePage()])

    def __len__(self):
        return 1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


def load_script():
    spec = importlib.util.spec_from_file_location("extract_structure_under_test", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load extract-structure.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExtractStructureTests(unittest.TestCase):
    def run_extraction(self, recorder_status: int) -> tuple[int, bool, str | None]:
        module = load_script()
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source.pdf"
            source.write_bytes(b"pdf")
            analysis = root / "analysis"
            analysis.mkdir()
            # Manifest must carry the source's sha256 so the provenance guard
            # (added to extract-structure.py) passes for the real source.
            (analysis / "manifest.json").write_text(
                json.dumps({"source_sha256": hashlib.sha256(b"pdf").hexdigest()}) + "\n",
                encoding="utf-8",
            )
            fake_pymupdf = SimpleNamespace(open=lambda _: FakeDocument(), __version__="test")
            with patch.dict(sys.modules, {"pymupdf": fake_pymupdf}), patch.object(module.os, "spawnv", return_value=recorder_status), patch.object(sys, "argv", [str(SCRIPT), str(source), str(analysis)]):
                status = module.main()
            output = analysis / "structured.json"
            if output.exists():
                return status, True, output.read_text(encoding="utf-8")
            return status, False, None

    def test_removes_artifact_when_manifest_recording_fails(self) -> None:
        status, exists, _ = self.run_extraction(1)
        self.assertEqual(1, status)
        self.assertFalse(exists)

    def test_keeps_artifact_when_manifest_recording_succeeds(self) -> None:
        status, exists, content = self.run_extraction(0)
        self.assertEqual(0, status)
        self.assertTrue(exists)
        self.assertIsNotNone(content)
        self.assertEqual(1, json.loads(content)["page_count"])


if __name__ == "__main__":
    unittest.main()
