# Moogle

Moogle turns the [BG-Wiki](https://www.bg-wiki.com/) (Final Fantasy XI) MediaWiki
export into a cleaned Markdown knowledge base, and serves it through a local
[AnythingLLM](https://anythingllm.com/) + [Ollama](https://ollama.com/) RAG
stack backed by LanceDB.

This project is fan-made and unaffiliated with BG-Wiki or Square Enix. See
[BG-Wiki content and licensing](#bg-wiki-content-and-licensing).

## Contents

- [Architecture](#architecture)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [CLI reference](#cli-reference)
  - [`moogle bootstrap`](#moogle-bootstrap--build-the-corpus)
  - [`moogle up` / `moogle down`](#moogle-up--moogle-down--docker-stack)
  - [`moogle ingest`](#moogle-ingest--load-anythingllm)
  - [`moogle ask`](#moogle-ask--query-the-knowledge-base)
  - [`moogle knowledge`](#moogle-knowledge--corpus-releases)
  - [`moogle runtime`](#moogle-runtime--snapshot-management)
- [Release model](#release-model)
- [Pinned versions](#pinned-versions)
- [BG-Wiki content and licensing](#bg-wiki-content-and-licensing)
- [Development](#development)

## Architecture

Three independently-versioned layers:

| Layer | What it is | Source of truth? |
|---|---|---|
| Moogle application | This repo: CLI, Docker/runtime config | N/A (versioned as `v1.0.0`, etc.) |
| Knowledge corpus | `data/processed/markdown`, cleaned from the BG-Wiki dump | **Yes** — canonical |
| Runtime snapshot | AnythingLLM's LanceDB vectors + app state | No — rebuildable cache |

The knowledge corpus can always regenerate the runtime snapshot (`moogle ingest`).
The reverse is never true, so the runtime snapshot is treated as disposable.

Services, once running:

```
Ollama       http://localhost:11434   (embedding + chat models)
AnythingLLM  http://localhost:3001    (workspace UI/API, LanceDB storage)
```

Both ports are bound to `127.0.0.1` only.

## Requirements

- Docker + Docker Compose
- [uv](https://docs.astral.sh/uv/) (Python package/venv manager)
- ~10 GB disk for the knowledge corpus + Docker images; more for Ollama models

## Quick start

```bash
git clone https://github.com/CatGirlsInc/Moogle.git && cd Moogle
cp .env.example .env
uv sync --extra dev
```

Then pick one path:

**Reproducible** (rebuilds everything from the public BG-Wiki dump — default, recommended):

```bash
uv run moogle bootstrap   # download + clean the corpus into data/processed/markdown
uv run moogle up          # start Ollama + AnythingLLM
uv run moogle ingest       # load the corpus into an AnythingLLM workspace
```

**Fast** (restore a runtime snapshot you already built or were given privately, skipping ingestion):

```bash
uv run moogle runtime restore /path/to/anythingllm-snapshot.tar.zst
uv run moogle up
```

Then query it:

```bash
uv run moogle ask "What are all sources of accuracy for player characters in FFXI?"
```

## Configuration

All runtime configuration lives in `.env` (copy from `.env.example`). Key variables:

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_IMAGE` | `ollama/ollama:0.32.15` | pinned Ollama image |
| `ANYTHINGLLM_IMAGE` | `mintplexlabs/anythingllm:1.16.0` | pinned AnythingLLM image |
| `ANYTHINGLLM_CHAT_MODEL` | `llama3.2:3b` | default chat model |
| `ANYTHINGLLM_EMBEDDING_MODEL` | `mxbai-embed-large` | embedding model (1024-dim) |
| `ANYTHINGLLM_EMBEDDING_CONCURRENCY` | `16` | parallel embedding requests |
| `OLLAMA_MAX_LOADED_MODELS` | `2` | models kept resident in VRAM |

For an NVIDIA GPU, start with the GPU override applied (see `moogle up --gpu` below).

## CLI reference

### `moogle bootstrap` — build the corpus

Downloads the BG-Wiki MediaWiki export, decompresses it, splits it into
per-page XML, converts each page to Markdown, and removes empty/title-only
stub pages. Stages are skipped if their output already exists.

```bash
uv run moogle bootstrap           # build data/processed/markdown
uv run moogle bootstrap --force   # wipe data/raw + data/processed and rebuild
```

### `moogle up` / `moogle down` — Docker stack

Thin wrappers around `docker compose`:

```bash
uv run moogle up             # docker compose up -d --wait
uv run moogle up --gpu       # also apply compose.gpu.yaml (NVIDIA GPU passthrough)
uv run moogle up --no-wait   # don't wait for healthchecks

uv run moogle down             # docker compose down
uv run moogle down --gpu       # match the compose files used to start the stack
uv run moogle down --volumes   # also delete named volumes (destroys runtime state)
```

To rebuild AnythingLLM's runtime state from scratch (safe — the Markdown
corpus is the source of truth):

```bash
uv run moogle down
docker volume rm moogle_anythingllm   # wipe runtime state only
uv run moogle up
uv run moogle ingest
```

### `moogle ingest` — load AnythingLLM

Uploads `data/processed/markdown` into an AnythingLLM workspace (default
name `BG Wiki`, slug `bg-wiki`), parsing and embedding each file via
AnythingLLM's workspace API.

```bash
uv run moogle ingest                # full rebuild: recreates the workspace, uploads everything
uv run moogle ingest --dry-run      # preview what would be uploaded, no changes
uv run moogle ingest --resume       # preserve the workspace, skip already-attached files
uv run moogle ingest --preserve-workspace   # don't recreate the workspace first
```

Empty/title-only files and image sidecar files (`*.png.md`, `*.jpg.md`,
`*.jpeg.md`, `*.gif.md`) are skipped automatically. Use `--resume` for large
imports that may need to be restarted.

### `moogle ask` — query the knowledge base

Broad, enumeration-style questions ("what are all sources of X?") tend to
collapse onto one dominant document with a single embedded query. `moogle ask`
works around this: it decomposes the question into a handful of sub-queries,
retrieves and deduplicates chunks across all of them, then makes one
synthesis call to produce a grounded answer.

```bash
uv run moogle ask "What are all sources of accuracy for player characters in FFXI?"
uv run moogle ask "..." --verbose   # per-stage timing + diagnostics
```

Two retrieval backends, selected with `--backend`:

- **`direct-lancedb`** (recommended): queries AnythingLLM's LanceDB table
  directly, skipping AnythingLLM's own chat/generation step for retrieval.
  ~3x faster (~20-30s vs. ~80-110s for a broad query) because it avoids a
  throwaway LLM generation per sub-query. Runs a read-only compatibility
  check first (table exists, expected fields, expected vector dimension) and
  gives a clear error if that fails.
- **`anythingllm`** (default, fallback): fans out sub-queries through
  AnythingLLM's own `mode=query` chat endpoint. Slower, but has no
  assumptions about AnythingLLM's internal storage layout.

```bash
uv run moogle ask "..." --backend direct-lancedb
```

`direct-lancedb` assumes:

- one LanceDB table per AnythingLLM workspace, named after the workspace slug
- the table has `vector`, `text`, and `title` fields
- vectors are 1024-dimensional (matching `mxbai-embed-large`)

If an AnythingLLM upgrade changes any of this, the compatibility check will
fail with a message recommending `--backend anythingllm` instead.

Other useful flags: `--decompose-model`, `--synthesis-model`,
`--fanout-model` (which Ollama models to use for each stage),
`--max-subqueries`, `--top-k-per-query`, `--max-context-chunks`.

### `moogle knowledge` — corpus releases

Packages, verifies, and installs versioned releases of the processed
Markdown corpus (see [Release model](#release-model)).

```bash
# Package data/processed/markdown into a versioned archive + manifest
uv run moogle knowledge package bgwiki-20250225.1 --output dist

# Verify an archive's checksum against its manifest
uv run moogle knowledge verify dist/moogle-bgwiki-20250225.1.tar.zst dist/moogle-bgwiki-20250225.1.manifest.json

# Download (or use --archive/--manifest locally), verify, and extract into data/processed/markdown
uv run moogle knowledge install bgwiki-20250225.1 --base-url https://your-host/knowledge
```

Manifests record the Moogle version, knowledge version, source dump
identity, document count, embedding model/dimensions, tested
AnythingLLM/Ollama versions, and the archive's checksum. See
[`manifests/schema.json`](manifests/schema.json).

### `moogle runtime` — snapshot management

Backup, restore, and compact AnythingLLM's runtime state (LanceDB vectors +
app data). Always a rebuildable convenience artifact, never the source of truth.

```bash
# Back up the running volume to a tar.zst file (safe while the stack is up)
uv run moogle runtime backup backups/anythingllm-snapshot.tar.zst

# Restore into a fresh volume (stop the stack first)
uv run moogle down
uv run moogle runtime restore backups/anythingllm-snapshot.tar.zst
uv run moogle up

# Compact the LanceDB table before packaging a release snapshot
uv run moogle runtime compact --backup backups/pre-compact-safety.tar.zst
```

Notes:

- `backup` defaults to zstd level 3, not a high compression level — LanceDB
  volumes are dominated by float32 vectors, which barely compress, so a high
  level costs a lot of time for little size benefit. Use `--exclude
  vector-cache` to additionally drop AnythingLLM's re-embedding cache
  (rebuildable, not needed to query the existing table).
- `compact` runs LanceDB's own supported maintenance API (`Table#optimize()`,
  "modeled after `VACUUM` in PostgreSQL": compacts fragments and prunes old
  table versions). It stops the AnythingLLM container first, runs the
  maintenance in a throwaway container from the same image, restarts
  AnythingLLM, and verifies the row count and two known queries
  (`Accuracy Bonus`, `Blade Madrigal`) are unaffected. A safety backup is
  taken first by default (`--skip-backup` to opt out).
- LanceDB's incremental single-document ingest history can dominate the
  volume's size — compacting a corpus of ~48k documents reduced runtime
  storage from ~95 GB to ~5.4 GB with no data loss (verified: identical row
  count and identical retrieval scores before/after).

## Release model

```
Moogle application                    e.g. v1.0.0            (this repo, tagged)
processed Markdown knowledge corpus   e.g. bgwiki-20250225.1  (canonical source of truth)
runtime snapshot (optional)                                   (rebuildable cache)
```

The knowledge corpus and runtime snapshot are **not** published as public
GitHub Release assets by default — see
[BG-Wiki content and licensing](#bg-wiki-content-and-licensing). Two reasons
this matters in practice, independent of that policy:

- The knowledge archive is small (~13 MiB for the reference 47,941-document
  build) and would easily fit GitHub's 2 GB per-asset limit.
- An *uncompacted* runtime snapshot will not: it can reach tens of GB. Run
  `moogle runtime compact` before packaging one.

Both `moogle knowledge install` and `moogle runtime restore` accept a
`--base-url`/local path, so a fork or private deployment can point at its own
hosting without code changes.

## Pinned versions

Images are pinned to specific tags, not `latest`/`main`, for reproducibility:

| Component | Image | Version tested |
|---|---|---|
| Ollama | `ollama/ollama` | `0.32.15` |
| AnythingLLM | `mintplexlabs/anythingllm` | `1.16.0` |
| Embedding model | `mxbai-embed-large` | 1024 dimensions |

Override via `.env` (`OLLAMA_IMAGE`, `ANYTHINGLLM_IMAGE`) to test a newer
version; update the pinned defaults and any new knowledge manifest's
`tested_versions` once validated end-to-end.

## BG-Wiki content and licensing

Moogle's source code is MIT-licensed (see [`LICENSE`](LICENSE)). That license
does **not** cover BG-Wiki content: the processed Markdown corpus is derived
from [bg-wiki.com](https://www.bg-wiki.com/), a fan-maintained wiki for Final
Fantasy XI, and remains the property of its original contributors under
BG-Wiki's own terms. This project is unaffiliated with and not endorsed by
BG-Wiki or Square Enix; "Final Fantasy XI" is a trademark of Square Enix
Holdings Co., Ltd.

Because BG-Wiki's bulk-redistribution terms aren't confirmed, Moogle does not
re-host or redistribute the corpus or a runtime snapshot itself. `moogle
bootstrap` fetches the source MediaWiki dump directly from its public
archive.org mirror and builds the corpus locally under your own review of
BG-Wiki's terms. The `moogle knowledge`/`moogle runtime` commands still work
against your own privately-hosted archive if you have confirmed
redistribution rights.

## Development

```bash
uv sync --extra dev
uv run pytest -q
```

A useful manual retrieval check: ask "What exact formula does BG-Wiki give
for Accuracy from DEX?" — the top source should be the Accuracy document,
supporting `Accuracy from DEX = floor(DEX * 0.75)`.
