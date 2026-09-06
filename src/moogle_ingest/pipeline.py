from __future__ import annotations

from pathlib import Path

from moogle_ingest.bootstrap import run_bootstrap


def run_pipeline(*, archive_path: Path, output_dir: Path, force: bool = False) -> None:
    run_bootstrap(archive_path=Path(archive_path), output_dir=Path(output_dir), force=force)
