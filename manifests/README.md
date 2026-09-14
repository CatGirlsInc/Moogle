# manifests/

Release manifests for versioned knowledge corpus releases (see [`../data/README.md`](../data/README.md)
and the top-level README's "Release model" section).

- `schema.json` — JSON Schema for a knowledge release manifest.
- `moogle-<knowledge_version>.manifest.json` — one manifest per published knowledge
  release, e.g. `moogle-bgwiki-20250225.1.manifest.json`.

Each manifest records: the Moogle software version it was packaged with, the
knowledge version, the source MediaWiki dump identity, document count,
embedding model/dimensions, tested AnythingLLM/Ollama versions, and the
archive's SHA-256 checksum + size. Manifests are small, contain no BG-Wiki
content themselves, and are checked into Git as schema documentation/
reference and as the thing `moogle knowledge install`/`moogle knowledge
verify` trust. The (large) archive itself embeds full BG-Wiki article text
and is **not** published as a public GitHub Release asset by default -- see
"BG-Wiki content and copyright" in the top-level README. Host it privately
if you have confirmed redistribution rights, or regenerate it locally via
`moogle bootstrap` + `moogle knowledge package`.

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
