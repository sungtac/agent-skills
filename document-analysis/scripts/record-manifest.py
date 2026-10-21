#!/usr/bin/env python3
"""Append a processor record and artifact path to an analysis manifest."""

from __future__ import annotations

import argparse
import json
import sys
import os
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("analysis_dir", type=Path)
    parser.add_argument("--processor", required=True)
    parser.add_argument("--version", default="unknown")
    parser.add_argument("--artifact", action="append", default=[])
    parser.add_argument("--warning", action="append", default=[])
    arguments = parser.parse_args()

    analysis_dir = arguments.analysis_dir.expanduser().resolve()
    manifest_path = analysis_dir / "manifest.json"
    if not manifest_path.is_file():
        print(f"Missing manifest: {manifest_path}", file=sys.stderr)
        return 2
    lock_stream = None
    try:
        lock_stream = manifest_path.open("r+", encoding="utf-8")
        if os.name == "nt":
            import msvcrt

            lock_stream.seek(0)
            msvcrt.locking(lock_stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
        lock_stream.seek(0)
        with lock_stream:
            stream = lock_stream
            manifest = json.load(stream)
            record = {
                "name": arguments.processor,
                "version": arguments.version,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
            processors = manifest.setdefault("processors", [])
            if not any(item.get("name") == record["name"] and item.get("version") == record["version"] for item in processors):
                processors.append(record)
            artifacts = manifest.setdefault("artifacts", [])
            warnings = manifest.setdefault("warnings", [])
            for warning in arguments.warning:
                if warning not in warnings:
                    warnings.append(warning)
            for artifact in arguments.artifact:
                candidate = Path(artifact)
                if not candidate.is_absolute():
                    # The extract scripts pass "<analysis-dir>/<name>", which is
                    # relative to the working directory when analysis-dir is.
                    from_cwd = candidate.resolve()
                    if not (from_cwd.is_file() and from_cwd.is_relative_to(analysis_dir)):
                        candidate = analysis_dir / candidate
                candidate = candidate.resolve()
                try:
                    relative = candidate.relative_to(analysis_dir)
                except ValueError:
                    print(f"Artifact must be inside analysis directory: {candidate}", file=sys.stderr)
                    return 2
                if not candidate.is_file():
                    print(f"Artifact does not exist: {candidate}", file=sys.stderr)
                    return 2
                value = str(relative)
                if value not in artifacts:
                    artifacts.append(value)
            stream.seek(0)
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.truncate()
            stream.flush()
    except (OSError, json.JSONDecodeError) as error:
        print(f"Could not update manifest: {error}", file=sys.stderr)
        return 1
    finally:
        if lock_stream is not None and not lock_stream.closed:
            try:
                if os.name == "nt":
                    import msvcrt

                    lock_stream.seek(0)
                    msvcrt.locking(lock_stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
