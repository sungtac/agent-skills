#!/usr/bin/env bash
set -euo pipefail

strict=false
if [[ "${1:-}" == "--strict" ]]; then
  strict=true
elif [[ $# -gt 0 ]]; then
  echo "Usage: $0 [--strict]" >&2
  exit 64
fi

data_root="${DOCUMENT_ANALYSIS_DATA_ROOT:-$HOME/.local/share/document-analysis}"
python_bin="${DOCUMENT_ANALYSIS_PYTHON:-$data_root/venv/bin/python}"
tika_root="${DOCUMENT_ANALYSIS_TIKA_ROOT:-$data_root/tika/current}"
missing=0

report_command() {
  local label="$1" command="$2"
  if command -v "$command" >/dev/null 2>&1; then
    local version
    case "$command" in
      pdftotext|pdfinfo|pdftoppm) version="$("$command" -v 2>&1 | head -n 1 || true)" ;;
      *) version="$("$command" --version 2>&1 | head -n 1 || true)" ;;
    esac
    printf '%-18s OK      %s\n' "$label" "$version"
  else
    printf '%-18s MISSING\n' "$label"
    missing=1
  fi
}

echo "Document analysis health check"
echo "data root: $data_root"
report_command "pdftotext" pdftotext
report_command "pdfinfo" pdfinfo
report_command "pdftoppm" pdftoppm
report_command "tesseract" tesseract
report_command "ocrmypdf" ocrmypdf
if command -v java >/dev/null 2>&1; then
  java_version="$(java -version 2>&1 | head -n 1 || true)"
  java_major="$(grep -Eo '[0-9]+' <<<"$java_version" | head -n 1 || true)"
  if [[ -n "$java_major" && "$java_major" -ge 17 ]]; then
    printf '%-18s OK      %s\n' "java" "$java_version"
  else
    printf '%-18s INCOMPATIBLE (Java 17+ required) %s\n' "java" "$java_version"
    missing=1
  fi
else
  printf '%-18s MISSING\n' "java"
  missing=1
fi

if command -v tesseract >/dev/null 2>&1; then
  languages="$(tesseract --list-langs 2>/dev/null || true)"
  for language in kor eng; do
    if grep -qx "$language" <<<"$languages"; then
      printf '%-18s OK\n' "tesseract:$language"
    else
      printf '%-18s MISSING\n' "tesseract:$language"
      missing=1
    fi
  done
fi

if [[ -x "$python_bin" ]]; then
  if "$python_bin" -c 'import pymupdf; print(pymupdf.__version__)' >/dev/null 2>&1; then
    printf '%-18s OK      %s\n' "pymupdf" "$($python_bin -c 'import pymupdf; print(pymupdf.__version__)')"
  else
    printf '%-18s MISSING\n' "pymupdf"
    missing=1
  fi
else
  printf '%-18s MISSING (%s)\n' "analysis python" "$python_bin"
  missing=1
fi

if find -L "$tika_root" -maxdepth 2 -type f -name 'tika-app*.jar' -print -quit 2>/dev/null | grep -q .; then
  tika_jar="$(find -L "$tika_root" -maxdepth 2 -type f -name 'tika-app*.jar' -print -quit 2>/dev/null)"
  printf '%-18s OK      %s\n' "apache-tika" "$(basename "$tika_jar")"
else
  printf '%-18s MISSING (%s)\n' "apache-tika" "$tika_root"
  missing=1
fi

if [[ "$strict" == true && "$missing" -ne 0 ]]; then
  exit 1
fi
