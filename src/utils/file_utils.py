"""File helpers: checksums and timestamped output paths."""
from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path


def file_sha256(path: Path, block_size: int = 1 << 20) -> str:
    """Stream the file so large inputs never need to fit in memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def detect_encoding(path: Path, candidates: tuple[str, ...] = ("utf-8-sig", "cp1252", "latin-1")) -> str:
    """Return the first encoding that decodes the whole file (streamed)."""
    import codecs

    for enc in candidates:
        decoder = codecs.getincrementaldecoder(enc)()
        try:
            with open(path, "rb") as fh:
                for block in iter(lambda: fh.read(1 << 20), b""):
                    decoder.decode(block)
                decoder.decode(b"", final=True)
            return enc
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Could not determine encoding for {path}")


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
