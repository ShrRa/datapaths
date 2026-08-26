# Changelog

## Unreleased

### Breaking

* **Naming conventions are no longer enforced.** `type="features"` no longer requires a name
  of at least four underscore-separated parts (`family_split_sourceVer_catVer`). Any name a
  filesystem can hold is accepted.
* **Layout no longer depends on type.** Every artifact is written flat as `{root}/{name}.{ext}`.
  `type="features"` used to nest artifacts under a family directory taken from the first
  underscore-separated part of the name. `type` now selects the root and nothing else; pass
  `relpath=` for a subdirectory.
* **`canonical_relpath` lost `layout` and `enforce_family_naming`.**
* **`force_flat_layout` removed** from `save` and `register`, and `--force-flat-layout` from
  the CLI. Every type is flat, so there was nothing left to force.
* **`TYPE_TO_ROOT` ships empty.** Five of its six entries mapped a type to a root of the same
  name, which the fallback already does; the sixth mapped `dataprep` to the `data` root. A
  project using `type="dataprep"` now needs a `dataprep` root, or must re-add the entry
  itself. The table remains as an escape hatch.
* **`save(overwrite=)` renamed to `save(overwrite_file=)`** (still `True` by default).
* **`register(overwrite=)` renamed to `register(overwrite_file=)`** (still `False` by
  default); `--overwrite` on the CLI is now `--overwrite-file`.
* **`register` no longer replaces a record silently.** Registering a name that is already in
  the registry warns and returns the existing record. Pass the new `overwrite_history=True`
  (`--overwrite-history`) to rewrite it. A deliberate rewrite now preserves the record's
  `archived` list, which `register` previously discarded.

#### Migrating

Registry records store their resolved `path`, so artifacts written under the old nested
layout keep resolving and `verify` keeps reporting `OK`. Only *new* saves land in the new
flat location, so a repository that predates this change will have files in two places until
its artifacts are re-saved. Nothing needs to be moved for the registry to stay correct.

### Added

* `validate_artifact_name` and `validate_relpath`, exported from the package. A name must be
  a single path component that cannot escape its root, and must not start with `.` or `~`;
  a `relpath` must be relative and must not traverse out of the root. Both run before
  anything touches the filesystem.

### Removed

* An unreachable format check in `write_tabular`, which `save` already dispatched around.

### Documentation

* Split the reference material out of `README.md` into `docs/`.
* Documented tag normalization (lowercased, comma-split) and the differing `overwrite_file`
  defaults between `save` and `register`, both of which were previously undocumented
  behavior.
