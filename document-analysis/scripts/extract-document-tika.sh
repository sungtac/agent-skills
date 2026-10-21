#!/usr/bin/env bash
set -euo pipefail

[[ $# -eq 2 ]] || { echo "Usage: $0 <source> <analysis-dir>" >&2; exit 64; }
source_path="$1"
analysis_dir="$2"
[[ -f "$source_path" ]] || { echo "Source does not exist: $source_path" >&2; exit 2; }
[[ -f "$analysis_dir/manifest.json" ]] || { echo "Analysis directory has no manifest: $analysis_dir" >&2; exit 2; }

# Bind this extraction to the source attested in the manifest (same guard as
# extract-pdf.sh): refuse to extract from a document whose bytes differ from
# the recorded source_sha256, so a substituted file cannot inherit another
# document's provenance and still pass verify-result.py.
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

command -v java >/dev/null 2>&1 || { echo "Java is required for Apache Tika." >&2; exit 127; }

data_root="${DOCUMENT_ANALYSIS_DATA_ROOT:-$HOME/.local/share/document-analysis}"
tika_root="${DOCUMENT_ANALYSIS_TIKA_ROOT:-$data_root/tika/current}"
tika_jar="$(find -L "$tika_root" -maxdepth 2 -type f -name 'tika-app*.jar' -print -quit 2>/dev/null || true)"
[[ -n "$tika_jar" ]] || { echo "Apache Tika launcher not found under: $tika_root" >&2; exit 127; }

output="$analysis_dir/extracted.txt"
errors="$analysis_dir/tika.stderr.log"
[[ ! -e "$output" && ! -e "$errors" ]] || { echo "Refusing to overwrite existing Tika artifacts." >&2; exit 1; }
if ! java -jar "$tika_jar" --text "$source_path" >"$output" 2>"$errors"; then
  rm -f "$output"
  echo "Apache Tika extraction failed; diagnostics retained at: $errors" >&2
  exit 1
fi
[[ -s "$output" ]] || { echo "Apache Tika created an empty extraction." >&2; exit 1; }
if [[ ! -s "$errors" ]]; then rm -f "$errors"; fi
version="$(basename "$tika_jar")"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
"$script_dir/record-manifest.py" "$analysis_dir" --processor apache-tika --version "$version" --artifact "$output"
[[ ! -e "$errors" ]] || "$script_dir/record-manifest.py" "$analysis_dir" --processor apache-tika --version "$version" --artifact "$errors"
printf '%s\n' "$output"
