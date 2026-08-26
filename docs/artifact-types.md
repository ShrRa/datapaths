# Artifact types and roots

## Adding a root

There is no command for this — a root is one line of YAML, and `roots.local.yaml` is
uncommitted and machine-local by design, so it is meant to be edited by hand.

Say you want somewhere to put plots. Create the directory, add it to the roots file:

```yaml
data: /mnt/scratch/var_stars/data
features: /mnt/scratch/var_stars/features
plots: /mnt/scratch/var_stars/plots     # new
```

and that is the whole setup. A type with no entry in `TYPE_TO_ROOT` falls back to a root of
the same name, so the new root is usable immediately:

```python
dp = Datapaths()
dp["plots"]                                              # the directory itself
dp.save(png_bytes, name="lc_grid", type="plots", fmt="bin")
dp.list(type="plots")
dp.verify(type="plots")
```

If the type has no matching root, the error names the file to edit and lists the types and
roots it does know about.

## How a root is chosen

`Datapaths` picks the storage root for an artifact in this order:

1. An explicit `root_key=` argument.
2. The built-in `TYPE_TO_ROOT` mapping.
3. A root named after the type itself.

## `type` is not a closed vocabulary

The `ArtifactType` `Literal` names the built-in types for editors and type checkers:

```python
ArtifactType = Literal["data", "dataprep", "features", "predictions", "models", "misc"]
```

It is **never enforced at runtime**, and any string works.

`TYPE_TO_ROOT` exists only for types whose root is *not* a root of the same name (`dataprep`
stores under `data`), and it takes precedence over the fallback — so defining a `dataprep`
root will not move existing `dataprep` artifacts.

## Family nesting is features-only

An artifact of any type other than `features` is written flat as `{name}.{ext}` directly
under its root. Only `type="features"` nests under `{family}/`, where the family is the part
of the name before the first underscore.

`features` also **enforces a naming convention**: the name must have at least four
underscore-separated parts, `family_split_sourceVer_catVer`.

```python
dp.save(df, name="features_train_dr2_v03", type="features", fmt="parquet")
# -> <features root>/features/features_train_dr2_v03.parquet

dp.save(df, name="features_train_v03", type="features", fmt="parquet")
# ArtifactError: Name 'features_train_v03' must look like family_split_sourceVer_catVer
#                (at least 4 underscore-separated parts).
```

Two ways out if that layout is not what you want:

* `force_flat_layout=True` — write flat and skip the name check.
* `relpath="..."` — say exactly where the file should sit inside the root.
