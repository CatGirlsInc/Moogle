"""Packaging, verification, and installation of the processed-Markdown knowledge corpus.

The processed Markdown under `data/processed/markdown` is the canonical source of
truth for Moogle's BG-Wiki knowledge. This module treats it as a versioned,
independently distributable artifact (e.g. `bgwiki-20250225.1`), separate from
the Moogle application version and separate from any rebuildable AnythingLLM/
LanceDB runtime snapshot (see `runtime_snapshot.py`).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import zstandard as zstd

from moogle_ingest.download import download_archive

DEFAULT_GITHUB_REPO = "CatGirlsInc/Moogle"
MANIFEST_SCHEMA_VERSION = 1


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def archive_name(knowledge_version: str) -> str:
    return f"moogle-{knowledge_version}.tar.zst"


def manifest_name(knowledge_version: str) -> str:
    return f"moogle-{knowledge_version}.manifest.json"


def _github_asset_url(repo: str, knowledge_version: str, filename: str) -> str:
    return f"https://github.com/{repo}/releases/download/knowledge-{knowledge_version}/{filename}"


@dataclass
class SourceDump:
    name: str
    retrieved_date: str
    checksum: str | None = None


def package_markdown_corpus(
    *,
    input_dir: Path,
    output_dir: Path,
    knowledge_version: str,
    moogle_version: str,
    source_dump: SourceDump,
    embedding_model: str = "mxbai-embed-large",
    embedding_dimensions: int = 1024,
    tested_anythingllm_version: str = "1.16.0",
    tested_ollama_version: str = "0.32.15",
) -> dict:
    """Tar+zstd the processed Markdown corpus and write its release manifest.

    Returns a dict with `archive_path`, `manifest_path`, and the manifest contents.
    """
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    markdown_files = sorted(input_dir.rglob("*.md"))
    if not markdown_files:
        raise FileNotFoundError(f"No markdown files found under: {input_dir}")

    archive_path = output_dir / archive_name(knowledge_version)
    tmp_path = archive_path.with_suffix(archive_path.suffix + ".part")

    cctx = zstd.ZstdCompressor(level=19)
    with tmp_path.open("wb") as raw_out:
        with cctx.stream_writer(raw_out) as compressed_out:
            with tarfile.open(fileobj=compressed_out, mode="w|") as tar:
                tar.add(input_dir, arcname="markdown")
    tmp_path.replace(archive_path)

    checksum = sha256_file(archive_path)
    size_bytes = archive_path.stat().st_size

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "moogle_version": moogle_version,
        "knowledge_version": knowledge_version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_dump": {
            "name": source_dump.name,
            "retrieved_date": source_dump.retrieved_date,
            "checksum": source_dump.checksum,
        },
        "document_count": len(markdown_files),
        "embedding_model": {
            "name": embedding_model,
            "dimensions": embedding_dimensions,
        },
        "tested_versions": {
            "anythingllm": tested_anythingllm_version,
            "ollama": tested_ollama_version,
        },
        "archive": {
            "filename": archive_path.name,
            "sha256": checksum,
            "size_bytes": size_bytes,
        },
    }

    manifest_path = output_dir / manifest_name(knowledge_version)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"Packaged {len(markdown_files)} markdown files into {archive_path} ({size_bytes / (1024 * 1024):.1f} MiB)")
    print(f"Wrote manifest to {manifest_path}")
    return {"archive_path": archive_path, "manifest_path": manifest_path, "manifest": manifest}


def load_manifest(manifest_path: Path) -> dict:
    return json.loads(Path(manifest_path).read_text(encoding="utf-8"))


def verify_archive(*, archive_path: Path, manifest_path: Path) -> dict:
    """Verify an archive's size and SHA-256 checksum against its manifest.

    Raises RuntimeError with a clear diagnostic on any mismatch.
    """
    archive_path = Path(archive_path)
    manifest = load_manifest(manifest_path)
    expected = manifest.get("archive", {})

    if not archive_path.exists():
        raise RuntimeError(f"Archive not found: {archive_path}")

    actual_size = archive_path.stat().st_size
    if expected.get("size_bytes") is not None and actual_size != expected["size_bytes"]:
        raise RuntimeError(
            f"Archive size mismatch for {archive_path.name}: "
            f"expected {expected['size_bytes']} bytes, got {actual_size} bytes"
        )

    actual_checksum = sha256_file(archive_path)
    expected_checksum = expected.get("sha256")
    if expected_checksum and actual_checksum != expected_checksum:
        raise RuntimeError(
            f"Checksum mismatch for {archive_path.name}: "
            f"expected sha256={expected_checksum}, got sha256={actual_checksum}. "
            "The archive may be corrupt or tampered with; re-download it."
        )

    print(f"Verified {archive_path.name}: sha256={actual_checksum} size={actual_size} bytes")
    return manifest


def _extract_archive(archive_path: Path, dest_dir: Path) -> None:
    """Extract a moogle knowledge tar.zst archive, guarding against path traversal."""
    dest_dir = Path(dest_dir)
    dest_dir.parent.mkdir(parents=True, exist_ok=True)

    dctx = zstd.ZstdDecompressor(max_window_size=1 << 30)
    with archive_path.open("rb") as raw_in:
        with dctx.stream_reader(raw_in) as reader:
            with tarfile.open(fileobj=reader, mode="r|") as tar:
                extract_root = dest_dir.parent.resolve()
                for member in tar:
                    member_path = (extract_root / member.name).resolve()
                    if not str(member_path).startswith(str(extract_root)):
                        raise RuntimeError(f"Refusing to extract archive member outside destination: {member.name}")
                    tar.extract(member, path=extract_root)


def install_knowledge(
    *,
    knowledge_version: str,
    dest_dir: Path,
    archive_path: Path | None = None,
    manifest_path: Path | None = None,
    base_url: str | None = None,
    github_repo: str = DEFAULT_GITHUB_REPO,
    download_dir: Path | None = None,
    force: bool = False,
) -> Path:
    """Download (or reuse local), verify, and extract a knowledge release.

    `dest_dir` is the target markdown directory (e.g. `data/processed/markdown`).
    If `archive_path`/`manifest_path` are given, they are used directly (offline
    install / already-downloaded artifacts). Otherwise both are fetched from
    `base_url` (or a GitHub Releases URL derived from `github_repo`).
    """
    dest_dir = Path(dest_dir)
    if dest_dir.exists() and any(dest_dir.iterdir()) and not force:
        raise RuntimeError(f"Destination already has content: {dest_dir}. Use --force to overwrite.")

    download_dir = Path(download_dir) if download_dir else dest_dir.parent.parent / "downloads"
    download_dir.mkdir(parents=True, exist_ok=True)

    if archive_path is None or manifest_path is None:
        archive_filename = archive_name(knowledge_version)
        manifest_filename = manifest_name(knowledge_version)
        if base_url:
            archive_url = f"{base_url.rstrip('/')}/{archive_filename}"
            manifest_url = f"{base_url.rstrip('/')}/{manifest_filename}"
        else:
            archive_url = _github_asset_url(github_repo, knowledge_version, archive_filename)
            manifest_url = _github_asset_url(github_repo, knowledge_version, manifest_filename)

        archive_path = download_dir / archive_filename
        manifest_path = download_dir / manifest_filename

        download_archive(url=manifest_url, output=manifest_path, force=force)
        download_archive(url=archive_url, output=archive_path, force=force)

    verify_archive(archive_path=archive_path, manifest_path=manifest_path)

    if dest_dir.exists() and force:
        for child in dest_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

    _extract_archive(archive_path, dest_dir)
    print(f"Installed knowledge {knowledge_version} into {dest_dir}")
    return dest_dir
