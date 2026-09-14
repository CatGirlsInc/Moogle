from __future__ import annotations

from pathlib import Path

import pytest

from moogle_ingest.knowledge import SourceDump, install_knowledge, package_markdown_corpus, verify_archive


def _make_corpus(root: Path) -> Path:
    markdown_dir = root / "markdown"
    markdown_dir.mkdir(parents=True)
    (markdown_dir / "1-Test-Page.md").write_text("---\ntitle: \"Test Page\"\n---\n\n# Test Page\n\nContent.\n", encoding="utf-8")
    (markdown_dir / "2-Other-Page.md").write_text("---\ntitle: \"Other Page\"\n---\n\n# Other Page\n\nMore content.\n", encoding="utf-8")
    return markdown_dir


def test_package_markdown_corpus_writes_archive_and_manifest(tmp_path: Path):
    markdown_dir = _make_corpus(tmp_path / "corpus")
    output_dir = tmp_path / "dist"

    result = package_markdown_corpus(
        input_dir=markdown_dir,
        output_dir=output_dir,
        knowledge_version="bgwiki-test.1",
        moogle_version="1.0.0",
        source_dump=SourceDump(name="test-dump.xml.zst", retrieved_date="2025-02-25", checksum="deadbeef"),
    )

    assert result["archive_path"].exists()
    assert result["manifest_path"].exists()
    assert result["manifest"]["document_count"] == 2
    assert result["manifest"]["knowledge_version"] == "bgwiki-test.1"
    assert result["manifest"]["archive"]["sha256"]


def test_verify_archive_detects_corruption(tmp_path: Path):
    markdown_dir = _make_corpus(tmp_path / "corpus")
    output_dir = tmp_path / "dist"
    result = package_markdown_corpus(
        input_dir=markdown_dir,
        output_dir=output_dir,
        knowledge_version="bgwiki-test.1",
        moogle_version="1.0.0",
        source_dump=SourceDump(name="test-dump.xml.zst", retrieved_date="2025-02-25"),
    )

    verify_archive(archive_path=result["archive_path"], manifest_path=result["manifest_path"])

    with result["archive_path"].open("ab") as f:
        f.write(b"corruption")

    with pytest.raises(RuntimeError, match="Checksum mismatch|size mismatch"):
        verify_archive(archive_path=result["archive_path"], manifest_path=result["manifest_path"])


def test_install_knowledge_from_local_archive(tmp_path: Path):
    markdown_dir = _make_corpus(tmp_path / "corpus")
    output_dir = tmp_path / "dist"
    result = package_markdown_corpus(
        input_dir=markdown_dir,
        output_dir=output_dir,
        knowledge_version="bgwiki-test.1",
        moogle_version="1.0.0",
        source_dump=SourceDump(name="test-dump.xml.zst", retrieved_date="2025-02-25"),
    )

    dest_dir = tmp_path / "installed" / "markdown"
    install_knowledge(
        knowledge_version="bgwiki-test.1",
        dest_dir=dest_dir,
        archive_path=result["archive_path"],
        manifest_path=result["manifest_path"],
    )

    installed_files = sorted(p.name for p in dest_dir.glob("*.md"))
    assert installed_files == ["1-Test-Page.md", "2-Other-Page.md"]


def test_install_knowledge_refuses_nonempty_destination_without_force(tmp_path: Path):
    markdown_dir = _make_corpus(tmp_path / "corpus")
    output_dir = tmp_path / "dist"
    result = package_markdown_corpus(
        input_dir=markdown_dir,
        output_dir=output_dir,
        knowledge_version="bgwiki-test.1",
        moogle_version="1.0.0",
        source_dump=SourceDump(name="test-dump.xml.zst", retrieved_date="2025-02-25"),
    )

    dest_dir = tmp_path / "installed" / "markdown"
    dest_dir.mkdir(parents=True)
    (dest_dir / "existing.md").write_text("pre-existing", encoding="utf-8")

    with pytest.raises(RuntimeError, match="already has content"):
        install_knowledge(
            knowledge_version="bgwiki-test.1",
            dest_dir=dest_dir,
            archive_path=result["archive_path"],
            manifest_path=result["manifest_path"],
        )
