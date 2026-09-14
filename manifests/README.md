# manifests/

Release manifests for versioned knowledge corpus releases (see [`../data/README.md`](../data/README.md)
and the top-level README's "Release model" section).

- `schema.json` — JSON Schema for a knowledge release manifest.
- `moogle-<knowledge_version>.manifest.json` — one manifest per published knowledge
  release, e.g. `moogle-bgwiki-20250225.1.manifest.json`.

Each manifest records: the Moogle software version it was packaged with, the
knowledge version, the source MediaWiki dump identity, document count,
embedding model/dimensions, tested AnythingLLM/Ollama versions, and the
archive's SHA-256 checksum + size. Manifests are small, checked into Git, and
are the thing `moogle knowledge install`/`moogle knowledge verify` trust —
the (large) archive itself is not committed to Git; it is attached to the
matching GitHub Release (tag `knowledge-<knowledge_version>`) instead.

Generate a manifest + archive from a local corpus:

```bash
uv run moogle knowledge package bgwiki-20250225.1 \
  --input data/processed/markdown \
  --output dist \
  --source-dump-checksum <sha256 of the raw .xml.zst dump>
```

Verify an archive against its manifest:

```bash
uv run moogle knowledge verify dist/moogle-bgwiki-20250225.1.tar.zst manifests/moogle-bgwiki-20250225.1.manifest.json
```
