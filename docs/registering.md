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
  the registry. It overrides the canonical `{family}/{name}.{ext}` layout.

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

## Overwrite behaviour

`register` defaults to `overwrite=False` and refuses an existing destination. (`save`
defaults to `overwrite=True`.) With `archive_previous=True` the displaced file is moved into
`_archive/` rather than deleted — see [architecture.md](architecture.md).
