"""Backup/restore of the AnythingLLM runtime state (LanceDB index + app data).

This targets the named Docker volume backing the `anythingllm` service
(`STORAGE_DIR=/app/server/storage`, volume name `<project>_anythingllm`, e.g.
`moogle_anythingllm` with the default `COMPOSE_PROJECT_NAME`). The snapshot is
explicitly a rebuildable convenience artifact, not the source of truth -- the
processed Markdown corpus is (see `knowledge.py`).

Backup/restore run a short-lived helper container that mounts the named
volume read (backup) or read-write (restore) alongside a host directory, and
tar+zstd the contents. This avoids requiring the `anythingllm` container
itself to be stopped for backup, but restore does require the stack to be
down so the volume isn't being written to concurrently.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

DEFAULT_VOLUME = "moogle_anythingllm"
DEFAULT_HELPER_IMAGE = "alpine:3.20"
# LanceDB volumes are dominated by float32 vector data, which is close to
# incompressible and large (tens of GB is common) -- a high zstd level buys
# almost no size reduction for a huge time cost. Level 3 (multithreaded) is a
# much better default; pass --level for a different size/speed tradeoff.
DEFAULT_COMPRESSION_LEVEL = 3


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def backup_runtime(
    *,
    output: Path,
    volume: str = DEFAULT_VOLUME,
    helper_image: str = DEFAULT_HELPER_IMAGE,
    level: int = DEFAULT_COMPRESSION_LEVEL,
    exclude: list[str] | None = None,
) -> Path:
    """Tar+zstd the contents of a named Docker volume to `output`.

    `exclude` is a list of top-level paths (relative to the volume root, e.g.
    ["vector-cache"]) to omit from the archive -- useful for AnythingLLM's
    `vector-cache/` dir, which only speeds up re-embedding already-processed
    documents and is not required to query the existing LanceDB table.
    """
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    exclude_flags = " ".join(f"--exclude=./{name}" for name in (exclude or []))
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{volume}:/source:ro",
        "-v", f"{output.parent}:/backup",
        helper_image,
        "sh", "-c",
        f"apk add --no-cache zstd tar >/dev/null 2>&1 && "
        f"tar -C /source {exclude_flags} -cf - . | zstd -{level} -T0 -o /backup/{output.name}",
    ]
    _run(cmd)
    print(f"Backed up volume '{volume}' to {output}")
    return output


def restore_runtime(
    *,
    input_path: Path,
    volume: str = DEFAULT_VOLUME,
    helper_image: str = DEFAULT_HELPER_IMAGE,
    wipe_existing: bool = True,
) -> None:
    """Restore a backup produced by `backup_runtime` into a named Docker volume.

    The target volume is expected to be idle (stack stopped, e.g. `moogle down`)
    to avoid restoring into a volume that AnythingLLM is actively writing to.
    """
    input_path = Path(input_path).resolve()
    if not input_path.exists():
        raise RuntimeError(f"Backup archive not found: {input_path}")

    wipe = "rm -rf /target/* /target/..?* /target/.[!.]* 2>/dev/null; " if wipe_existing else ""
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{volume}:/target",
        "-v", f"{input_path.parent}:/backup:ro",
        helper_image,
        "sh", "-c",
        f"apk add --no-cache zstd tar >/dev/null 2>&1 && "
        f"{wipe}"
        f"zstd -d -c /backup/{input_path.name} | tar -C /target -xf -",
    ]
    _run(cmd)
    print(f"Restored volume '{volume}' from {input_path}")
