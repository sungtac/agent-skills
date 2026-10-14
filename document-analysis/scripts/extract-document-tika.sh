#!/usr/bin/env bash
set -euo pipefail

[[ $# -eq 2 ]] || { echo "Usage: $0 <source> <analysis-dir>" >&2; exit 64; }
source_path="$1"
analysis_dir="$2"
[[ -f "$source_path" ]] || { echo "Source does not exist: $source_path" >&2; exit 2; }
[[ -f "$analysis_dir/manifest.json" ]] || { echo "Analysis directory has no manifest: $analysis_dir" >&2; exit 2; }
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
