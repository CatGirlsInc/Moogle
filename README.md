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

## Docker stack

Copy the example env file:

```bash
cp .env.example .env
```

Start the stack:

```bash
docker compose up -d --wait
```

Services:

- AnythingLLM: `http://localhost:3001`
- Ollama API: `http://localhost:11434`

Both published ports are bound to `127.0.0.1`.

Optional GPU override for Ollama hosts with NVIDIA runtime support:

```bash
docker compose -f compose.yaml -f compose.gpu.yaml up -d --wait
```

## Clean rebuild from corpus

From trusted cleaned Markdown only:

```bash
docker compose down
# Remove runtime state only:
docker volume rm moogle_anythingllm
# Optional: also reset Ollama pulled models/cache
docker volume rm moogle_ollama

docker compose up -d --wait
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
