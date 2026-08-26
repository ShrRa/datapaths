# AGENTS.md

This file provides guidance to agentic AI tools (Claude Code, ChatGPT Codex, etc.) when working with code in this repository.

## Commands

```bash
pip install -e ".[tabular,dev]"   # editable install with test + tabular deps
pytest                            # full suite, ~4 seconds
pytest tests/test_save.py -x      # single file, stop on first failure
```

CI runs the suite on Linux, macOS and Windows against Python 3.10, 3.12 and 3.14, plus one
job without the `tabular` extra — the parquet/csv tests skip themselves there rather than
failing, so a consumer that only resolves paths can still run the suite. Do not make a test
depend on `pandas`/`pyarrow` without guarding it the same way.

## Layout

| Module | Responsibility |
|---|---|
| `src/datapaths/datapaths.py` | The `Datapaths` class — resolve, save, register, list, print_paths, verify |
| `src/datapaths/config.py` | Repo-root discovery, env overrides, roots file |
| `src/datapaths/registry.py` | Read/write the registry YAML under a file lock |
| `src/datapaths/artifacts.py` | Canonical relative paths, atomic writes, archiving |
| `src/datapaths/hashing.py` | sha256 of files and bytes |
| `src/datapaths/cli.py` | `datapaths` command |
| `src/datapaths/exceptions.py` | `DatapathsError` and friends |

See `docs/architecture.md` for the durability guarantees behind these.

## Invariants — do not break these

* **Writes are atomic.** Serialize to a staging file, hash it, then `shutil.move` into
  place, with a `finally` that unlinks the stage. Never write directly to the destination.
* **Registry mutations take the `filelock`.** Always go through `update_registry_atomic`;
  never read-modify-write the registry YAML directly.
* **Overwrites archive, never delete.** The displaced file moves into `_archive/` with a
  timestamp and short hash.
* **Registry paths are stored POSIX-style** (`rel.as_posix()`), because the registry is
  committed and read on other machines.
* **`ArtifactType` is advisory.** It is a `Literal` for editors only and must never be
  enforced at runtime — any string is a valid type.
* **Validate safety, never convention.** Names are checked only for things that make them
  unsafe as a filename (separators, traversal, a leading dot or tilde, control characters).
  Do not re-add rules about how a name should be *shaped* — underscore counts, prefixes,
  version suffixes. That belongs to the project using the package. A four-part naming rule
  for `type="features"` was removed for exactly this reason.
* **Layout does not depend on type.** Every artifact is `{root}/{name}.{ext}`. `type`
  selects the root and nothing else; `relpath=` is how a caller asks for a subdirectory.
* **`TYPE_TO_ROOT` ships empty.** It is an escape hatch for a consuming project, not a
  vocabulary. Do not populate it with defaults.
* **Tests must not assume POSIX separators or a case-sensitive filesystem.** CI runs on
  Windows and macOS.

Two tests exist specifically to catch regressions in the above, and are worth knowing about
because they fail loudly if the protection they cover is ever removed:

* `tests/test_registry_concurrency.py` runs two processes appending to one registry and
  checks that neither loses the other's entries. With the `filelock` removed it does not
  merely drop records — it leaves the registry as unparseable YAML.
* `tests/test_save.py::TestAtomicity` interrupts a write part-way and asserts nothing is
  left behind. Staging temp files that outlive a failed write accumulate invisibly in the
  data root.

## Documentation

Documentation lives in `docs/` apart from `AGENTS.md` and `README.md` that live in the root of the repo.

| File | Contents |
|---|---|
| `README.md` | User-facing: pitch, install, usage examples, config basics, CLI |
| `docs/configuration.md` | Roots and registry files, env overrides, precedence, collision warnings |
| `docs/artifact-types.md` | Types, `TYPE_TO_ROOT`, root fallback, family nesting |
| `docs/registering.md` | `register` vs `save`, `src_path` vs `relpath`, canonical copies |
| `docs/architecture.md` | Module table, atomicity, locking, archiving |
| `docs/backlog.md` | Known bugs and planned functionality |
| `docs/changelog.md` | Introduced changes |

Keep reference detail in `docs/` and keep the README short — it is the page a new user
reads. When adding a section, ask whether it answers a question a first-time user is
actually asking yet; if not, it belongs in `docs/`.

## Workflow

Before editing the code, perform `git pull`. 
Before starting to implement new feature or a refactoring, ask the user whether you should create a new branch for it. 

After implementing a new feature or doing a major refactoring:
- Add changes to `docs/changelog.md`. 
- If these features or bugs were mentioned in `docs/backlog.md`, move their description from there to `docs/changelog.md` and remove them from the backlog. 
- Re-read README.md and AGENTS.md, update to reflect recent changes.
- Run the tests.
- At the end of the round of changes, ask whether the branch should be merged to main (or to some other branch).
- After each round of editing the code, commit the changes to git and run `git push`.
