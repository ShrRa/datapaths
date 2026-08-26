# Architecture

## Modules

| Module | Responsibility |
|---|---|
| `datapaths.py` | The `Datapaths` class — resolve, save, register, list, print_paths, verify |
| `config.py` | Repo-root discovery, env overrides, roots file |
| `registry.py` | Read/write the registry YAML under a file lock |
| `artifacts.py` | Canonical relative paths, atomic writes, archiving |
| `hashing.py` | sha256 of files and bytes |
| `cli.py` | `datapaths` command |
| `exceptions.py` | `DatapathsError` and friends |

## Exceptions and warnings

All errors derive from `DatapathsError(RuntimeError)`:

* `ConfigError` — the config could not be loaded.
* `RegistryError` — the registry could not be read or written.
* `ArtifactError` — an artifact operation could not be carried out.

Two warning classes signal a partial success, never a failure:

* `ConfigWarning` — a config file was usable, but part of it was not.
* `ArtifactWarning` — an artifact operation succeeded, but not quite as asked.

## Durability guarantees

These are the invariants the design exists to hold. Each is covered by a test that fails
loudly if the protection is removed.

**Writes are atomic.** `save` serializes to a hidden staging file next to the destination
(`.{name}.{uuid}.new`), hashes it, and only then `shutil.move`s it into place. A `finally`
unlinks the staging file on any failure, so an interrupted write leaves neither a partial
artifact nor an accumulating pile of temp files in the data root.

**Registry updates take a lock.** Every mutation goes through
`update_registry_atomic`, which holds a `filelock` across the read-modify-write. Two
processes appending concurrently do not lose each other's entries.

**Overwrites archive, never delete.** Replacing a registered artifact moves the old file
into `_archive/` under a name carrying its UTC timestamp and short hash. The registry record
keeps the last five archived entries under an `archived` list.

**Registry paths are POSIX-style, always.** The registry is committed and read on other
machines; a Windows-written `bazin\f.parquet` would be one filename containing backslashes
anywhere else. `Path()` accepts forward slashes on every platform, so reading is unaffected.

## Skipping a no-op save

`save` compares both metadata and content hash against the existing record. If both match,
`on_same` decides:

* `"skip"` (default) — discard the staged file, warn, return the existing record.
* `"overwrite"` — rewrite in place without archiving.
* `"archive"` — archive the identical previous copy anyway.
