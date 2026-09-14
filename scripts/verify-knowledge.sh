#!/usr/bin/env bash
# Verify a downloaded/local knowledge archive against its manifest checksum.
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <archive.tar.zst> <manifest.json>" >&2
  exit 2
fi

cd "$(dirname "${BASH_SOURCE[0]}")/.."
uv run moogle knowledge verify "$1" "$2"
