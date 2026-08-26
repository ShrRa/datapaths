# datapaths

[![tests](https://github.com/ShrRa/datapaths/actions/workflows/ci.yml/badge.svg)](https://github.com/ShrRa/datapaths/actions/workflows/ci.yml)

A small package for managing datasets — paths, names, versions, provenance — in data
analysis and ML projects. It resolves root-relative paths and keeps a hashed artifact
registry.

**The idea:** your analysis repo should know only *which* dataset it uses, not *where on
this particular machine* that dataset sits. `datapaths` splits those apart. A committed
registry names artifacts and records their hashes; an uncommitted, machine-local roots file
says where the storage actually is. The same notebook then runs on your laptop and on a
shared cluster node without an edit.

```python
from datapaths import Datapaths

dp = Datapaths()

path = dp["features_train_dr2_v02"]      # -> absolute Path on this machine
df   = pd.read_parquet(path)             # datapaths resolves and records; you read

dp.save(df, name="features_train_dr2_v03", type="features", fmt="parquet",
        tags=["v03", "bazin"], updated_by="Jay Doe",
        notes="after renaming the columns")   # so colleagues know what this file is

dp.print_paths(tag="v03")                # inspect what accumulated during the project
```

---

## Install

Nothing is published to PyPI. Install from the repository.

```bash
# From a clone, for development -- edits are picked up immediately by every
# environment that installed it this way.
pip install -e /path/to/datapaths

# From git, for a server, CI, or a fresh machine.
pip install "datapaths @ git+https://github.com/ShrRa/datapaths.git@main"
```

Add the `tabular` extra if the project saves or loads parquet/csv artifacts:

```bash
pip install "datapaths[tabular] @ git+https://github.com/ShrRa/datapaths.git@main"
```

In a consuming project, put the git form in `pyproject.toml` and it resolves like any other
dependency. Pin `@main` to always track the tip, or `@v0.2.0` / `@<sha>` where a project
needs to be reproducible — you get versioning only where you actually want it.

---

## Setup

Two files, both under `configs/` in your project by default.

**`configs/roots.local.yaml`** — machine-local, **never committed**. Maps root names to
absolute directories:

```yaml
data: /mnt/scratch/var_stars/data
features: /mnt/scratch/var_stars/features
models: /mnt/scratch/var_stars/models
predictions: /mnt/scratch/var_stars/predictions
misc: /mnt/scratch/var_stars/misc
```

**`configs/artifacts_registry.yaml`** — committed. One record per artifact: its path under a
root, format, sha256, tags, notes, timestamps. This is the file that makes an artifact
reference mean the same thing to two people. You never write it by hand — `save` and
`register` maintain it.

Both are found relative to the repository root, discovered by walking up from the current
working directory looking for `pyproject.toml` or `.git`. If that guess is ever wrong (a
notebook or a scheduled job started elsewhere), set `DATAPATHS_REPO_ROOT` — see
[docs/configuration.md](docs/configuration.md).

---

## Usage

There are only a handful of things to know.

### Resolve a path

Subscripting takes either an artifact name or a root name and gives you an absolute `Path`:

```python
dp = Datapaths()

dp["features_train_dr2_v02"]   # an artifact -> /mnt/scratch/.../features_train_dr2_v02.parquet
dp["features"]                 # a root      -> /mnt/scratch/var_stars/features
dp["root_features"]            # force the root, even if an artifact shares the name
```

A missing key raises `KeyError`, and if you only got the capitalization wrong it says so.

### Read an artifact's metadata

```python
dp.get("features_train_dr2_v02")                    # the whole record as a dict
dp.get("features_train_dr2_v02", field="notes")     # one field
dp.get("features_train_dr2_v02", field="hash")
dp.get("nope", default={})                          # no exception, unlike dp["nope"]
```

### Save an object

`save` serializes, writes atomically, hashes the result and updates the registry:

```python
dp.save(df, name="features_train_dr2_v03", type="features", fmt="parquet",
        tags=["v03", "bazin"],
        inputs=["lightcurves_dr2"],       # provenance: what this was built from
        notes="dropped the saturated epochs",
        updated_by="Jay Doe")
```

Formats it can write: `parquet`, `csv`, `json`, `bin` (bytes), `pickle`.

Saving over an existing artifact archives the old file rather than deleting it. Saving
something byte-identical with identical metadata is skipped with a warning.

> **Naming note:** `type="features"` nests files under a family directory and requires a
> name with at least four underscore-separated parts
> (`family_split_sourceVer_catVer`). Every other type is written flat as `{name}.{ext}` with
> no name check. Pass `force_flat_layout=True` or an explicit `relpath=` to opt out. See
> [docs/artifact-types.md](docs/artifact-types.md).

### Register a file that already exists

`register` does not serialize anything — it records a path, a hash and metadata — so it
accepts **any format label**. A FITS cube, an HDF5 model or a PDF works:

```python
dp.register(name="lc_cube", type="misc", fmt="fits",
            src_path="/mnt/scratch/misc/cubes/lc.fits")

dp["lc_cube"]                   # now resolves like anything else
```

By default the file is adopted where it lies (it must already be under one of the roots).
Pass `copy_into_canonical=True` to copy it into the canonical layout instead — details in
[docs/registering.md](docs/registering.md).

### Find things

`list` returns matching records as dicts, newest first. All filters combine with AND:

```python
dp.list(type="features")
dp.list(tag=["v03", "bazin"])       # both tags required
dp.list(name="train")               # substring match on the name
dp.list(text="saturated")           # substring match on name or notes
```

### Print a table

`print_paths` takes the same filters and prints an aligned table with resolved absolute
paths — the quickest way to see what a project has accumulated:

```python
dp.print_paths(type="features")
dp.print_paths(tag="v03", columns=["name", "path", "notes"])
```

```
name                     | path                                        | tags
-------------------------+---------------------------------------------+-----------
features_train_dr2_v03   | /mnt/scratch/var_stars/features/features/... | v03,bazin
features_test_dr2_v03    | /mnt/scratch/var_stars/features/features/... | v03,bazin
```

Default columns are `name`, `path`, `tags`, `type`, `updated at`; pass `columns=` to pick
any fields from the record.

### Check nothing drifted

`verify` re-hashes what is on disk against what the registry claims, so an artifact that was
regenerated without being re-registered is caught rather than quietly used:

```python
dp.verify(type="features")
dp.verify(names=["lc_cube"])
```

Each result carries a `status` of `OK`, `MISSING`, `HASH_MISMATCH`, or `ROOT_MISSING`.

### Add a new kind of artifact

Add one line to `roots.local.yaml` — there is no command, because the file is machine-local
by design:

```yaml
plots: /mnt/scratch/var_stars/plots     # new
```

A type with no built-in mapping falls back to a root of the same name, so `type="plots"`
works immediately with no code change:

```python
dp.save(png_bytes, name="lc_grid", type="plots", fmt="bin")
dp.list(type="plots")
```

---

## CLI

The package is primarily meant to be used from Python, but a `datapaths` command is
installed for quick checks from a shell:

```bash
datapaths list --type features --tag v02
datapaths list --tag v02,bazin            # comma means AND: both tags required
datapaths verify --type features          # re-hash and report drift
datapaths register --name my_table --type features --file /tmp/x.parquet --fmt parquet
```

Output is JSON. The CLI is not stricter than the API — `--fmt fits` works too.

---

## What it guarantees

Artifact writes go through a staging file and an atomic move, and registry updates take a
`filelock`, so a crashed or concurrent run does not leave a half-written artifact or a
corrupted registry. Overwriting a registered artifact moves the old file into `_archive/`
under a name carrying its timestamp and short hash rather than deleting it. Details in
[docs/architecture.md](docs/architecture.md).

## Documentation

| Page | Contents |
|---|---|
| [docs/configuration.md](docs/configuration.md) | Config files, env overrides, precedence, collision warnings |
| [docs/artifact-types.md](docs/artifact-types.md) | Types, roots, and the features naming convention |
| [docs/registering.md](docs/registering.md) | `register` vs `save`, `src_path` vs `relpath` |
| [docs/architecture.md](docs/architecture.md) | Modules, atomicity, locking, archiving |

## Contributing

```bash
pip install -e ".[tabular,dev]"
pytest
```

CI runs the suite on Linux, macOS and Windows against Python 3.10, 3.12 and 3.14, plus one
job without the `tabular` extra. See [AGENTS.md](AGENTS.md) for the invariants to preserve.

## License

MIT.
