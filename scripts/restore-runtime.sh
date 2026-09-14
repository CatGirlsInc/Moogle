#!/usr/bin/env bash
# Restore a prebuilt AnythingLLM runtime snapshot into the Docker volume.
# Run `moogle down` first so the volume isn't being written to concurrently.
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <input.tar.zst> [--volume <name>]" >&2
  echo "example: $0 backups/anythingllm-bgwiki-20250225.1.tar.zst" >&2
  exit 2
fi

cd "$(dirname "${BASH_SOURCE[0]}")/.."
uv run moogle runtime restore "$@"
