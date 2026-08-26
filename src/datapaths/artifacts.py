from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
import json
import pickle

from .exceptions import ArtifactError
from .hashing import short_hash

ArtifactType = Literal["data", "dataprep", "features", "predictions", "models", "misc"]
Format = Literal["parquet", "csv", "json", "bin", "pickle"]

TYPE_TO_ROOT: dict[str, str] = {
    "data": "data",
    "dataprep": "data",
    "features": "features",
    "predictions": "predictions",
    "models": "models",
    "misc": "misc",
}


def normalize_tag(v: Any) -> str:
    return str(v).strip().lower()


def normalize_tags(raw: Any) -> set[str]:
    if raw is None:
        return set()
    if isinstance(raw, (list, tuple, set)):
        return {normalize_tag(v) for v in raw if normalize_tag(v)}
    if isinstance(raw, str):
        return {normalize_tag(v) for v in raw.split(",") if normalize_tag(v)}
    return {normalize_tag(raw)} if normalize_tag(raw) else set()


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def canonical_relpath(
    name: str,
    fmt: Format,
    *,
    layout: Literal["one_level_family", "flat"] = "one_level_family",
    enforce_family_naming: bool = False,
) -> Path:
    parts = name.split("_")

    ext_map = {
        "parquet": "parquet",
        "csv": "csv",
        "json": "json",
        "bin": "bin",
        "pickle": "pkl",
    }
    ext = ext_map.get(fmt)
    if ext is None:
        raise ArtifactError(f"Unsupported format: {fmt}")

    filename = f"{name}.{ext}"

    if layout == "one_level_family":
        if enforce_family_naming and len(parts) < 4:
            raise ArtifactError(
                f"Name '{name}' must look like family_split_sourceVer_catVer "
                "(at least 4 underscore-separated parts)."
            )
        family = parts[0]
        return Path(family) / filename
    if layout == "flat":
        return Path(filename)

    raise ArtifactError(f"Unknown layout: {layout}")


def archive_path(root_abs: Path, relpath: Path, old_hash: str) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sh = short_hash(old_hash)
    stem, suffix = relpath.stem, relpath.suffix
    archived_name = f"{stem}__{ts}__{sh}{suffix}"
    return root_abs / "_archive" / relpath.parent / archived_name


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_bytes_atomic(path: Path, data: bytes) -> None:
    ensure_parent(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def write_json_atomic(path: Path, obj: Any) -> None:
    data = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
    write_bytes_atomic(path, data)


def write_pickle_atomic(path: Path, obj: Any) -> None:
    ensure_parent(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as f:
        pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(path)


def write_tabular(path: Path, obj: Any, fmt: Format) -> None:
    if not hasattr(obj, "to_parquet") and not hasattr(obj, "to_csv"):
        raise ArtifactError("Tabular save expects a pandas DataFrame (or compatible).")

    ensure_parent(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    if fmt == "parquet":
        obj.to_parquet(tmp, index=False)
    elif fmt == "csv":
        obj.to_csv(tmp, index=False)
    else:
        raise ArtifactError(f"Unsupported tabular format: {fmt}")
    tmp.replace(path)
