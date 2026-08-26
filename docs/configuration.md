# Configuration

`datapaths` reads two files. One is committed and shared; the other is machine-local and
never committed. Everything on this page is about where they are found and how they may go
wrong.

## The two files

### `configs/roots.local.yaml` — machine-local, never committed

Maps root names to absolute directories:

```yaml
data: /mnt/beegfs/scratch/grumpy_hippo/var_stars/data
features: /mnt/beegfs/scratch/grumpy_hippo/var_stars/features
models: /mnt/beegfs/scratch/grumpy_hippo/var_stars/models
predictions: /mnt/beegfs/scratch/grumpy_hippo/var_stars/predictions
misc: /mnt/beegfs/scratch/grumpy_hippo/var_stars/misc
```

Every root must exist on disk and be an absolute path.

Note there is **no top-level wrapper key** — the entries sit at the top level. (The registry
file *does* nest everything under `artifacts:`, which makes this an easy mistake.) An entry
that isn't a name mapped to a single path is skipped with a `ConfigWarning` naming it; if
that leaves no roots at all, `load_roots` raises rather than handing back an empty mapping
that would fail later as an unexplained `KeyError`.

### `configs/artifacts_registry.yaml` — committed

One record per artifact: its relative path under a root, format, sha256, tags, notes,
timestamps. This is the file that makes an artifact reference mean the same thing to two
people.

Both are found relative to the repository root, which is discovered by walking up from the
current working directory looking for `pyproject.toml` or `.git`.

## Root name matching

Root names are matched **exactly**. `dp["FEATURES"]` will not find a root called `features`
— though the error says so and suggests the near miss.

An artifact and a root may share a name. `dp["features"]` prefers the root; prefix the key
with `root_` to force a root lookup and skip the registry entirely:

```python
dp["root_features"]     # always the root directory
```

## Collision warnings

Three things about a roots file draw a `ConfigWarning` without refusing to load it:

1. Two names differing only in case.
2. **Two names pointing at the same directory** — checked with `samefile`, so a symlink or a
   case-insensitive filesystem counts.
3. Two paths differing only in case, where nothing on disk can settle whether they are one
   directory.

The second is the dangerous one: artifacts of both roots share a tree, so two records can
resolve to the same file and overwrite each other while `verify` reports both `OK`.

## Overriding where the config files live

The `configs/` names are a default, not a requirement. Three environment variables override
them, so a repository that organises itself differently — or a job whose working directory
is somewhere else entirely — does not have to change any call site:

| Variable | Effect |
|---|---|
| `DATAPATHS_REPO_ROOT` | Use this directory as the repository root instead of discovering one |
| `DATAPATHS_ROOTS_FILE` | Path to the roots file |
| `DATAPATHS_REGISTRY_FILE` | Path to the registry file |

The two file variables accept either an absolute path (used as-is) or a path relative to the
repo root (resolved against it).

```bash
export DATAPATHS_REPO_ROOT=/home/grumpy_hippo/Data/Work/Github/var_stars_project
export DATAPATHS_ROOTS_FILE=etc/roots.yaml            # relative to the repo root
export DATAPATHS_REGISTRY_FILE=/shared/registry.yaml  # absolute paths work too (but for collaborative work, make sure its committed)
```

`DATAPATHS_REPO_ROOT` is the one worth setting habitually. Root discovery starts from the
*working directory*, so a notebook, a scheduled job, or a shell started in the wrong place
will otherwise silently resolve against whichever repository happens to be above it.

## Precedence

Per setting: **explicit argument → environment variable → default**.

```python
Datapaths()                                  # env vars, else configs/ defaults
Datapaths(repo_root=Path("/some/repo"))      # pins the root, env still fills the filenames
Datapaths(registry_file="etc/registry.yaml") # pins the registry, ignores its env var
```

An argument you pass is never overridden by an environment variable that happens to be set
in the shell — a caller that names a file means it.

## Tags

Tags are normalized on the way in and on the way out: every tag is stripped and lowercased,
and a string containing commas is split into several tags.

```python
dp.save(df, name="x", type="misc", fmt="json", tags=["V02", " Bazin "])
dp.get("x", field="tags")     # ['bazin', 'v02'] -- lowercased and sorted
```

Two consequences, both intended:

* **A tag cannot contain a comma.** Commas are the separator, which is what makes
  `--tag v02,bazin` on the CLI mean "both tags required" rather than one literal tag that
  could never match anything.
* **A tag cannot carry case.** `V02` and `v02` are the same tag. The registry is a committed
  file that people read, so two entry points writing the same tag differently would make it
  inconsistent with itself.

Filtering normalizes the query the same way, so `tag="V02"` matches a stored `v02`. Tag
matching is AND across every tag given:

```python
dp.list(tag=["v03", "bazin"])   # records carrying both
dp.list(tag="v03,bazin")        # the same query
```

Note this differs from root names, which are matched **exactly** and are case-sensitive.
