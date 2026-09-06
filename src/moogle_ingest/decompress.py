from __future__ import annotations

import zstandard as zstd
from pathlib import Path


def decompress_archive(*, input_path: Path, output: Path, force: bool = False) -> Path:
    src = Path(input_path)
    dst = Path(output)

    if dst.exists() and dst.is_file() and not force:
        return dst

    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")

    with src.open("rb") as inf:
        dctx = zstd.ZstdDecompressor(max_window_size=1 << 30)
        with dctx.stream_reader(inf) as reader:
            with tmp.open("wb") as outf:
                while True:
                    chunk = reader.read(1024 * 1024)
                    if not chunk:
                        break
                    outf.write(chunk)

    tmp.replace(dst)
    print(f"Decompressed archive to {dst}")
    return dst
