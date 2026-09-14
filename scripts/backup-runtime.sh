#!/usr/bin/env bash
# Backup the AnythingLLM Docker volume (LanceDB index + app state) to a tar.zst file.
# This is a convenience/cache snapshot, not the source of truth -- see data/README.md.
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <output.tar.zst> [--volume <name>]" >&2
  echo "example: $0 backups/anythingllm-bgwiki-20250225.1.tar.zst" >&2
  exit 2
fi

cd "$(dirname "${BASH_SOURCE[0]}")/.."
uv run moogle runtime backup "$@"
