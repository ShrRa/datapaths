# Artifact types and roots

## What `type` does

A `type` selects **which root** an artifact is stored in, and nothing else. It has no effect
on the path inside that root, and it is not validated against any list.

## Adding a root

There is no command for this — a root is one line of YAML, and `roots.local.yaml` is
uncommitted and machine-local by design, so it is meant to be edited by hand.

Say you want somewhere to put plots. Create the directory, add it to the roots file:

```yaml
data: /mnt/scratch/var_stars/data
features: /mnt/scratch/var_stars/features
plots: /mnt/scratch/var_stars/plots     # new
```

and that is the whole setup. A type resolves to a root of the same name, so the new root is
usable immediately:

```python
dp = Datapaths()
dp["plots"]                                              # the directory itself
dp.save(png_bytes, name="lc_grid", type="plots", fmt="bin")
dp.list(type="plots")
dp.verify(type="plots")
```

If the type has no matching root, the error names the file to edit and lists the roots it
does know about.

## How a root is chosen

1. An explicit `root_key=` argument.
2. The `TYPE_TO_ROOT` mapping.
3. A root named after the type itself.

`TYPE_TO_ROOT` **ships empty**, so in practice step 3 does all the work. It exists as an
escape hatch for a project that needs a type whose root has a different name:

```python
from datapaths.artifacts import TYPE_TO_ROOT
TYPE_TO_ROOT["dataprep"] = "data"     # dataprep artifacts land in the data root
```

It takes precedence over the same-name fallback, so an entry here wins even if a root of the
type's own name also exists.

## `type` is not a closed vocabulary

The `ArtifactType` `Literal` names some common types for editors and type checkers:

```python
ArtifactType = Literal["data", "dataprep", "features", "predictions", "models", "misc"]
```

It is **never enforced at runtime**, and any string works. It is a hint about what people
usually pick, not a list of what is allowed.

## Layout

Every artifact is written flat, directly under its root:

```
{root}/{name}.{ext}
```

There are no per-type layouts. `type="features"` used to nest artifacts under a family
directory taken from the first underscore-separated part of the name, and to require names
of at least four such parts; both are gone. Pass `relpath=` when you want a specific
arrangement:

```python
dp.save(df, name="bazin_train", type="features", relpath="bazin/train.parquet")
```

## Name rules

The one thing a name must satisfy is that it can safely become a filename under a root. A
name is rejected if it:

* is empty or only whitespace,
* contains `/` or `\` — a name is one path component; use `relpath=` to nest,
* is `.` or `..`, or traverses out of the root,
* starts with `.` — hidden files have no place in a provenance registry,
* starts with `~`, which some tools expand to a home directory,
* contains a control character.

Everything else is allowed, including short names, names with no underscores, and names with
dots or dashes inside them. Naming conventions are the project's business, not the library's.
