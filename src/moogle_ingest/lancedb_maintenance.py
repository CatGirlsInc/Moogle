"""LanceDB compaction/vacuum for the AnythingLLM runtime volume.

Uses LanceDB's own supported maintenance API (`Table#optimize()`, "modeled
after VACUUM in PostgreSQL": compaction of small fragments + pruning of old
table versions + index optimization) instead of touching `_versions`/data
files directly. See `lancedb_compact.js`.

The AnythingLLM container is stopped before running the maintenance
container (a throwaway container from the *same* image, so it reuses the
exact bundled LanceDB client version) so nothing is concurrently writing to
the table, then restarted afterward -- this function always restarts the
container, even on failure, so the stack isn't left down.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

DEFAULT_CONTAINER = "moogle-anythingllm"
DEFAULT_VOLUME = "moogle_anythingllm"
DEFAULT_IMAGE = "mintplexlabs/anythingllm:1.16.0"
DEFAULT_STORAGE_DIR = "/app/server/storage/lancedb"
DEFAULT_NAMESPACE = "bg-wiki"

_COMPACT_SCRIPT_PATH = Path(__file__).parent / "lancedb_compact.js"


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kwargs)


def detect_container_image(container: str) -> str | None:
    """Best-effort lookup of the image backing a running container, before stopping it."""
    result = subprocess.run(
        ["docker", "inspect", container, "--format", "{{.Config.Image}}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def get_storage_size_bytes(*, container: str, storage_dir: str = "/app/server/storage") -> int | None:
    """Read the current on-disk size of AnythingLLM's storage dir via `docker exec du`. Requires the container to be running."""
    result = subprocess.run(
        ["docker", "exec", container, "du", "-sb", storage_dir],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    return int(result.stdout.split()[0])


def compact_lancedb_table(
    *,
    container: str = DEFAULT_CONTAINER,
    volume: str = DEFAULT_VOLUME,
    image: str | None = None,
    storage_dir: str = DEFAULT_STORAGE_DIR,
    namespace: str = DEFAULT_NAMESPACE,
    cleanup_older_than_days: int = 0,
) -> dict:
    """Stop `container`, run LanceDB's `optimize()` on `namespace`'s table, then restart `container`.

    Returns the JSON stats produced by lancedb_compact.js (row counts,
    versions, and index names before/after, plus LanceDB's own
    compaction/prune stats).
    """
    resolved_image = image or detect_container_image(container) or DEFAULT_IMAGE

    was_running = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", container],
        capture_output=True, text=True,
    ).stdout.strip() == "true"

    if was_running:
        print(f"Stopping {container} before LanceDB maintenance...")
        _run(["docker", "stop", container])

    try:
        request = json.dumps({
            "storageDir": storage_dir,
            "namespace": namespace,
            "cleanupOlderThanDays": cleanup_older_than_days,
        })
        result = subprocess.run(
            [
                "docker", "run", "--rm",
                "-v", f"{volume}:/app/server/storage",
                "-v", f"{_COMPACT_SCRIPT_PATH.parent}:/moogle-scripts:ro",
                "-e", f"LANCEDB_COMPACT_REQUEST={request}",
                "--entrypoint", "node",
                resolved_image,
                "/moogle-scripts/lancedb_compact.js",
            ],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"LanceDB compaction failed: {result.stderr.strip()}")
        return json.loads(result.stdout)
    finally:
        if was_running:
            print(f"Restarting {container}...")
            _run(["docker", "start", container])
