#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 <source.pdf> <analysis-dir> [--layout]" >&2
  exit 64
}

[[ $# -ge 2 && $# -le 3 ]] || usage
source_path="$1"
analysis_dir="$2"
layout=false
if [[ $# -eq 3 ]]; then
  [[ "$3" == "--layout" ]] || usage
  layout=true
fi

[[ -f "$source_path" ]] || { echo "Source PDF does not exist: $source_path" >&2; exit 2; }
[[ -f "$analysis_dir/manifest.json" ]] || { echo "Analysis directory has no manifest: $analysis_dir" >&2; exit 2; }

# Bind this extraction to the source attested in the manifest. Without this
# check extract-pdf.sh would happily run pdftotext over a different document
# than the one prepare-analysis-dir.py recorded, and because verify-result.py
# only re-checks the manifest's own recorded source against itself, the
# substituted extraction would still pass strict verification.
python3 -I - "$analysis_dir/manifest.json" "$source_path" <<'PROVENANCE'
import hashlib, json, sys

manifest_path, source_path = sys.argv[1], sys.argv[2]


def fail(message):
    print(message, file=sys.stderr)
    raise SystemExit(2)


try:
    recorded = json.load(open(manifest_path, encoding="utf-8")).get("source_sha256")
except (OSError, ValueError) as error:
    fail(f"Cannot read manifest for provenance check: {error}")
if not recorded:
    fail("Manifest has no recorded source_sha256; cannot verify provenance.")
digest = hashlib.sha256()
with open(source_path, "rb") as handle:
    for chunk in iter(lambda: handle.read(1 << 20), b""):
        digest.update(chunk)
if digest.hexdigest() != recorded:
    fail("Source does not match the manifest's recorded source_sha256; "
         "refusing to extract from a different document than the one analysed.")
PROVENANCE

command -v pdftotext >/dev/null 2>&1 || { echo "pdftotext is required; install poppler-utils." >&2; exit 127; }

output="$analysis_dir/extracted.txt"
if [[ "$layout" == true ]]; then
  output="$analysis_dir/extracted-layout.txt"
fi
[[ ! -e "$output" ]] || { echo "Refusing to overwrite existing artifact: $output" >&2; exit 1; }
diagnostics_log="$analysis_dir/poppler-diagnostics.log"
[[ ! -e "$diagnostics_log" ]] || { echo "Refusing to overwrite existing artifact: $diagnostics_log" >&2; exit 1; }
diagnostics_temp="$(mktemp "${TMPDIR:-/tmp}/document-analysis-poppler-diagnostics.XXXXXX")"
trap 'rm -f -- "$diagnostics_temp"' EXIT
pdftotext_args=()
[[ "$layout" == true ]] && pdftotext_args=(-layout)
if ! pdftotext ${pdftotext_args[@]+"${pdftotext_args[@]}"} "$source_path" "$output" 2>"$diagnostics_temp"; then
  # Show why it failed and drop any partial output so a retry is not blocked.
  cat -- "$diagnostics_temp" >&2
  rm -f -- "$output"
  echo "Poppler extraction failed: $source_path" >&2
  exit 1
fi

[[ -s "$output" ]] || { echo "Poppler created an empty extraction: $output" >&2; exit 1; }
version="$(pdftotext -v 2>&1 | head -n 1 || true)"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
"$script_dir/record-manifest.py" "$analysis_dir" --processor poppler --version "$version" --artifact "$output"
if [[ -s "$diagnostics_temp" ]]; then
  mv -- "$diagnostics_temp" "$diagnostics_log"
  trap - EXIT
  warning_text="$(<"$diagnostics_log")"
  "$script_dir/record-manifest.py" "$analysis_dir" --processor poppler-diagnostics --version "$version" --artifact "$diagnostics_log" --warning "$warning_text"
fi
printf '%s\n' "$output"
