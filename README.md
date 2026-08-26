# datapaths

Root-relative path resolution and a small hashed artifact registry, for data-analysis
repositories where the data does not live next to the code.

The problem it solves: analysis code needs to say *which* dataset it wants, not *where on
this particular machine* that dataset sits. `datapaths` splits those apart. A committed
registry names artifacts and records their hashes; an uncommitted, machine-local roots file
says where the storage actually is. The same notebook then runs on a laptop and on a shared
cluster node without an edit.

```python
from datapaths import Datapaths

dp = Datapaths()
path = dp["features_train_v02"]          # -> absolute Path on this machine
df   = dp.load("features_train_v02")     # or read it directly

dp.save(df, name="features_train_v03", type="features", fmt="parquet",
        tags=["v03", "bazin"], notes="after the CC-1 rename")
```

## Install

Nothing is published to PyPI. Install from the repository.

```bash
# From a clone, for development -- edits are picked up immediately by every
# environment that installed it this way.
pip install -e /path/to/datapaths

# From git, for a server, CI, or a fresh machine.
pip install "datapaths @ git+https://github.com/ShrRa/datapaths.git@main"
```

In a consuming project, put the git form in `pyproject.toml` and it resolves like any other
dependency. Pin `@main` to always track the tip, or `@v0.2.0` / `@<sha>` where a project
needs to be reproducible — you get versioning only where you actually want it.

Add the `tabular` extra if the project saves or loads parquet/csv artifacts:
`pip install "datapaths[tabular] @ git+..."`.

## The two config files

**`configs/roots.local.yaml`** — machine-local, **never committed**. Maps root names to
absolute paths:

```yaml
data: /mnt/beegfs/scratch/alex/mallorn/data
features: /mnt/beegfs/scratch/alex/mallorn/features
models: /mnt/beegfs/scratch/alex/mallorn/models
predictions: /mnt/beegfs/scratch/alex/mallorn/predictions
misc: /mnt/beegfs/scratch/alex/mallorn/misc
```

**`configs/artifacts_registry.yaml`** — committed. One record per artifact: its relative
path under a root, format, sha256, tags, notes, timestamps. This is the file that makes an
artifact reference mean the same thing to two people.

Both are found relative to the repository root, which is discovered by walking up from the
current working directory looking for `pyproject.toml` or `.git`.

## Overriding where the config files live

The `configs/` names above are a default, not a requirement. Three environment variables
override them, so a repository that organises itself differently — or a job whose working
directory is somewhere else entirely — does not have to change any call site:

| Variable | Effect |
|---|---|
| `DATAPATHS_REPO_ROOT` | Use this directory as the repository root instead of discovering one |
| `DATAPATHS_ROOTS_FILE` | Path to the roots file |
| `DATAPATHS_REGISTRY_FILE` | Path to the registry file |

The two file variables accept either an absolute path (used as-is) or a path relative to the
repo root (resolved against it).

```bash
export DATAPATHS_REPO_ROOT=/home/alex/Data/Work/Github/mallorn_tde
export DATAPATHS_ROOTS_FILE=etc/roots.yaml            # relative to the repo root
export DATAPATHS_REGISTRY_FILE=/shared/registry.yaml  # absolute
```

Precedence, per setting, is: **explicit argument → environment variable → default**.

```python
Datapaths()                                  # env vars, else configs/ defaults
Datapaths(repo_root=Path("/some/repo"))      # pins the root, env still fills the filenames
Datapaths(registry_file="etc/registry.yaml") # pins the registry, ignores its env var
```

An argument you pass is never overridden by an environment variable that happens to be set
in the shell — a caller that names a file means it.

`DATAPATHS_REPO_ROOT` is the one worth setting habitually. Root discovery starts from the
*working directory*, so a notebook, a scheduled job, or a shell started in the wrong place
will otherwise silently resolve against whichever repository happens to be above it.

## CLI

Installed as `datapaths`:

```bash
datapaths list --type features --tag v02
datapaths verify --type features          # re-hash and report drift
datapaths register --name my_table --type features --file /tmp/x.parquet --fmt parquet
```

`verify` is the one that earns its keep: it re-hashes what is on disk against what the
registry claims, so an artifact that was regenerated without being re-registered is caught
rather than quietly used.

## Layout

| Module | Responsibility |
|---|---|
| `datapaths.py` | The `Datapaths` class — resolve, load, save, register, list, verify |
| `config.py` | Repo-root discovery, env overrides, roots file |
| `registry.py` | Read/write the registry YAML under a file lock |
| `artifacts.py` | Canonical relative paths, atomic writes, archiving |
| `hashing.py` | sha256 of files and bytes |
| `cli.py` | `datapaths` command |
| `exceptions.py` | `DatapathsError` and friends |

Writes go through a temp file and `Path.replace`, and registry updates take a `filelock`, so
a crashed or concurrent run does not leave a half-written artifact or a corrupted registry.
Overwriting a registered artifact moves the old file into `_archive/` under a name carrying
its timestamp and short hash rather than deleting it.

## Status

Extracted from the `mallorn_tde` repository, where it had been copied by hand into several
projects. No test suite yet — that is the first thing to add, since it is now a dependency
that can break several projects at once.
