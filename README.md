# Moogle BG-Wiki RAG Project

This project prepares BG-Wiki content into cleaned Markdown and ingests that corpus into a local AnythingLLM workspace backed by Ollama.

Authoritative corpus output:

- `data/processed/markdown`

Everything after that stage (AnythingLLM vectors/indexes and app state) is treated as rebuildable runtime state.

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

**Known bottleneck:** AnythingLLM's `mode=query` endpoint always performs a
full LLM generation per call, even though the fan-out step only needs the
retrieved `sources`. Measured directly, this generation (not model loading or
GPU contention) dominates fan-out latency -- concurrency and a cheap fan-out
model help modestly, but a broad query with several sub-queries still takes
roughly 80-110s end to end. See repo memory / experiment notes for details;
the next step under consideration is replacing these calls with direct
LanceDB vector search.

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
