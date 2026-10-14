#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  echo "Installs Linux dependencies for document-analysis. Set DOCUMENT_ANALYSIS_TIKA_VERSION to change the Tika release."
  exit 0
fi

command -v apt-get >/dev/null 2>&1 || { echo "This setup script currently supports apt-based Linux distributions only." >&2; exit 2; }
command -v sudo >/dev/null 2>&1 || { echo "sudo is required to install system packages." >&2; exit 2; }

data_root="${DOCUMENT_ANALYSIS_DATA_ROOT:-$HOME/.local/share/document-analysis}"
tika_version="${DOCUMENT_ANALYSIS_TIKA_VERSION:-4.1.0}"
tika_base="$data_root/tika"
tika_destination="$tika_base/$tika_version"
tika_url="https://downloads.apache.org/tika/$tika_version/tika-app-$tika_version.zip"

sudo apt-get update
sudo apt-get install -y \
  poppler-utils tesseract-ocr tesseract-ocr-kor tesseract-ocr-eng ocrmypdf \
  python3-venv openjdk-17-jre-headless curl unzip

mkdir -p "$data_root" "$tika_base"
venv="$data_root/venv"
if [[ ! -x "$venv/bin/python" ]]; then
  python3 -m venv "$venv"
fi
"$venv/bin/python" -m pip install --upgrade pip
"$venv/bin/python" -m pip install --upgrade pymupdf

if [[ ! -d "$tika_destination" ]]; then
  temporary_dir="$(mktemp -d "${TMPDIR:-/tmp}/document-analysis-tika.XXXXXX")"
  cleanup() {
    rm -f -- "$archive" "$checksum"
    rmdir -- "$temporary_dir" 2>/dev/null || true
  }
  trap cleanup EXIT
  archive="$temporary_dir/tika.zip"
  checksum="$temporary_dir/tika.zip.sha512"
  curl --fail --location --proto '=https' --tlsv1.2 "$tika_url" --output "$archive"
  curl --fail --location --proto '=https' --tlsv1.2 "$tika_url.sha512" --output "$checksum"
  expected="$(grep -Eo '[[:xdigit:]]{128}' "$checksum" | head -n 1 || true)"
  actual="$(sha512sum "$archive" | awk '{print $1}')"
  [[ -n "$expected" && "$expected" == "$actual" ]] || { echo "Apache Tika SHA-512 verification failed." >&2; exit 1; }
  mkdir -p "$tika_destination"
  unzip -q "$archive" -d "$tika_destination"
  find "$tika_destination" -maxdepth 2 -type f -name "tika-app-$tika_version.jar" -print -quit | grep -q . || {
    echo "Apache Tika archive did not contain the expected launcher." >&2
    exit 1
  }
fi
current="$tika_base/current"
if [[ -e "$current" && ! -L "$current" ]]; then
  echo "Refusing to replace non-symlink Tika path: $current" >&2
  exit 1
fi
ln -sfn "$tika_destination" "$current"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
"$script_dir/health-check.sh" --strict
