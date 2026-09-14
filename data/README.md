# data/

This directory holds the pipeline's raw and processed data. Its contents are
**not** committed to Git (see `.gitignore`) — everything here is either
downloaded, generated, or installed by `moogle` commands.

```text
data/
  raw/          the MediaWiki XML dump (downloaded/decompressed by `moogle bootstrap`)
  processed/
    xml/        one XML file per wiki page (intermediate, from `moogle bootstrap`)
    metadata/   page manifest + redirect map (intermediate, from `moogle bootstrap`)
    markdown/   the canonical cleaned Markdown knowledge corpus
  downloads/    cached knowledge archives/manifests fetched by `moogle knowledge install`
```

`data/processed/markdown` is the canonical source of truth for Moogle's
knowledge — everything downstream of it (AnythingLLM documents, LanceDB
vectors) is rebuildable cache, not authoritative content.

## Getting the knowledge corpus

Two ways to populate `data/processed/markdown`:

**Install a released knowledge version** (fast, no MediaWiki processing):

```bash
uv run moogle knowledge install bgwiki-20250225.1
```

This downloads the matching archive + manifest from the project's GitHub
Releases (tag `knowledge-bgwiki-20250225.1`), verifies the archive's SHA-256
checksum against the manifest, and extracts it into `data/processed/markdown`.
Use `--archive`/`--manifest` to install from local files instead of
downloading (e.g. artifacts already fetched by CI or copied from another
machine).

**Rebuild from the original BG-Wiki dump** (reproducible, but takes longer —
downloads and reprocesses the full MediaWiki export):

```bash
uv run moogle bootstrap
```

See the top-level [README](../README.md) for the full release model
(Moogle software version vs. knowledge version vs. optional runtime
snapshot) and the manifest schema in [`../manifests/`](../manifests/).
