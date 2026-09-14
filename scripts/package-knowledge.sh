#!/usr/bin/env bash
# Package data/processed/markdown into a versioned tar.zst archive + manifest.
# Thin wrapper around `moogle knowledge package`; see manifests/README.md.
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <knowledge_version> [extra moogle knowledge package args...]" >&2
  echo "example: $0 bgwiki-20250225.1 --source-dump-checksum <sha256>" >&2
  exit 2
fi

KNOWLEDGE_VERSION="$1"
shift

cd "$(dirname "${BASH_SOURCE[0]}")/.."
uv run moogle knowledge package "$KNOWLEDGE_VERSION" --output dist "$@"
