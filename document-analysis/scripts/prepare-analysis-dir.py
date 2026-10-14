#!/usr/bin/env python3
"""Create a non-overwriting analysis directory beside a source document."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--parent", type=Path, help="Directory that will contain the analysis directory")
    arguments = parser.parse_args()
    source = arguments.source.expanduser().resolve()
    if not source.is_file():
        print(f"Not a readable file: {source}", file=sys.stderr)
        return 2

    parent = (arguments.parent or source.parent).expanduser().resolve()
    if not parent.is_dir():
        print(f"Output parent does not exist: {parent}", file=sys.stderr)
        return 2
    base = parent / f"{source.stem}.analysis"
    suffix = datetime.now().strftime("%Y%m%d-%H%M%S")
    for sequence in range(0, 1000):
        if sequence == 0:
            target = base
        elif sequence == 1:
            target = parent / f"{source.stem}.analysis-{suffix}"
        else:
            target = parent / f"{source.stem}.analysis-{suffix}-{sequence}"
        try:
            target.mkdir()
            break
        except FileExistsError:
            continue
        except OSError as error:
            print(f"Could not create analysis directory in {parent}: {error}", file=sys.stderr)
            return 1
    else:
        print(f"Could not allocate a unique analysis directory in {parent}", file=sys.stderr)
        return 1

    page_count = None
    inspection_warnings = []
    if source.suffix.lower() == ".pdf":
        try:
            info = subprocess.run(["pdfinfo", str(source)], capture_output=True, text=True, timeout=45, check=False)
            if info.returncode == 0:
                if info.stderr.strip():
                    inspection_warnings.append(info.stderr.strip())
                for line in info.stdout.splitlines():
                    if line.startswith("Pages:"):
                        page_count = int(line.split(":", 1)[1].strip())
                        break
            elif info.stderr.strip():
                inspection_warnings.append(info.stderr.strip())
        except (OSError, subprocess.TimeoutExpired):
            pass

    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "source_sha256": digest(source),
        "page_count": page_count,
        "warnings": inspection_warnings,
        "output_directory": str(target),
        "processors": [],
        "artifacts": [],
    }
    (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
