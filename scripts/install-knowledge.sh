#!/usr/bin/env bash
# Install (download/verify/extract) a released knowledge version into data/processed/markdown.
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <knowledge_version> [extra moogle knowledge install args...]" >&2
  echo "example: $0 bgwiki-20250225.1" >&2
  exit 2
fi

KNOWLEDGE_VERSION="$1"
shift

cd "$(dirname "${BASH_SOURCE[0]}")/.."
uv run moogle knowledge install "$KNOWLEDGE_VERSION" "$@"
