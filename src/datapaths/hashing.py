from __future__ import annotations

from pathlib import Path
import hashlib

BUF = 1024 * 1024  # 1 MiB

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(BUF)
            if not b:
                break
            h.update(b)
    return "sha256:" + h.hexdigest()

def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()

def short_hash(h: str, n: int = 10) -> str:
    # expects "sha256:<hex>"
    if ":" in h:
        h = h.split(":", 1)[1]
    return h[:n]
