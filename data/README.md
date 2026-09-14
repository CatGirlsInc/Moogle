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

**Rebuild from the original BG-Wiki dump** (default/recommended -- Moogle
fetches the MediaWiki XML dump directly from its public archive.org mirror
and regenerates the corpus locally; see "BG-Wiki content and copyright" in
the top-level README for why this project doesn't re-host/redistribute that
content itself):

```bash
uv run moogle bootstrap
```

**Install a prebuilt knowledge version** (faster, no MediaWiki processing --
for teams with their own privately hosted, rights-confirmed archive):

```bash
uv run moogle knowledge install bgwiki-20250225.1 --base-url https://your-private-host/knowledge
```

This downloads the matching archive + manifest, verifies the archive's
SHA-256 checksum against the manifest, and extracts it into
`data/processed/markdown`. Use `--archive`/`--manifest` to install from local
files instead of downloading (e.g. artifacts already fetched by CI or copied
from another machine).

See the top-level [README](../README.md) for the full release model
(Moogle software version vs. knowledge version vs. optional runtime
snapshot) and the manifest schema in [`../manifests/`](../manifests/).
