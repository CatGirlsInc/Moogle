# Moogle BG-Wiki RAG Project

This project prepares BG-Wiki content into cleaned Markdown and ingests that corpus into a local AnythingLLM workspace backed by Ollama.

Authoritative corpus output:

- `data/processed/markdown`

Everything after that stage (AnythingLLM vectors/indexes and app state) is treated as rebuildable runtime state.

## BG-Wiki content and copyright

This repository's source code is MIT-licensed (see [`LICENSE`](LICENSE)). That
license does **not** cover BG-Wiki content: the processed Markdown corpus is
derived from [bg-wiki.com](https://www.bg-wiki.com/), a fan-maintained wiki
for Final Fantasy XI, and remains the property of its original
contributors/BG-Wiki under BG-Wiki's own terms. This project is unaffiliated
with and not endorsed by BG-Wiki or Square Enix; "Final Fantasy XI" is a
trademark of Square Enix Holdings Co., Ltd.

Because BG-Wiki's redistribution terms for bulk/derived corpus reuse aren't
confirmed, this project does **not** publish the processed-Markdown archive or
the AnythingLLM/LanceDB runtime snapshot (both embed full BG-Wiki article
text) as public GitHub Release assets. The default/recommended path is
`moogle bootstrap`, which fetches the MediaWiki XML dump directly from its
public archive.org mirror and regenerates the corpus locally under your own
review of BG-Wiki's terms -- Moogle itself never re-hosts or redistributes
that content. The `moogle knowledge`/`moogle runtime` commands below still
support packaging and installing prebuilt archives; use them with your own
privately hosted storage if you have confirmed rights to redistribute, not
with the public GitHub Release by default.

## Release model

Moogle ships as three independently versioned layers:

```text
Moogle application                  -- source code + Docker/runtime config, e.g. v1.0.0
processed Markdown knowledge corpus -- the canonical source of truth, e.g. bgwiki-20250225.1
optional AnythingLLM/LanceDB runtime snapshot -- rebuildable cache/convenience artifact
```

The knowledge version tracks the source BG-Wiki dump + downselection logic, not
the application code, so a knowledge release can be reused across multiple
Moogle versions and vice versa. The runtime snapshot is never authoritative --
it exists purely so a fresh clone can skip a multi-hour re-ingestion; it can
always be regenerated from the knowledge corpus via `moogle ingest`.

Release artifacts (see [`manifests/`](manifests/) and [`data/README.md`](data/README.md)):

1. source code + pinned `compose.yaml`/`compose.gpu.yaml`/image tags (Git, tagged `v1.0.0`) -- published publicly
2. `moogle-bgwiki-20250225.1.tar.zst` -- compressed processed-Markdown archive -- **not published publicly** (see "BG-Wiki content and copyright" above); build it yourself via `moogle bootstrap` + `moogle knowledge package`, or host it privately
3. `moogle-bgwiki-20250225.1.manifest.json` -- checksums + provenance for (2) -- published in Git under `manifests/` as schema documentation/reference, independent of whether the archive itself is hosted anywhere
4. optional `anythingllm-bgwiki-20250225.1.tar.zst` -- prebuilt AnythingLLM/LanceDB state snapshot -- also **not published publicly**, same reasoning as (2)

## Two supported install paths

**Fast** (skip re-ingestion, restore a runtime snapshot you built or were given privately):

```bash
git clone https://github.com/CatGirlsInc/Moogle.git && cd Moogle
cp .env.example .env
uv run moogle runtime restore /path/to/anythingllm-bgwiki-20250225.1.tar.zst
uv run moogle up
```

**Reproducible** (default/recommended -- rebuild the corpus + vectors locally from the public BG-Wiki dump):

```bash
git clone https://github.com/CatGirlsInc/Moogle.git && cd Moogle
cp .env.example .env
uv sync --extra dev
uv run moogle bootstrap
uv run moogle up
uv run moogle ingest
```

## Quick start

```bash
uv sync --extra dev
uv run moogle --help
```

## Commands

Build or refresh the cleaned corpus:

```bash
uv run moogle bootstrap
```

`bootstrap` runs:

- download
- decompress
- split
- convert
- downselect

To rebuild from scratch:

```bash
uv run moogle bootstrap --force
```

Ingest cleaned Markdown into AnythingLLM:

```bash
uv run moogle ingest
```

Useful ingest flags:

```bash
uv run moogle ingest --dry-run
uv run moogle ingest --input data/processed/markdown --base-url http://localhost:3001 --name "BG Wiki"
uv run moogle ingest --chat-model llama3.2:3b --embedding-model mxbai-embed-large
uv run moogle ingest --preserve-workspace
uv run moogle ingest --resume
```

Embedding throughput defaults:

- embeddings still use `mxbai-embed-large` from the existing Ollama service
- AnythingLLM is configured to call Ollama through its OpenAI-compatible `/v1` endpoint
- embedding concurrency is controlled by `ANYTHINGLLM_EMBEDDING_CONCURRENCY` and defaults to `16`

For long-running imports that need restartability, use:

- `uv run moogle ingest --resume`

Resume mode preserves the workspace and skips markdown files already attached to that workspace.

Default ingest behavior is deterministic rebuild:

- recreates the target workspace by default
- uploads eligible Markdown files only
- skips empty/title-only files and image-sidecar Markdown (`*.png.md`, `*.jpg.md`, `*.jpeg.md`, `*.gif.md`)
- parses and embeds each file through AnythingLLM workspace APIs (`/api/workspace/:slug/parse` then `/api/workspace/:slug/embed-parsed-file/:fileId`)

## Chat model comparison

Switch a workspace's chat model without touching its documents or vectors:

```bash
uv run moogle set-chat-model --workspace bg-wiki --model qwen2.5:7b-instruct-q4_K_M
uv run moogle set-chat-model --workspace bg-wiki --model llama3.2:3b
```

Pull additional models directly through Ollama, e.g.:

```bash
docker exec moogle-ollama ollama pull qwen2.5:7b-instruct-q4_K_M
```

## Broad-question retrieval (`moogle ask`)

Single embedded queries tend to collapse onto one dominant document for broad
enumeration-style questions (e.g. "what are all sources of X?"). `moogle ask`
works around this without a new database or reranker:

1. decomposes the question into up to 6 sub-queries that maximize coverage of
   the question's distinct aspects/mechanics/terminology (generic, not tied to
   a fixed category list; narrow single-entity lookups may decompose to
   nothing extra),
2. drops near-duplicate sub-queries (Jaccard similarity vs. the original
   question and each other),
3. runs each sub-query (plus the original) concurrently (bounded) through the
   existing AnythingLLM workspace in `query` mode purely to harvest retrieved
   source chunks -- the workspace's chat model is temporarily pinned to a
   cheap/fast model for this step since the generated text is discarded, then
   restored,
4. deduplicates/ranks the combined chunks by similarity score,
5. makes one direct call to Ollama (bypassing AnythingLLM's own retrieval) to
   synthesize a grounded final answer from the deduplicated context.

```bash
uv run moogle ask "What are all sources of accuracy for player characters in FFXI?"
```

Useful flags:

```bash
uv run moogle ask "..." --decompose-model qwen2.5:7b-instruct-q4_K_M
uv run moogle ask "..." --synthesis-model llama3.2:3b
uv run moogle ask "..." --fanout-model llama3.2:3b
uv run moogle ask "..." --top-k-per-query 3 --max-context-chunks 14
uv run moogle ask "..." --concurrency 3
uv run moogle ask "..." --verbose   # per-stage timing + diagnostics
```

`--synthesis-model` and `--decompose-model` call Ollama directly and are
independent of the workspace's own `chatModel` setting. `--fanout-model` is
temporarily applied to the workspace for the retrieval-only sub-query calls
and restored afterward.

`--synthesis-model` and `--decompose-model` call Ollama directly and are
independent of the workspace's own `chatModel` setting. `--fanout-model` is
temporarily applied to the workspace for the retrieval-only sub-query calls
and restored afterward.

**`--backend anythingllm` (default) known bottleneck:** AnythingLLM's
`mode=query` endpoint always performs a full LLM generation per call, even
though the fan-out step only needs the retrieved `sources`. Measured
directly, this generation (not model loading or GPU contention) dominates
fan-out latency -- a broad query with several sub-queries takes roughly
80-110s end to end.

**`--backend direct-lancedb`:** bypasses AnythingLLM's chat endpoint for
retrieval entirely. It embeds sub-queries with the same `mxbai-embed-large`
model/endpoint AnythingLLM itself uses, then runs the vector search directly
against AnythingLLM's own LanceDB table via `docker exec` into the
AnythingLLM container (reusing its bundled `@lancedb/lancedb` client and
on-disk index -- no re-embedding, no new database, no Python LanceDB
dependency). This eliminates the throwaway generation and brought the same
broad queries down to ~20-30s in testing:

```bash
uv run moogle ask "..." --backend direct-lancedb --verbose
uv run moogle ask "..." --backend direct-lancedb --container moogle-anythingllm --storage-dir /app/server/storage/lancedb
```

Before every search, `direct-lancedb` runs a lightweight read-only
compatibility check (table exists, `vector`/`text`/`title` fields present,
vector dimension matches the embedding model) and fails fast with a clear
error recommending `--backend anythingllm` if the table is missing or
schema-incompatible -- e.g. after an AnythingLLM upgrade that changes its
storage layout, or if the workspace was embedded with a different model.

The `anythingllm` backend remains the default/fallback for comparison; both
share the same decomposition, dedup/ranking, and synthesis code.

## Knowledge corpus (package / verify / install)

`data/processed/markdown` is not committed to Git (see `.gitignore`); it is
installed or rebuilt locally. See [`data/README.md`](data/README.md) for the
full directory layout. The default/recommended way to populate it is
`moogle bootstrap` (fetches the public BG-Wiki dump directly, see above).

`moogle knowledge install`/`package` exist for teams that host their own
prebuilt archive (e.g. private object storage or a private GitHub Release)
and want the same checksum-verified install flow without re-running the full
pipeline:

```bash
uv run moogle knowledge install bgwiki-20250225.1 --base-url https://your-private-host/knowledge
```

This fetches `moogle-bgwiki-20250225.1.tar.zst` + its manifest, verifies the
archive's SHA-256 checksum against the manifest, and extracts it into
`data/processed/markdown`. Use `--archive`/`--manifest` to install from local
files instead of downloading. `--github-repo`/the default GitHub Releases URL
form are supported but nothing is published there by default -- see
"BG-Wiki content and copyright" above.

Verify an archive you already have against its manifest:

```bash
uv run moogle knowledge verify moogle-bgwiki-20250225.1.tar.zst manifests/moogle-bgwiki-20250225.1.manifest.json
```

Package a freshly bootstrapped corpus into a new release (used to cut a new
knowledge version, e.g. after a BG-Wiki dump refresh):

```bash
uv run moogle knowledge package bgwiki-20250225.1 \
  --input data/processed/markdown \
  --output dist \
  --source-dump-checksum <sha256 of the raw .xml.zst dump>
```

See [`manifests/schema.json`](manifests/schema.json) for the manifest fields:
Moogle version, knowledge version, source dump identity, document count,
embedding model/dimensions, tested AnythingLLM/Ollama versions, and the
archive's checksum/size.

## Runtime snapshot backup / restore

The AnythingLLM Docker volume (LanceDB index + app state) is rebuildable cache,
never the source of truth, but backing it up avoids repeating a multi-hour
ingest. Back it up while the stack is running (LanceDB files are read, not
locked):

```bash
uv run moogle runtime backup backups/anythingllm-bgwiki-20250225.1.tar.zst
```

Restore into a fresh clone (stack should be stopped first so nothing is
writing to the volume concurrently):

```bash
uv run moogle down
uv run moogle runtime restore backups/anythingllm-bgwiki-20250225.1.tar.zst
uv run moogle up
```

Both commands run a short-lived helper container (`alpine`) that mounts the
named volume (default `moogle_anythingllm`) alongside the host backup file and
tar+zstd its contents -- no changes to the running `anythingllm`/`ollama`
containers themselves. This snapshot embeds full BG-Wiki article text (in
LanceDB's `text` column), so treat it the same as the knowledge archive: keep
it out of the public GitHub Release, and if you distribute it privately, label
it clearly as a rebuildable convenience artifact, not the source of truth.

**Size/speed note:** the full-corpus LanceDB volume for this project measured
~95 GB (dominated by 1024-dimensional float32 vectors, which barely
compress). `moogle runtime backup` defaults to zstd level 3 (~85 MB/s
observed, multithreaded) rather than a high compression level for exactly
this reason -- level 19 was tested and was impractically slow for a volume
this size. Use `--level` to trade off further; a runtime snapshot at this
scale is well beyond what's practical to attach to a GitHub Release (see
"GitHub Release size limits" below) even before the copyright concern above.

## Runtime compaction (`moogle runtime compact`)

Most of that ~95 GB is not live data -- it's LanceDB's own historical version
chain from many incremental ingest runs (`_versions/`), not the current table
contents (`data/` was ~1.2 GB in the same measurement). Before packaging a
runtime snapshot for release, run:

```bash
uv run moogle runtime compact --backup backups/anythingllm-pre-compact.tar.zst
```

This uses LanceDB's own supported maintenance API, `Table#optimize()`
("modeled after `VACUUM` in PostgreSQL": compacts small fragments, prunes old
table versions, refreshes indices) -- it never touches `_versions`/data files
directly. Concretely, `moogle runtime compact`:

1. records the current on-disk storage size and the table's row count,
2. takes a safety backup first via `moogle runtime backup` (required unless
   `--skip-backup` is passed explicitly),
3. stops the `anythingllm` container so nothing writes to the table
   concurrently,
4. runs `optimize()` inside a throwaway container built from the *same*
   AnythingLLM image (so it uses the exact same bundled LanceDB client
   version) with the volume mounted, keeping only the current table version
   by default (`--cleanup-older-than-days 0`),
5. restarts the `anythingllm` container (always, even if compaction fails),
6. verifies the row count is unchanged, the table opens normally, and the
   `direct-lancedb` retrieval backend still returns the expected top result
   for two known queries (`Accuracy Bonus`, `Blade Madrigal`) -- skip with
   `--skip-verify`.

Useful flags: `--cleanup-older-than-days N` (keep more history instead of
just the current version), `--workspace <slug>` for a different table,
`--skip-backup`/`--skip-verify` to speed up repeat runs once you trust the
result on a given volume.

**Verified result (2026-09-14, `bg-wiki` table, 196,988 rows):** storage went
from 94.85 GiB to 5.38 GiB (freed 89.47 GiB) in a single run --
`fragmentsRemoved: 47941`, `oldVersionsRemoved: 47942`, `bytesRemoved: ~97 GB`.
Row count and per-query similarity scores for both verification queries were
bit-for-bit identical before and after (same top document, same score to 15
decimal places), confirming `optimize()` only compacted/pruned history and
never touched live vectors.

**`vector-cache/` (~4.4 GB):** AnythingLLM's own source
(`utils/files/index.js`, `cachedVectorInformation()`) confirms this is a
rebuildable cache keyed by filename, used only to skip *re-embedding* a
document if it's added to a workspace again -- it is not read at query time
and is unrelated to the live LanceDB table. It is **not required** for a
fast-start runtime snapshot; `moogle runtime backup --exclude vector-cache`
omits it. The live volume is left untouched either way -- excluding it only
affects what goes into a *packaged* snapshot, not the running stack (which
still benefits from the cache if it re-processes a document later).

Final packaged release snapshot for this corpus:
`anythingllm-bgwiki-20250225.1.tar.zst`, **761 MiB** (`--level 19 --exclude
vector-cache`, only practical to use a high compression level *after*
compaction -- 1.2 GiB uncompressed at this point, vs. the ~95 GB/25.6 GiB
before compaction).

## Compatibility assumptions (`--backend direct-lancedb`)

The direct LanceDB retrieval backend (see `moogle ask` below) reads
AnythingLLM's own on-disk LanceDB tables directly and assumes:

- **workspace/table naming:** one LanceDB table per AnythingLLM workspace,
  named exactly the workspace slug (e.g. workspace `bg-wiki` -> table `bg-wiki`)
- **required fields:** `vector` (embedding), `text` (chunk content), `title`
  (document title) must be present on the table
- **vector dimensionality:** 1024-dimensional vectors, matching
  `mxbai-embed-large` (the default embedding model here) -- a different
  embedding model with a different dimension count will fail the
  compatibility check

A read-only compatibility check runs automatically before every
`direct-lancedb` query and fails fast with a clear error (recommending
`--backend anythingllm`) if the table is missing or the schema doesn't match --
e.g. after an AnythingLLM upgrade that changes its storage layout, or if a
workspace was embedded with a different model. The `anythingllm` backend is
preserved as the default/fallback for exactly this reason.

## Pinned runtime versions

Images are pinned to specific tags, not `latest`/`main`, for reproducibility:

| Component   | Image                                    | Version tested |
|-------------|-------------------------------------------|----------------|
| Ollama      | `ollama/ollama`                           | `0.32.15`      |
| AnythingLLM | `mintplexlabs/anythingllm`                 | `1.16.0`       |

Override via `.env` (`OLLAMA_IMAGE`, `ANYTHINGLLM_IMAGE`) if testing a newer
version; update the pinned defaults in `compose.yaml`/`.env.example` and the
`tested_versions` fields recorded in new knowledge manifests once a newer
combination has been validated end-to-end.

## GitHub Release size limits

GitHub Releases accepts individual assets up to 2 GB. The processed-Markdown
corpus packages small (the reference `bgwiki-20250225.1` build is ~13 MiB
compressed for 47,941 documents, see [`manifests/`](manifests/)) and would fit
comfortably if it were published there. The AnythingLLM/LanceDB runtime
snapshot does not: the full-corpus volume measured **~95 GB** uncompressed
(mostly incompressible float32 embedding vectors), tens of GB even after
compression -- far over the per-asset limit and impractical to host on GitHub
regardless. Combined with the unresolved BG-Wiki redistribution question
above, neither artifact is published to the public GitHub Release for this
project; both `moogle knowledge install` and `moogle runtime restore` accept
`--base-url`/a local path so a fork or private deployment can point at its own
object storage without any code changes if/when that becomes necessary.

## Docker stack

Copy the example env file:

```bash
cp .env.example .env
```

Start the stack:

```bash
uv run moogle up
```

Stop the stack:

```bash
uv run moogle down
```

Services:

- AnythingLLM: `http://localhost:3001`
- Ollama API: `http://localhost:11434`

Both published ports are bound to `127.0.0.1`.

`up`/`down` are thin wrappers around `docker compose`, equivalent to `docker compose up -d --wait` / `docker compose down`. Useful flags:

```bash
uv run moogle up --gpu       # also apply compose.gpu.yaml
uv run moogle up --no-wait   # don't wait for healthchecks
uv run moogle down --gpu     # match the compose files used to start the stack
uv run moogle down --volumes # also remove named volumes (destroys runtime state)
```

## Clean rebuild from corpus

From trusted cleaned Markdown only:

```bash
uv run moogle down
# Remove runtime state only:
docker volume rm moogle_anythingllm
# Optional: also reset Ollama pulled models/cache
docker volume rm moogle_ollama

uv run moogle up
uv run moogle ingest
```

## Validation

Run tests:

```bash
uv run pytest -q
```

Expected retrieval check prompt:

- What exact formula does BG-Wiki give for Accuracy from DEX?

Expected evidence should include the Accuracy document and support:

- Accuracy from DEX = floor(DEX * 0.75)
