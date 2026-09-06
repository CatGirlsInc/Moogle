from __future__ import annotations

import hashlib
from pathlib import Path

import requests


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download_archive(*, url: str, output: Path, force: bool = False) -> Path:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    if output.exists() and output.is_file() and not force:
        return output

    tmp = output.with_suffix(output.suffix + ".part")
    headers = {}
    if tmp.exists():
        headers["Range"] = f"bytes={tmp.stat().st_size}-"

    with requests.get(url, headers=headers, stream=True, timeout=60) as response:
        response.raise_for_status()
        with tmp.open("wb") as out:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    out.write(chunk)

    tmp.replace(output)
    print(f"Downloaded archive to {output} ({_sha256_file(output)[:12]})")
    return output
