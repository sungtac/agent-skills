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
    # Recursive: the temp dir may also hold the .asc signature, the KEYS file
    # and a throwaway gpg homedir (with sockets gpg leaves behind), which a
    # plain rmdir would not clear.
    rm -rf -- "$temporary_dir"
  }
  trap cleanup EXIT
  archive="$temporary_dir/tika.zip"
  checksum="$temporary_dir/tika.zip.sha512"
  curl --fail --location --proto '=https' --tlsv1.2 "$tika_url" --output "$archive"
  curl --fail --location --proto '=https' --tlsv1.2 "$tika_url.sha512" --output "$checksum"
  expected="$(grep -Eo '[[:xdigit:]]{128}' "$checksum" | head -n 1 || true)"
  actual="$(sha512sum "$archive" | awk '{print $1}')"
  [[ -n "$expected" && "$expected" == "$actual" ]] || { echo "Apache Tika SHA-512 verification failed." >&2; exit 1; }
  # Supply-chain hardening (BEST EFFORT): the .sha512 above is fetched from the
  # same Apache host as the archive, so on its own it only detects transfer
  # corruption, not a compromised mirror serving a matching checksum for a
  # tampered archive. Apache also publishes a detached PGP signature (.asc) and
  # a KEYS file of release-signing public keys. When gpg is present AND the
  # signature and KEYS can be fetched and imported, verify the signature as a
  # stronger cryptographic integrity check. On minimal hosts without gpg, or
  # when KEYS/signature cannot be fetched or imported, we deliberately fall back
  # to the sha512 result and warn instead of hard-failing, so the installer keeps
  # working offline-of-keyservers and on bare systems. A genuinely BAD signature
  # (gpg usable, KEYS imported) is treated as tampering and aborts the install.
  if command -v gpg >/dev/null 2>&1; then
    signature="$temporary_dir/tika.zip.asc"
    gnupg_home="$temporary_dir/gnupg"
    mkdir -p "$gnupg_home"
    chmod 700 "$gnupg_home"
    if curl --fail --location --proto '=https' --tlsv1.2 "$tika_url.asc" --output "$signature" \
      && curl --fail --location --proto '=https' --tlsv1.2 "https://downloads.apache.org/tika/KEYS" --output "$temporary_dir/KEYS" \
      && gpg --homedir "$gnupg_home" --batch --import "$temporary_dir/KEYS" >/dev/null 2>&1; then
      if gpg --homedir "$gnupg_home" --batch --verify "$signature" "$archive" >/dev/null 2>&1; then
        echo "Apache Tika PGP signature verified against imported Apache KEYS."
      else
        echo "Apache Tika PGP signature verification FAILED; the archive may be tampered with. Aborting." >&2
        exit 1
      fi
    else
      echo "Warning: could not fetch/import the Apache signature or KEYS; skipped PGP verification and relied on SHA-512 only." >&2
    fi
  else
    echo "Warning: gpg not available; skipped PGP signature verification and relied on SHA-512 only (fetched from the same host as the archive)." >&2
  fi
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
