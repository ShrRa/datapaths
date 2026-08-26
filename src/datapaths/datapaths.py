from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Literal
import os
import shutil
import uuid
import warnings

from .artifacts import (
    ArtifactType,
    Format,
    TYPE_TO_ROOT,
    archive_path,
    canonical_relpath,
    ensure_parent,
    normalize_tags,
    now_iso,
    write_bytes_atomic,
    write_json_atomic,
    write_pickle_atomic,
    write_tabular,
)
from .config import DatapathsConfig, load_config, load_roots
from .exceptions import ArtifactError, ArtifactWarning
from .hashing import sha256_file
from .registry import Registry, read_registry, update_registry_atomic


class Datapaths:
    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        roots_file: str | Path | None = None,
        registry_file: str | Path | None = None,
    ) -> None:
        """Leave the paths as None to let config resolution decide.

        None means "env var if set, else the configs/ default"; passing a value
        here pins it and the environment is ignored. See datapaths.config.
        """
        self._repo_root = repo_root
        self._roots_file = roots_file
        self._registry_file = registry_file

        self.cfg: DatapathsConfig
        self.roots: dict[str, Path]
        self.catalogues: dict[str, dict[str, Any]]
        self.reload()

    def reload(self) -> None:
        self.cfg = load_config(
            repo_root=self._repo_root,
            roots_file=self._roots_file,
            registry_file=self._registry_file,
        )
        self.roots = load_roots(self.cfg)
        self.catalogues = read_registry(self.cfg.registry_file).artifacts

    def _missing_key(self, key: str, *, roots_only: bool = False) -> KeyError:
        """Build the KeyError, naming a case-insensitive near miss if there is one.

        Root names are matched exactly and tags are lowercased everywhere else,
        so getting the case wrong is the likeliest way to land here -- and a
        bare KeyError leaves the caller comparing strings by eye.
        """
        candidates = list(self.roots) if roots_only else [*self.roots, *self.catalogues]
        folded = key.casefold()
        near = [c for c in candidates if c.casefold() == folded]
        if near:
            return KeyError(f"{key!r}; did you mean {near[0]!r}? (matching is case-sensitive)")
        return KeyError(key)

    def __getitem__(self, key: str) -> Path:
        if key.startswith("root_"):
            rk = key[5:]
            if rk not in self.roots:
                raise self._missing_key(rk, roots_only=True)
            return self.roots[rk]

        if key in self.roots:
            return self.roots[key]

        rec = self.catalogues.get(key)
        if rec is None:
            raise self._missing_key(key)
        return self._absolute_from_record(rec)

    def get(self, key: str, default: Any = None, *, field: str | None = None) -> Any:
        rec = self.catalogues.get(key)
        if rec is None:
            return default

        if field is None:
            return dict(rec)
        if field in ("path_abs", "absolute_path"):
            return str(self._absolute_from_record(rec))
        return rec.get(field, default)

    def _absolute_from_record(self, rec: dict[str, Any]) -> Path:
        rk = rec.get("root")
        rel = rec.get("path")
        if rk not in self.roots:
            raise ArtifactError(f"Root key '{rk}' from registry is missing in roots.local.yaml")
        if rel is None:
            raise ArtifactError("Registry record has no path field")
        return (self.roots[rk] / Path(str(rel))).resolve()

    def _resolve_root(self, type: ArtifactType | str, root_key: str | None) -> str:
        """Pick the storage root for an artifact.

        Order: an explicit root_key, then the built-in TYPE_TO_ROOT mapping,
        then a root named after the type itself. The last one is what makes a
        new kind of artifact a one-line change: declaring `plots:` in the roots
        file is enough for type="plots" to work, with no edit here. TYPE_TO_ROOT
        still wins, so "dataprep" keeps landing under the "data" root even for
        someone who has also defined a "dataprep" root.
        """
        rk = root_key or TYPE_TO_ROOT.get(type) or (type if type in self.roots else None)
        if not rk:
            known = ", ".join(sorted(set(TYPE_TO_ROOT) | set(self.roots))) or "none"
            raise ArtifactError(
                f"No root configured for type '{type}'. Pass root_key=..., or add "
                f"a root named '{type}' to {self.cfg.roots_file}. "
                f"Known types and roots: {known}."
            )
        if rk not in self.roots:
            raise ArtifactError(
                f"Root key '{rk}' not present in {self.cfg.roots_file}. "
                f"Available: {', '.join(sorted(self.roots)) or 'none'}."
            )
        return rk

    def save(
        self,
        obj: Any,
        *,
        name: str,
        type: ArtifactType | str,
        fmt: Format = "parquet",
        relpath: str | None = None,
        root_key: str | None = None,
        tags: list[str] | None = None,
        inputs: list[str] | None = None,
        notes: str | None = None,
        updated_by: str | None = None,
        force_flat_layout: bool = False,
        overwrite: bool = True,
        archive_previous: bool = True,
        on_same: Literal["skip", "overwrite", "archive"] = "skip",
    ) -> dict[str, Any]:
        self.reload()
        rk = self._resolve_root(type, root_key)

        layout: Literal["one_level_family", "flat"] = (
            "flat" if (force_flat_layout or type != "features") else "one_level_family"
        )
        rel = Path(relpath) if relpath else canonical_relpath(
            name,
            fmt,
            layout=layout,
            enforce_family_naming=(type == "features" and layout == "one_level_family"),
        )
        abs_path = self.roots[rk] / rel

        existing = self.catalogues.get(name, {})
        wanted_tags = sorted(normalize_tags(tags))
        wanted_inputs = list(inputs or [])
        wanted_notes = notes or ""
        same_metadata = bool(existing) and (
            existing.get("type") == type
            and existing.get("root") == rk
            and existing.get("path") == rel.as_posix()
            and existing.get("format") == fmt
            and sorted(normalize_tags(existing.get("tags"))) == wanted_tags
            and list(existing.get("inputs", [])) == wanted_inputs
            and (existing.get("notes") or "") == wanted_notes
        )

        stage_path = abs_path.with_name(f".{abs_path.name}.{uuid.uuid4().hex}.new")
        if fmt in ("parquet", "csv"):
            write_tabular(stage_path, obj, fmt)
        elif fmt == "json":
            write_json_atomic(stage_path, obj)
        elif fmt == "pickle":
            write_pickle_atomic(stage_path, obj)
        elif fmt == "bin":
            if not isinstance(obj, (bytes, bytearray)):
                raise ArtifactError("bin format expects bytes/bytearray")
            write_bytes_atomic(stage_path, bytes(obj))
        else:
            raise ArtifactError(f"Unsupported format: {fmt}")

        new_hash = sha256_file(stage_path)
        archived_rec: dict[str, Any] | None = None
        try:
            if abs_path.exists():
                old_hash = sha256_file(abs_path)
                unchanged = same_metadata and old_hash == new_hash

                if unchanged and on_same == "skip":
                    stage_path.unlink(missing_ok=True)
                    warnings.warn(
                        f"Artifact '{name}' unchanged (same metadata and hash); skipping save.",
                        stacklevel=2,
                    )
                    self.reload()
                    return dict(existing) if existing else {
                        "type": type,
                        "root": rk,
                        "path": rel.as_posix(),
                        "format": fmt,
                        "hash": old_hash,
                        "tags": wanted_tags,
                        "inputs": wanted_inputs,
                        "notes": wanted_notes,
                    }

                if not overwrite and not unchanged:
                    raise ArtifactError(f"Artifact already exists: {abs_path}")

                do_archive = (
                    archive_previous and (not unchanged or on_same == "archive")
                )
                if do_archive:
                    arch_path = archive_path(self.roots[rk], rel, old_hash)
                    ensure_parent(arch_path)
                    shutil.move(str(abs_path), str(arch_path))
                    archived_rec = {
                        "archived_at": now_iso(),
                        "hash": old_hash,
                        "path": arch_path.relative_to(self.roots[rk]).as_posix(),
                        "notes": "auto-archived on overwrite",
                    }
                else:
                    abs_path.unlink()

            ensure_parent(abs_path)
            shutil.move(str(stage_path), str(abs_path))
        finally:
            stage_path.unlink(missing_ok=True)

        record = {
            "type": type,
            "root": rk,
            # Recorded POSIX-style, always. The registry is committed and read
            # on other machines; a Windows-written 'bazin\\f.parquet' would be
            # one filename containing backslashes anywhere else. Path() accepts
            # forward slashes on every platform, so reading stays unchanged.
            "path": rel.as_posix(),
            "format": fmt,
            "updated_at": now_iso(),
            "updated_by": updated_by or os.environ.get("USER") or os.environ.get("USERNAME") or "unknown",
            "hash": new_hash,
            "tags": wanted_tags,
            "inputs": wanted_inputs,
            "notes": wanted_notes,
        }

        def _upd(reg: Registry) -> Registry:
            a = reg.artifacts.get(name, {})
            archived = list(a.get("archived", [])) if isinstance(a.get("archived", []), list) else []
            if archived_rec:
                archived.insert(0, archived_rec)
                archived = archived[:5]
            a.update(record)
            if archived:
                a["archived"] = archived
            reg.artifacts[name] = a
            return reg

        update_registry_atomic(self.cfg.registry_file, _upd)
        self.reload()
        return record

    def register(
        self,
        *,
        name: str,
        type: ArtifactType | str,
        src_path: str,
        fmt: Format | str,
        root_key: str | None = None,
        relpath: str | None = None,
        tags: list[str] | None = None,
        inputs: list[str] | None = None,
        notes: str | None = None,
        updated_by: str | None = None,
        force_flat_layout: bool = False,
        copy_into_canonical: bool = False,
        overwrite: bool = False,
        archive_previous: bool = True,
    ) -> dict[str, Any]:
        self.reload()
        rk = self._resolve_root(type, root_key)

        src = Path(src_path).expanduser().resolve()
        if not src.exists():
            raise ArtifactError(f"Source path does not exist: {src}")

        if copy_into_canonical:
            layout: Literal["one_level_family", "flat"] = (
                "flat" if (force_flat_layout or type != "features") else "one_level_family"
            )
            # A format with no saver still names a real file: borrow the
            # source's own suffix so the canonical name keeps matching it.
            rel = Path(relpath) if relpath else canonical_relpath(
                name,
                fmt,
                layout=layout,
                enforce_family_naming=(type == "features" and layout == "one_level_family"),
                fallback_ext=src.suffix,
            )
            dst = self.roots[rk] / rel

            if dst.exists():
                if not overwrite:
                    raise ArtifactError(f"Destination exists: {dst}")
                old_hash = sha256_file(dst)
                if archive_previous:
                    arch_path = archive_path(self.roots[rk], rel, old_hash)
                    ensure_parent(arch_path)
                    shutil.move(str(dst), str(arch_path))
                else:
                    dst.unlink()
            ensure_parent(dst)
            shutil.copy2(str(src), str(dst))
            final_path = dst
        else:
            # Registering in place: the file stays where it is, so its own
            # location IS the record. No canonical path is built here, which is
            # also why a format this package cannot write is fine -- nothing
            # needs to know an extension for it.
            if relpath is not None:
                warnings.warn(
                    f"relpath={relpath!r} is ignored when registering in place: "
                    f"'{name}' is recorded where the file already sits. Pass "
                    f"copy_into_canonical=True to move it to that path instead.",
                    ArtifactWarning,
                    stacklevel=2,
                )
            final_path = src
            try:
                rel = final_path.relative_to(self.roots[rk])
            except Exception as e:
                raise ArtifactError(
                    f"Source file is not under the '{rk}' root "
                    f"({self.roots[rk]}): {src}. Use copy_into_canonical=True "
                    f"to copy it in, or adjust {self.cfg.roots_file}."
                ) from e

        h = sha256_file(final_path)

        record = {
            "type": type,
            "root": rk,
            # Recorded POSIX-style, always. The registry is committed and read
            # on other machines; a Windows-written 'bazin\\f.parquet' would be
            # one filename containing backslashes anywhere else. Path() accepts
            # forward slashes on every platform, so reading stays unchanged.
            "path": rel.as_posix(),
            "format": fmt,
            "updated_at": now_iso(),
            "updated_by": updated_by or os.environ.get("USER") or os.environ.get("USERNAME") or "unknown",
            "hash": h,
            "tags": sorted(normalize_tags(tags)),
            "inputs": inputs or [],
            "notes": notes or "",
        }

        def _upd(reg: Registry) -> Registry:
            reg.artifacts[name] = record
            return reg

        update_registry_atomic(self.cfg.registry_file, _upd)
        self.reload()
        return record

    def list(
        self,
        *,
        name: str | None = None,
        type: ArtifactType | str | None = None,
        tag: str | list[str] | None = None,
        text: str | None = None,
    ) -> list[dict[str, Any]]:
        wanted_name = name.strip().lower() if name else None
        # normalize_tags splits a comma string, so "v02,bazin" filters on both.
        # Every write path normalizes the same way, which means no stored tag
        # can contain a comma -- treating the query as one literal tag could
        # only ever match nothing.
        wanted_tags = normalize_tags(tag)

        out: list[dict[str, Any]] = []
        for art_name, rec in self.catalogues.items():
            if wanted_name and wanted_name not in art_name.lower():
                continue
            if type and rec.get("type") != type:
                continue
            rec_tags = normalize_tags(rec.get("tags"))
            if wanted_tags and not wanted_tags.issubset(rec_tags):
                continue
            if text:
                blob = (art_name + " " + str(rec.get("notes", ""))).lower()
                if text.lower() not in blob:
                    continue
            out.append({"name": art_name, **rec})

        out.sort(key=lambda r: r.get("updated_at", ""), reverse=True)
        return out

    def print_paths(
        self,
        *,
        columns: list[str] | None = None,
        name: str | None = None,
        type: ArtifactType | str | None = None,
        tag: str | list[str] | None = None,
        text: str | None = None,
    ) -> None:
        rows = self.list(name=name, type=type, tag=tag, text=text)

        selected = columns or ["name", "path", "tags", "type", "updated at"]
        aliases = {"updated at": "updated_at", "updated_at": "updated_at"}
        normalized = [aliases.get(c, c) for c in selected]

        rendered_rows: list[dict[str, Any]] = []
        for row in rows:
            rk = row.get("root")
            rel = row.get("path")
            if rk in self.roots and rel is not None:
                abs_path = str((self.roots[rk] / Path(str(rel))).resolve())
            else:
                abs_path = str(rel or "")

            rendered = {**row, "path": abs_path}
            rendered_rows.append(rendered)

        def _cell(rec: dict[str, Any], col: str) -> str:
            v = rec.get(col, "")
            if col == "tags" and isinstance(v, list):
                return ",".join(str(x) for x in v)
            if isinstance(v, list):
                return ",".join(str(x) for x in v)
            return str(v)

        matrix = [[_cell(rec, col) for col in normalized] for rec in rendered_rows]

        widths = [len(h) for h in selected]
        for row in matrix:
            for i, val in enumerate(row):
                widths[i] = max(widths[i], len(val))

        def _fmt_line(vals: list[str]) -> str:
            return " | ".join(v.ljust(widths[i]) for i, v in enumerate(vals))

        print(_fmt_line(selected))
        print("-+-".join("-" * w for w in widths))
        for row in matrix:
            print(_fmt_line(row))

    def verify(
        self,
        *,
        names: Iterable[str] | None = None,
        type: ArtifactType | str | None = None,
        tag: str | list[str] | None = None,
    ) -> list[dict[str, Any]]:
        wanted = set(names) if names else None
        wanted_tags = normalize_tags(tag)
        results: list[dict[str, Any]] = []

        for name, rec in self.catalogues.items():
            if wanted is not None and name not in wanted:
                continue
            if type and rec.get("type") != type:
                continue
            if wanted_tags and not wanted_tags.issubset(normalize_tags(rec.get("tags"))):
                continue

            rk = rec.get("root")
            rel = rec.get("path")
            expected = rec.get("hash")
            if rk not in self.roots:
                results.append({"name": name, "status": "ROOT_MISSING", "root": rk, "path": rel})
                continue

            abs_path = self.roots[rk] / Path(str(rel))
            if not abs_path.exists():
                results.append({"name": name, "status": "MISSING", "path": str(abs_path)})
                continue

            actual = sha256_file(abs_path)
            if expected != actual:
                results.append(
                    {
                        "name": name,
                        "status": "HASH_MISMATCH",
                        "path": str(abs_path),
                        "expected": expected,
                        "actual": actual,
                    }
                )
            else:
                results.append({"name": name, "status": "OK", "path": str(abs_path)})
        return results
