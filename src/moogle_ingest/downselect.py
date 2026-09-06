from __future__ import annotations

from pathlib import Path

from moogle_ingest.anythingllm import has_meaningful_markdown_content


def downselect_markdown(*, input_dir: Path) -> dict[str, int]:
    source_dir = Path(input_dir)
    if not source_dir.exists():
        raise FileNotFoundError(f"Prepared markdown directory not found: {source_dir}")

    markdown_files = sorted(source_dir.rglob("*.md"))
    kept = 0
    removed = 0

    for markdown_file in markdown_files:
        if has_meaningful_markdown_content(markdown_file):
            kept += 1
            continue

        markdown_file.unlink()
        removed += 1

    print(f"Downselected markdown corpus in {source_dir}: kept {kept}, removed {removed}")
    return {"kept": kept, "removed": removed}