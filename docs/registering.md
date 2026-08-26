# Registering files `datapaths` cannot write

`save` serializes, so it only accepts `parquet`, `csv`, `json`, `bin`, `pickle`.

`register` does not serialize anything — it records a path, a hash and metadata — so it
takes **any format label**. A FITS cube, an HDF5 model or a PDF is registered, resolved and
verified like anything else:

```python
dp.register(name="lc_cube", type="misc", src_path="/mnt/scratch/misc/cubes/lc.fits",
            fmt="fits")
dp["lc_cube"]                   # resolves
dp.verify(names=["lc_cube"])    # re-hashes, reports drift
```

`datapaths register --fmt fits` works too; the CLI is not stricter than the API.

## `src_path` vs `relpath`

They are the two ends of a copy, and which one matters depends on `copy_into_canonical`:

* **`src_path`** — where the file is *now*. Absolute, or relative to your cwd. It must
  exist, and it is never moved.
* **`relpath`** — where the file should sit *inside the root*, and the `path` recorded in
  the registry. It overrides the canonical `{name}.{ext}` layout, and is the way to
  place an artifact in a subdirectory.

|                                      | `relpath` given                | no `relpath`                             |
| ------------------------------------ | ------------------------------ | ---------------------------------------- |
| **in place** (the default)           | ignored, with a warning        | path is the file's existing location     |
| **`copy_into_canonical=True`**       | the destination, verbatim      | destination from `canonical_relpath`     |

### Registering in place (the default)

Adopts the file exactly where it lies, so the record simply describes it — which is why no
extension has to be known, and why any format works. The file must already be under one of
the roots.

### Registering with `copy_into_canonical=True`

Copies the file to a canonical name, so an extension *is* needed:

* For a format with no saver, the extension is taken from the source file's own suffix, so
  `incoming.fits` registered as `cube` becomes `cube.fits`.
* A known format still uses the standard mapping (`pickle` → `.pkl`) rather than the suffix.
* If the format is unknown *and* the source has no suffix, nothing can name the destination
  and it is refused — pass `relpath` to say what you want.

`relpath` must be relative and must not escape the root; `../` is refused.

## Overwrite behaviour

Two different things can be in the way of a `register`, so there are two flags.

### `overwrite_file` — bytes on disk

Only relevant with `copy_into_canonical=True`, where a file may already occupy the
destination.

|  | default | an existing destination file |
|---|---|---|
| `register` | `overwrite_file=False` | `ArtifactError` |
| `save` | `overwrite_file=True` | replaced |

The defaults differ deliberately. `save` exists to write new versions of an artifact, so
replacing the previous one is the normal case. `register` adopts files it did not create, so
replacing one should be a decision the caller makes out loud.

With `archive_previous=True` (the default) the displaced file is moved into `_archive/`
rather than deleted — see [architecture.md](architecture.md).

### `overwrite_history` — the registry record

If the name is **already registered**, `register` warns and does nothing:

```python
dp.register(name="lc_cube", type="misc", fmt="fits", src_path=".../lc.fits")
dp.register(name="lc_cube", type="misc", fmt="fits", src_path=".../lc.fits")
# ArtifactWarning: 'lc_cube' is already registered (path: cubes/lc.fits); skipping.
#                  Pass overwrite_history=True to replace the record.
```

The warning is not pedantry: a record carries an `archived` list, which is the one piece of
provenance that cannot be reconstructed from the files on disk. Pass `overwrite_history=True`
to rewrite the record deliberately — the archived list is carried across either way.

```python
dp.register(name="lc_cube", type="misc", fmt="fits",
            src_path=".../lc.fits", notes="re-hashed after the pipeline rerun",
            overwrite_history=True)
```

`save` has no equivalent flag: writing a new version of an artifact is the whole point of it,
and it already merges rather than replaces.
