from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal
import json
import pickle

from .exceptions import ArtifactError
from .hashing import short_hash

# The built-in types, not the permitted ones: this is a hint, never enforced at
# runtime. Any string works as a type, and one naming a root in the roots file
# resolves to it without an entry in TYPE_TO_ROOT below.
ArtifactType = Literal["data", "dataprep", "features", "predictions", "models", "misc"]
Format = Literal["parquet", "csv", "json", "bin", "pickle"]

# Types whose root is *not* a root of the same name. Empty by design: a type
# resolves to the root it is named after, so this table is an escape hatch for
# a project that needs an exception, not a vocabulary the package ships. It
# still takes precedence over the same-name fallback when it is populated.
TYPE_TO_ROOT: dict[str, str] = {}


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


def validate_artifact_name(name: str) -> str:
    """Refuse a name that cannot safely become a filename.

    This is the only rule the package imposes on names. It does not care how
    many underscores a name has or what it starts with -- naming conventions
    belong to the project, not to the library. What it does care about is that
    a name becomes a path component under a root, so it must not be able to
    reach outside one or split into several.
    """
    if not isinstance(name, str) or not name.strip():
        raise ArtifactError("Artifact name is empty.")

    if any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
        raise ArtifactError(
            f"Artifact name contains a control character: {name!r}."
        )

    if "/" in name or "\\" in name:
        raise ArtifactError(
            f"Artifact name contains a path separator: {name!r}. A name is one "
            f"path component; pass relpath= to place the file in a subdirectory."
        )

    if name in (".", ".."):
        raise ArtifactError(f"Artifact name is not a usable filename: {name!r}.")

    if name.startswith("."):
        raise ArtifactError(
            f"Artifact name starts with a dot: {name!r}. Hidden files have no "
            f"place in a provenance registry."
        )

    if name.startswith("~"):
        raise ArtifactError(
            f"Artifact name starts with '~': {name!r}, which some tools expand "
            f"to a home directory."
        )

    return name


def validate_relpath(relpath: str | Path) -> Path:
    """Refuse a relpath that is absolute or escapes its root.

    Checked lexically, on the path as written: the root it will be joined to
    may not exist yet, and a relpath is a statement about layout rather than
    about what is currently on disk.
    """
    rel = Path(relpath)
    if not str(relpath).strip():
        raise ArtifactError("relpath is empty.")
    if rel.is_absolute():
        raise ArtifactError(f"relpath must be relative, got {relpath!r}.")

    parts: list[str] = []
    for part in rel.parts:
        if part == "..":
            if not parts:
                raise ArtifactError(
                    f"relpath points outside its root: {relpath!r}."
                )
            parts.pop()
        elif part not in ("", "."):
            parts.append(part)

    if not parts:
        raise ArtifactError(f"relpath points outside its root: {relpath!r}.")
    return rel


def canonical_relpath(
    name: str,
    fmt: Format | str,
    *,
    fallback_ext: str | None = None,
) -> Path:
    """Build the canonical path for an artifact: {name}.{ext}, flat.

    One rule for every type. `type` selects which root an artifact lands in and
    nothing else about its path -- it used to also decide the shape of the path
    inside that root, which made "features" behave unlike every other type for
    no reason a user could see.

    `fallback_ext` supplies an extension for a format this package cannot
    write, which is how register() adopts a FITS cube or an HDF5 model: the
    format has no saver, but the file on disk already carries a suffix that
    says what it is, and the canonical name should keep matching it.
    """
    validate_artifact_name(name)

    ext_map = {
        "parquet": "parquet",
        "csv": "csv",
        "json": "json",
        "bin": "bin",
        "pickle": "pkl",
    }
    ext = ext_map.get(fmt) or (fallback_ext or "").lstrip(".")
    if not ext:
        raise ArtifactError(
            f"Unsupported format: {fmt}. Formats this package can write are "
            f"{', '.join(sorted(ext_map))}; any other format can still be "
            f"registered, but the file needs a suffix to name it by, or an "
            f"explicit relpath."
        )

    return Path(f"{name}.{ext}")


def archive_path(root_abs: Path, relpath: Path, old_hash: str) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sh = short_hash(old_hash)
    stem, suffix = relpath.stem, relpath.suffix
    archived_name = f"{stem}__{ts}__{sh}{suffix}"
    return root_abs / "_archive" / relpath.parent / archived_name


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def _staged(path: Path) -> Iterator[Path]:
    """Yield a sibling temp path, then move it onto `path`.

    A serialization that fails part-way -- a disk filling up, a column pyarrow
    cannot encode, a SIGINT -- must not leave its partial output behind. The
    caller writes to the yielded path and this cleans it up on the way out,
    whether the write succeeded or raised.
    """
    ensure_parent(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        yield tmp
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def write_bytes_atomic(path: Path, data: bytes) -> None:
    with _staged(path) as tmp:
        tmp.write_bytes(data)


def write_json_atomic(path: Path, obj: Any) -> None:
    data = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
    write_bytes_atomic(path, data)


def write_pickle_atomic(path: Path, obj: Any) -> None:
    with _staged(path) as tmp:
        with tmp.open("wb") as f:
            pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)


def write_tabular(path: Path, obj: Any, fmt: Format) -> None:
    if not hasattr(obj, "to_parquet") and not hasattr(obj, "to_csv"):
        raise ArtifactError("Tabular save expects a pandas DataFrame (or compatible).")

    with _staged(path) as tmp:
        if fmt == "parquet":
            obj.to_parquet(tmp, index=False)
        else:
            obj.to_csv(tmp, index=False)
