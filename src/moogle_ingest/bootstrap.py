from __future__ import annotations

import shutil
from pathlib import Path

from moogle_ingest.convert import convert_pages_to_markdown
from moogle_ingest.decompress import decompress_archive
from moogle_ingest.download import download_archive
from moogle_ingest.downselect import downselect_markdown
from moogle_ingest.split import split_mediawiki_xml


DEFAULT_ARCHIVE_URL = "https://archive.org/download/wiki-www.bg-wiki.com-20250225/www.bg-wiki.com-20250225-current.xml.zst"
DEFAULT_ARCHIVE_NAME = "www.bg-wiki.com-20250225-current.xml.zst"
DEFAULT_XML_NAME = "www.bg-wiki.com-20250225-current.xml"


def _directory_has_files(path: Path, pattern: str) -> bool:
    return path.exists() and any(path.rglob(pattern))


def _clear_previous_outputs(raw_dir: Path, output_dir: Path) -> None:
    for path in (raw_dir, output_dir):
        if path.exists():
            shutil.rmtree(path)


def run_bootstrap(*, archive_path: Path, output_dir: Path, force: bool = False) -> None:
    archive_path = Path(archive_path)
    output_dir = Path(output_dir)

    raw_dir = output_dir.parent / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    if force:
        _clear_previous_outputs(raw_dir, output_dir)
        raw_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

    if not archive_path.exists() or not archive_path.is_file():
        archive_path = raw_dir / DEFAULT_ARCHIVE_NAME

    xml_path = raw_dir / DEFAULT_XML_NAME
    xml_dir = output_dir / "xml"
    markdown_dir = output_dir / "markdown"
    metadata_dir = output_dir / "metadata"
    manifest_path = metadata_dir / "pages.jsonl"

    if archive_path.exists() and archive_path.is_file():
        print(f"Skipping download; archive already exists at {archive_path}")
    else:
        download_archive(url=DEFAULT_ARCHIVE_URL, output=archive_path, force=False)

    if xml_path.exists() and xml_path.is_file():
        print(f"Skipping decompress; XML already exists at {xml_path}")
    else:
        decompress_archive(input_path=archive_path, output=xml_path, force=False)

    if manifest_path.exists() and _directory_has_files(xml_dir, "*.xml"):
        print(f"Skipping split; XML pages already exist in {xml_dir}")
    else:
        split_mediawiki_xml(input_path=xml_path, output_dir=xml_dir, manifest_path=manifest_path)

    if _directory_has_files(markdown_dir, "*.md"):
        print(f"Skipping convert; markdown already exists in {markdown_dir}")
    else:
        convert_pages_to_markdown(input_dir=xml_dir, output_dir=markdown_dir, manifest_path=manifest_path)

    downselect_markdown(input_dir=markdown_dir)
    print(f"Bootstrap complete. Output written to {output_dir}")