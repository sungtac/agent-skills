#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 <source.pdf> <analysis-dir> [--language kor+eng]" >&2
  exit 64
}

[[ $# -ge 2 && $# -le 4 ]] || usage
source_path="$1"
analysis_dir="$2"
language="kor+eng"
if [[ $# -gt 2 ]]; then
  [[ "$3" == "--language" && $# -eq 4 ]] || usage
  language="$4"
fi
[[ -f "$source_path" ]] || { echo "Source PDF does not exist: $source_path" >&2; exit 2; }
[[ -f "$analysis_dir/manifest.json" ]] || { echo "Analysis directory has no manifest: $analysis_dir" >&2; exit 2; }
command -v ocrmypdf >/dev/null 2>&1 || { echo "ocrmypdf is required." >&2; exit 127; }
command -v pdftotext >/dev/null 2>&1 || { echo "pdftotext is required after OCR." >&2; exit 127; }

output_pdf="$analysis_dir/ocr.pdf"
output_text="$analysis_dir/extracted.txt"
ocr_log="$analysis_dir/ocr-run.log"
[[ ! -e "$output_pdf" && ! -e "$output_text" && ! -e "$ocr_log" ]] || { echo "Refusing to overwrite existing OCR artifacts." >&2; exit 1; }
temporary_dir="$(mktemp -d "${TMPDIR:-/tmp}/document-analysis-ocr.XXXXXX")"
cleanup() { rm -rf "$temporary_dir"; }
trap cleanup EXIT

if ! TMPDIR="$temporary_dir" ocrmypdf --skip-text --deskew --rotate-pages -l "$language" "$source_path" "$output_pdf" >"$ocr_log" 2>&1; then
  cat "$ocr_log" >&2
  echo "OCR failed; diagnostics retained at: $ocr_log" >&2
  exit 1
fi
cat "$ocr_log"
[[ -s "$output_pdf" ]] || { echo "OCR did not create a PDF." >&2; exit 1; }
pdftotext "$output_pdf" "$output_text"
[[ -s "$output_text" ]] || { echo "OCR PDF produced no extractable text." >&2; exit 1; }
version="$(ocrmypdf --version 2>&1 | head -n 1 || true)"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
"$script_dir/record-manifest.py" "$analysis_dir" --processor ocrmypdf --version "$version" --artifact "$output_pdf" --artifact "$output_text" --artifact "$ocr_log"
printf '%s\n%s\n' "$output_pdf" "$output_text"
