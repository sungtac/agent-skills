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
if [[ "$layout" == true ]]; then
  pdftotext -layout "$source_path" "$output" 2>"$diagnostics_temp"
else
  pdftotext "$source_path" "$output" 2>"$diagnostics_temp"
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
