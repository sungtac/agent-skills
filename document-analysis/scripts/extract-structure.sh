#!/usr/bin/env bash
set -euo pipefail

data_root="${DOCUMENT_ANALYSIS_DATA_ROOT:-$HOME/.local/share/document-analysis}"
python_bin="${DOCUMENT_ANALYSIS_PYTHON:-$data_root/venv/bin/python}"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
[[ -x "$python_bin" ]] || { echo "Document-analysis Python is unavailable: $python_bin" >&2; exit 127; }
[[ $# -eq 2 ]] || { echo "Usage: $0 <source.pdf> <analysis-dir>" >&2; exit 64; }
diagnostic_log="$2/pymupdf-diagnostics.log"
[[ ! -e "$diagnostic_log" ]] || { echo "Refusing to overwrite diagnostics log: $diagnostic_log" >&2; exit 1; }
if ! "$python_bin" "$script_dir/extract-structure.py" "$@" 2>"$diagnostic_log"; then
  cat "$diagnostic_log" >&2
  echo "PyMuPDF extraction failed; diagnostics retained at: $diagnostic_log" >&2
  exit 1
fi
if [[ -s "$diagnostic_log" ]]; then
  cat "$diagnostic_log" >&2
  "$script_dir/record-manifest.py" "$2" --processor pymupdf-diagnostics --version "$("$python_bin" -c 'import pymupdf; print(pymupdf.__version__)')" --artifact "$diagnostic_log"
else
  rm -f -- "$diagnostic_log"
fi
