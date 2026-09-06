"""Direct LanceDB retrieval, bypassing AnythingLLM's per-query LLM generation.

AnythingLLM's `mode=query` chat endpoint always performs a full LLM
generation on top of retrieval, even when only the retrieved chunks are
needed (see multi_query.py's fan-out step). Measured directly, that
generation -- not model loading or GPU contention -- is the dominant cost of
using it as a retrieval-only shim (see repo notes / experiment report).

This module talks to the *same* LanceDB index AnythingLLM already built
(same on-disk tables under its `storage/lancedb` directory, same
`mxbai-embed-large` vectors) directly, with no re-embedding and no new
database:

- query embeddings are generated with the exact same model/endpoint
  AnythingLLM itself uses (Ollama's OpenAI-compatible `/v1/embeddings`)
- the actual vector search runs *inside* the AnythingLLM container via
  `docker exec`, reusing the exact `@lancedb/lancedb` client and on-disk
  table AnythingLLM ships with (see lancedb_search.js) -- this avoids
  needing a Python LanceDB client, a host bind-mount of the volume, or any
  reimplementation of AnythingLLM's schema/scoring conventions
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import requests

DEFAULT_CONTAINER = "moogle-anythingllm"
DEFAULT_STORAGE_DIR = "/app/server/storage/lancedb"
DEFAULT_EMBEDDING_DIM = 1024
REQUIRED_TABLE_FIELDS = ("vector", "text", "title")

_SEARCH_SCRIPT_PATH = Path(__file__).parent / "lancedb_search.js"
_SEARCH_CONTAINER_PATH = "/tmp/moogle_lancedb_search.js"
_SCHEMA_CHECK_SCRIPT_PATH = Path(__file__).parent / "lancedb_schema_check.js"
_SCHEMA_CHECK_CONTAINER_PATH = "/tmp/moogle_lancedb_schema_check.js"


def embed_texts(ollama_base_url: str, *, model: str, texts: list[str], timeout: int = 60) -> list[list[float]]:
    """Embed texts via Ollama's OpenAI-compatible endpoint (same one AnythingLLM's generic-openai embedder uses)."""
    base = ollama_base_url.rstrip("/")
    response = requests.post(f"{base}/v1/embeddings", json={"model": model, "input": texts}, timeout=timeout)
    response.raise_for_status()
    data = response.json()["data"]
    ordered = sorted(data, key=lambda item: item.get("index", 0))
    return [item["embedding"] for item in ordered]


def _run_node_script(
    *,
    container: str,
    script_host_path: Path,
    script_container_path: str,
    request: dict,
    timeout: int,
) -> dict | list:
    """Copy a small Node script + JSON request into the AnythingLLM container, run it, and parse its JSON stdout."""
    if shutil.which("docker") is None:
        raise RuntimeError("docker CLI not found on PATH; direct LanceDB access requires it")

    subprocess.run(
        ["docker", "cp", str(script_host_path), f"{container}:{script_container_path}"],
        check=True,
        capture_output=True,
    )

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(request, handle)
        request_path = handle.name

    try:
        container_request_path = "/tmp/moogle_lancedb_request.json"
        subprocess.run(["docker", "cp", request_path, f"{container}:{container_request_path}"], check=True, capture_output=True)
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-e",
                f"LANCEDB_SEARCH_REQUEST_FILE={container_request_path}",
                container,
                "node",
                "-e",
                (
                    "process.env.LANCEDB_SEARCH_REQUEST = require('fs')"
                    ".readFileSync(process.env.LANCEDB_SEARCH_REQUEST_FILE, 'utf8');"
                    f"require('{script_container_path}');"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    finally:
        Path(request_path).unlink(missing_ok=True)

    if result.returncode != 0:
        raise RuntimeError(f"direct LanceDB script failed ({script_container_path}): {result.stderr.strip()}")

    return json.loads(result.stdout)


def check_table_compatibility(
    *,
    container: str = DEFAULT_CONTAINER,
    storage_dir: str = DEFAULT_STORAGE_DIR,
    namespace: str,
    embedding_dim: int = DEFAULT_EMBEDDING_DIM,
    required_fields: tuple[str, ...] = REQUIRED_TABLE_FIELDS,
    timeout: int = 30,
) -> dict:
    """Verify the existing AnythingLLM LanceDB table is present and shaped as expected before direct retrieval.

    Raises RuntimeError with a clear diagnostic (and a recommendation to fall
    back to `--backend anythingllm`) if the table is missing or incompatible.
    Does not modify the table in any way.
    """
    info = _run_node_script(
        container=container,
        script_host_path=_SCHEMA_CHECK_SCRIPT_PATH,
        script_container_path=_SCHEMA_CHECK_CONTAINER_PATH,
        request={"storageDir": storage_dir, "namespace": namespace},
        timeout=timeout,
    )

    fallback_hint = "Fall back to --backend anythingllm, which does not depend on the LanceDB schema directly."

    if not info.get("exists"):
        raise RuntimeError(
            f"Direct LanceDB retrieval unavailable: table '{namespace}' not found under "
            f"{storage_dir} (tables present: {info.get('tables')}). "
            f"Expected a table named after the AnythingLLM workspace slug. {fallback_hint}"
        )

    fields = info.get("fields") or []
    missing_fields = [field for field in required_fields if field not in fields]
    if missing_fields:
        raise RuntimeError(
            f"Direct LanceDB retrieval unavailable: table '{namespace}' is missing required "
            f"field(s) {missing_fields} (found fields: {fields}). This usually means AnythingLLM's "
            f"storage schema has changed since this integration was written. {fallback_hint}"
        )

    vector_dim = info.get("vectorDim")
    if vector_dim != embedding_dim:
        raise RuntimeError(
            f"Direct LanceDB retrieval unavailable: table '{namespace}' has vector dimension "
            f"{vector_dim!r}, expected {embedding_dim} (mxbai-embed-large). The index may have been "
            f"built with a different embedding model, or the schema has changed. {fallback_hint}"
        )

    return info


def direct_vector_search(
    *,
    container: str = DEFAULT_CONTAINER,
    storage_dir: str = DEFAULT_STORAGE_DIR,
    namespace: str,
    queries: list[tuple[str, list[float], int]],
    similarity_threshold: float = 0.25,
    timeout: int = 60,
) -> dict[str, list[dict]]:
    """Run one or more vector searches directly against an existing AnythingLLM LanceDB table.

    `queries` is a list of (query_text, query_vector, top_n) tuples. All
    searches run inside a single `docker exec` call (one Node process, one
    table open) to minimize per-call process-spawn overhead.
    """
    decoded = _run_node_script(
        container=container,
        script_host_path=_SEARCH_SCRIPT_PATH,
        script_container_path=_SEARCH_CONTAINER_PATH,
        request={
            "storageDir": storage_dir,
            "namespace": namespace,
            "similarityThreshold": similarity_threshold,
            "queries": [{"query": query, "vector": vector, "topN": top_n} for query, vector, top_n in queries],
        },
        timeout=timeout,
    )
    return {item["query"]: item["sources"] for item in decoded}
