from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "scripts" / "inspect-document.py"
ORIGINAL = "ORIGINAL-IMPORTANT-CONTENT\n"


def load_script():
    spec = importlib.util.spec_from_file_location("inspect_document_under_test", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load inspect-document.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InspectDocumentOutputGuardTests(unittest.TestCase):
    def run_with_argv(self, argv: list[str]) -> int:
        module = load_script()
        with patch.object(sys, "argv", [str(SCRIPT), *argv]):
            return module.main()

    def test_refuses_to_overwrite_source_via_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "doc.txt"
            source.write_text(ORIGINAL, encoding="utf-8")
            status = self.run_with_argv([str(source), "--output", str(source)])
            self.assertEqual(2, status)
            # The source document must be left exactly as it was.
            self.assertEqual(ORIGINAL, source.read_text(encoding="utf-8"))

    def test_refuses_when_output_symlinks_back_to_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "doc.txt"
            source.write_text(ORIGINAL, encoding="utf-8")
            link = Path(tmp) / "link.txt"
            link.symlink_to(source)
            status = self.run_with_argv([str(source), "--output", str(link)])
            self.assertEqual(2, status)
            self.assertEqual(ORIGINAL, source.read_text(encoding="utf-8"))

    def test_writes_to_a_distinct_output_and_preserves_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "doc.txt"
            source.write_text(ORIGINAL, encoding="utf-8")
            output = Path(tmp) / "report.json"
            status = self.run_with_argv([str(source), "--output", str(output)])
            self.assertEqual(0, status)
            self.assertTrue(output.exists())
            self.assertIn('"schema_version"', output.read_text(encoding="utf-8"))
            self.assertEqual(ORIGINAL, source.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
